import { useCallback } from 'react';
import { useReport } from '@/contexts/ReportContext';
import { VIEW_TITLE_MAP, VIEW_TABLE_CONFIGS, ALL_MONTHS, isAllZeroTable, type NoteView } from '@/config/viewConfigs';
import { exportToExcel, type ExportSheet, type SummarySheetDef, type DetailSheetDef, type PlanillaExportRow } from '@/utils/exportExcel';
import type { ReportData, ReportRow, DisplayColumn, Month, MonthSource } from '@/types';
import type { HeadcountMap } from '@/features/dashboard/useHeadcount';
import { useHeadcount } from '@/features/dashboard/useHeadcount';
import { getCellValue, getSummaryTotal } from '@/utils/cellValue';
import { getDataKeyForTable } from '@/utils/dataKeyMapping';
import { buildCecoGroups, buildCuentaEntries, sumRows } from '@/utils/cecoGrouping';

// ── Planilla grouping (mirrors PlanillaTable hierarchy) ─────────────

const PARTIDA_PL_ORDER = [
    'INGRESOS ORDINARIOS', 'INGRESOS PROYECTOS',
    'COSTO', 'D&A - COSTO',
    'GASTO VENTA', 'GASTO ADMIN',
    'PARTICIPACION DE TRABAJADORES', 'D&A - GASTO',
    'PROVISION INCOBRABLE', 'OTROS INGRESOS', 'OTROS EGRESOS',
    'RESULTADO FINANCIERO', 'DIFERENCIA DE CAMBIO',
    'IMPUESTO A LA RENTA', 'POR CLASIFICAR',
];
const PARTIDA_ORDER_INDEX = new Map(PARTIDA_PL_ORDER.map((p, i) => [p, i]));

interface PlanillaCeco {
    code: string;
    desc: string;
    totals: Record<string, number>;
    cuentaRows: ReportRow[];
}

interface PlanillaPartida {
    name: string;
    totals: Record<string, number>;
    cecos: PlanillaCeco[];
}

function buildPlanillaHierarchy(rows: ReportRow[], columns: DisplayColumn[]): PlanillaPartida[] {
    const monthKeys = new Set<string>();
    for (const col of columns) {
        for (const m of col.sourceMonths) monthKeys.add(m);
    }

    const sumMonths = (rws: ReportRow[]): Record<string, number> => {
        const sums: Record<string, number> = {};
        for (const row of rws) {
            for (const m of monthKeys) sums[m] = (sums[m] ?? 0) + ((row[m] as number) ?? 0);
            sums['TOTAL'] = (sums['TOTAL'] ?? 0) + ((row['TOTAL'] as number) ?? 0);
        }
        return sums;
    };

    const partidaMap = new Map<string, Map<string, { desc: string; rows: ReportRow[] }>>();
    for (const row of rows) {
        const partida = String(row['PARTIDA_PL'] ?? '');
        const ceco = String(row['CENTRO_COSTO'] ?? '');
        const cecoDesc = String(row['DESC_CECO'] ?? '');
        if (!partida) continue;
        if (!partidaMap.has(partida)) partidaMap.set(partida, new Map());
        const cecoMap = partidaMap.get(partida)!;
        if (!cecoMap.has(ceco)) cecoMap.set(ceco, { desc: cecoDesc, rows: [] });
        cecoMap.get(ceco)!.rows.push(row);
    }

    const result: PlanillaPartida[] = [];
    for (const [partidaName, cecoMap] of partidaMap) {
        const cecos: PlanillaCeco[] = [];
        const allRows: ReportRow[] = [];
        for (const [cecoCode, { desc, rows: cecoRows }] of cecoMap) {
            cecos.push({ code: cecoCode, desc, totals: sumMonths(cecoRows), cuentaRows: cecoRows });
            allRows.push(...cecoRows);
        }
        cecos.sort((a, b) => a.code.localeCompare(b.code));
        result.push({ name: partidaName, totals: sumMonths(allRows), cecos });
    }

    const fallback = PARTIDA_PL_ORDER.length;
    result.sort((a, b) =>
        (PARTIDA_ORDER_INDEX.get(a.name) ?? fallback) - (PARTIDA_ORDER_INDEX.get(b.name) ?? fallback)
    );
    return result;
}

// ── Headcount helpers (mirrors PlanillaTable) ───────────────────────

const MONTH_TO_NUM: Record<Month, number> = Object.fromEntries(
    ALL_MONTHS.map((m, i) => [m, i + 1])
) as Record<Month, number>;

function buildColYm(columns: DisplayColumn[], selectedYear: number, monthSources: MonthSource[] | null): Map<DisplayColumn, string> {
    const map = new Map<DisplayColumn, string>();
    if (monthSources) {
        const srcMap = new Map<Month, string>();
        for (const s of monthSources) srcMap.set(s.month, String(s.year * 100 + MONTH_TO_NUM[s.month]));
        for (const col of columns) {
            const ym = srcMap.get(col.sourceMonths[0]);
            if (ym !== undefined) map.set(col, ym);
        }
    } else {
        for (const col of columns) {
            const num = MONTH_TO_NUM[col.sourceMonths[0]];
            if (num !== undefined) map.set(col, String(selectedYear * 100 + num));
        }
    }
    return map;
}

function hcForCol(cecoData: Record<string, number> | undefined, col: DisplayColumn, colYm: Map<DisplayColumn, string>): number | null {
    if (!cecoData) return null;
    const ym = colYm.get(col);
    if (ym === undefined) return null;
    const hc = cecoData[ym];
    return hc != null && hc > 0 ? hc : null;
}

function hcAvg(cecoData: Record<string, number> | undefined, colYm: Map<DisplayColumn, string>): number | null {
    if (!cecoData) return null;
    let sum = 0, count = 0;
    const seen = new Set<string>();
    for (const ym of colYm.values()) {
        if (seen.has(ym)) continue;
        seen.add(ym);
        const hc = cecoData[ym];
        if (hc != null && hc > 0) { sum += hc; count++; }
    }
    return count > 0 ? sum / count : null;
}

// ── Finanzas (ExpandableFinancialTable) export ──────────────────────

/** Map each expandable PARTIDA_PL to its _by_cuenta data key */
const PARTIDA_TO_DATA_KEY: Record<string, keyof ReportData> = {
    'COSTO': 'costo_by_cuenta',
    'GASTO VENTA': 'gasto_venta_by_cuenta',
    'GASTO ADMIN': 'gasto_admin_by_cuenta',
    'D&A - COSTO': 'dya_costo_by_cuenta',
    'D&A - GASTO': 'dya_gasto_by_cuenta',
    'OTROS INGRESOS': 'otros_ingresos_by_cuenta',
    'OTROS EGRESOS': 'otros_egresos_by_cuenta',
    'PARTICIPACION DE TRABAJADORES': 'participacion_by_cuenta',
    'PROVISION INCOBRABLE': 'provision_by_cuenta',
};

/** Partida order matching the website's ExpandableFinancialTable */
const FINANZAS_PARTIDA_ORDER = [
    'COSTO', 'D&A - COSTO', 'GASTO VENTA', 'GASTO ADMIN',
    'PARTICIPACION DE TRABAJADORES', 'D&A - GASTO',
    'PROVISION INCOBRABLE', 'OTROS INGRESOS', 'OTROS EGRESOS',
] as const;

function buildFinanzasRows(
    summaryRows: ReportRow[],
    columns: DisplayColumn[],
    getMergedDetailRows: (key: keyof ReportData, labelKeys: string[]) => ReportRow[],
): PlanillaExportRow[] {
    const cecoKeys = ['CENTRO_COSTO', 'DESC_CECO', 'CUENTA_CONTABLE', 'DESCRIPCION'];
    const flat: PlanillaExportRow[] = [];

    // Build a lookup from summaryRows for quick access
    const summaryByPartida = new Map(
        summaryRows.map(r => [r['PARTIDA_PL'] as string, r]),
    );

    for (const label of FINANZAS_PARTIDA_ORDER) {
        const row = summaryByPartida.get(label);
        if (!row) continue;

        // Level 0: summary partida row — use getSummaryTotal for TOTAL
        const vals: Record<string, number> = {};
        for (const col of columns) {
            const v = getCellValue(row, col);
            if (v !== null) vals[col.sourceMonths[0]] = v;
        }
        const total = getSummaryTotal(row, columns, 'pl');
        if (total !== null) vals['TOTAL'] = total;
        flat.push({ label, level: 0, values: vals });

        // Expand detail data for this partida
        const dataKey = PARTIDA_TO_DATA_KEY[label];
        if (!dataKey) continue;

        const detailRows = getMergedDetailRows(dataKey, cecoKeys);
        const cecoGroups = buildCecoGroups(detailRows, columns);

        for (const group of cecoGroups) {
            // Level 1: CECO group
            const gVals: Record<string, number> = {};
            for (const col of columns) {
                const v = getCellValue(group.data, col);
                if (v !== null) gVals[col.sourceMonths[0]] = v;
            }
            gVals['TOTAL'] = (group.data['TOTAL'] as number) ?? 0;
            flat.push({ label: group.label, level: 1, values: gVals });

            // Level 2: cuenta entries (grouped by prefix category)
            const entries = buildCuentaEntries(group.cuentaRows, columns);
            for (const entry of entries) {
                const eVals: Record<string, number> = {};
                let src: ReportRow;
                let eLabel: string;
                if (entry.prefix !== null) {
                    src = entry.data;
                    eLabel = entry.label;
                } else {
                    src = entry.row;
                    eLabel = `${src['CUENTA_CONTABLE']} ${src['DESCRIPCION']}`;
                }
                for (const col of columns) {
                    const v = getCellValue(src, col);
                    if (v !== null) eVals[col.sourceMonths[0]] = v;
                }
                eVals['TOTAL'] = (src['TOTAL'] as number) ?? 0;
                flat.push({ label: eLabel, level: 2, values: eVals });
            }
        }
    }

    return flat;
}

// ── Flujo de Caja export ───────────────────────────────────────────

const FLUJO_DATA_KEYS: Record<string, keyof ReportData> = {
    ingresos_ord: 'flujo_ingresos_ord_by_cuenta',
    ingresos_proy: 'flujo_ingresos_proy_by_cuenta',
    costo: 'flujo_costo_by_cuenta',
    gasto_venta: 'flujo_gasto_venta_by_cuenta',
    gasto_admin: 'flujo_gasto_admin_by_cuenta',
    participacion: 'flujo_participacion_by_cuenta',
    otros_ingresos: 'flujo_otros_ingresos_by_cuenta',
    otros_egresos: 'flujo_otros_egresos_by_cuenta',
};

interface FlujoRowDef {
    key: string;
    label: string;
    isComputed: boolean;
    hasCeco?: boolean;
    sumOf?: string[];
}

interface FlujoSectionDef {
    title: string;
    rows: FlujoRowDef[];
}

const FLUJO_SECTIONS: FlujoSectionDef[] = [
    {
        title: 'Ingresos',
        rows: [
            { key: 'ingresos_ord', label: 'Ingresos Ordinarios', isComputed: false, hasCeco: false },
            { key: 'ingresos_proy', label: 'Ingresos Proyectos', isComputed: false, hasCeco: false },
            { key: 'total_ingresos', label: 'Total Ingresos', isComputed: true, sumOf: ['ingresos_ord', 'ingresos_proy'] },
        ],
    },
    {
        title: 'Gastos',
        rows: [
            { key: 'costo', label: 'Costo', isComputed: false, hasCeco: true },
            { key: 'gasto_venta', label: 'Gasto Venta', isComputed: false, hasCeco: true },
            { key: 'gasto_admin', label: 'Gasto Admin', isComputed: false, hasCeco: true },
            { key: 'participacion', label: 'Participacion de Trabajadores', isComputed: false, hasCeco: true },
            { key: 'total_gastos', label: 'Total Gastos', isComputed: true, sumOf: ['costo', 'gasto_venta', 'gasto_admin', 'participacion'] },
        ],
    },
    {
        title: 'Otros',
        rows: [
            { key: 'otros_ingresos', label: 'Otros Ingresos', isComputed: false, hasCeco: true },
            { key: 'otros_egresos', label: 'Otros Egresos', isComputed: false, hasCeco: true },
            { key: 'total_otros', label: 'Total Otros', isComputed: true, sumOf: ['otros_ingresos', 'otros_egresos'] },
        ],
    },
];

const FLUJO_GRAND_TOTAL: FlujoRowDef = {
    key: 'total', label: 'TOTAL', isComputed: true,
    sumOf: ['ingresos_ord', 'ingresos_proy', 'costo', 'gasto_venta', 'gasto_admin', 'participacion', 'otros_ingresos', 'otros_egresos'],
};

function buildFlujoCajaRows(
    columns: DisplayColumn[],
    getMergedDetailRows: (key: keyof ReportData, labelKeys: string[]) => ReportRow[],
): PlanillaExportRow[] {
    const cecoKeys = ['CENTRO_COSTO', 'DESC_CECO', 'CUENTA_CONTABLE', 'DESCRIPCION'];
    const cuentaKeys = ['CUENTA_CONTABLE', 'DESCRIPCION'];

    // Fetch and compute totals for each data partida
    const allDefs = FLUJO_SECTIONS.flatMap(s => s.rows);
    const dataRows = new Map<string, { totalRow: Record<string, number>; cecoGroups: ReturnType<typeof buildCecoGroups>; rawRows: ReportRow[]; hasCeco: boolean }>();
    for (const def of allDefs) {
        if (def.isComputed) continue;
        const dataKey = FLUJO_DATA_KEYS[def.key];
        if (!dataKey) continue;
        const keys = def.hasCeco ? cecoKeys : cuentaKeys;
        const rows = getMergedDetailRows(dataKey, keys);
        const cecoGroups = def.hasCeco ? buildCecoGroups(rows, columns) : [];
        const totalRow = sumRows(rows, columns);
        dataRows.set(def.key, { totalRow, cecoGroups, rawRows: rows, hasCeco: def.hasCeco ?? false });
    }

    const computeSum = (keys: string[]): Record<string, number> => {
        const sums: Record<string, number> = {};
        for (const key of keys) {
            const d = dataRows.get(key);
            if (!d) continue;
            for (const [m, v] of Object.entries(d.totalRow)) {
                if (typeof v === 'number') sums[m] = (sums[m] ?? 0) + v;
            }
        }
        return sums;
    };

    const emitDataRow = (def: FlujoRowDef, flat: PlanillaExportRow[]) => {
        const d = dataRows.get(def.key);
        if (!d) return;

        flat.push({ label: def.label, level: 0, values: d.totalRow });

        if (d.hasCeco) {
            for (const group of d.cecoGroups) {
                const gVals: Record<string, number> = {};
                for (const col of columns) {
                    const v = getCellValue(group.data, col);
                    if (v !== null) gVals[col.sourceMonths[0]] = v;
                }
                gVals['TOTAL'] = (group.data['TOTAL'] as number) ?? 0;
                flat.push({ label: group.label, level: 1, values: gVals });

                for (const row of group.cuentaRows) {
                    const cuenta = String(row['CUENTA_CONTABLE'] ?? '');
                    if (!cuenta || cuenta === 'TOTAL') continue;
                    const desc = String(row['DESCRIPCION'] ?? '');
                    const eVals: Record<string, number> = {};
                    for (const col of columns) {
                        const v = getCellValue(row, col);
                        if (v !== null) eVals[col.sourceMonths[0]] = v;
                    }
                    eVals['TOTAL'] = (row['TOTAL'] as number) ?? 0;
                    flat.push({ label: `${cuenta} ${desc}`, level: 2, values: eVals });
                }
            }
        } else {
            for (const row of d.rawRows) {
                const cuenta = String(row['CUENTA_CONTABLE'] ?? '');
                if (!cuenta || cuenta === 'TOTAL') continue;
                const desc = String(row['DESCRIPCION'] ?? '');
                const eVals: Record<string, number> = {};
                for (const col of columns) {
                    const v = getCellValue(row, col);
                    if (v !== null) eVals[col.sourceMonths[0]] = v;
                }
                eVals['TOTAL'] = (row['TOTAL'] as number) ?? 0;
                flat.push({ label: `${cuenta} ${desc}`, level: 1, values: eVals });
            }
        }
    };

    const flat: PlanillaExportRow[] = [];

    for (const section of FLUJO_SECTIONS) {
        // Section header (empty values row)
        flat.push({ label: section.title, level: 0, values: {} });

        for (const def of section.rows) {
            if (def.isComputed) {
                flat.push({ label: def.label, level: 0, values: computeSum(def.sumOf!) });
            } else {
                emitDataRow(def, flat);
            }
        }
    }

    // Grand total
    flat.push({ label: FLUJO_GRAND_TOTAL.label, level: 0, values: computeSum(FLUJO_GRAND_TOTAL.sumOf!) });

    return flat;
}

// ── Sheet builders ──────────────────────────────────────────────────

/** Sheet 1: Gasto (expense amounts) */
function buildExpenseRows(partidas: PlanillaPartida[]): PlanillaExportRow[] {
    const flat: PlanillaExportRow[] = [];
    for (const p of partidas) {
        flat.push({ label: p.name, level: 0, values: p.totals });
        for (const c of p.cecos) {
            flat.push({ label: `${c.code} ${c.desc}`, level: 1, values: c.totals });
            for (const row of c.cuentaRows) {
                const vals: Record<string, number> = {};
                for (const k of Object.keys(c.totals)) vals[k] = (row[k] as number) ?? 0;
                flat.push({ label: `${row['CUENTA_CONTABLE']} ${row['DESCRIPCION']}`, level: 2, values: vals });
            }
        }
    }
    return flat;
}

/** Sheet 2: Headcount (HC per CECO, summed at partida level) */
function buildHeadcountRows(
    partidas: PlanillaPartida[], headcountMap: HeadcountMap, columns: DisplayColumn[], colYm: Map<DisplayColumn, string>,
): PlanillaExportRow[] {
    const flat: PlanillaExportRow[] = [];
    for (const p of partidas) {
        // Partida-level: sum HC across CECOs
        const pVals: Record<string, number> = {};
        for (const col of columns) {
            let total = 0;
            for (const c of p.cecos) {
                const hc = hcForCol(headcountMap[c.code], col, colYm);
                if (hc) total += hc;
            }
            pVals[col.sourceMonths[0]] = total;
        }
        // Average for total column
        let avgSum = 0;
        for (const c of p.cecos) {
            const avg = hcAvg(headcountMap[c.code], colYm);
            if (avg) avgSum += avg;
        }
        pVals['TOTAL'] = Math.round(avgSum);
        flat.push({ label: p.name, level: 0, values: pVals });

        // CECO-level
        for (const c of p.cecos) {
            const cVals: Record<string, number> = {};
            const cecoData = headcountMap[c.code];
            for (const col of columns) {
                const hc = hcForCol(cecoData, col, colYm);
                cVals[col.sourceMonths[0]] = hc ?? 0;
            }
            const avg = hcAvg(cecoData, colYm);
            cVals['TOTAL'] = avg != null ? Math.round(avg) : 0;
            flat.push({ label: `${c.code} ${c.desc}`, level: 1, values: cVals });
        }
    }
    return flat;
}

/** Sheet 3: % de Ingresos */
function buildPctRows(
    partidas: PlanillaPartida[], revenueRow: ReportRow, columns: DisplayColumn[],
): PlanillaExportRow[] {
    const pct = (cost: number | null, rev: number | null): number =>
        cost != null && rev != null && rev !== 0 ? (cost / rev) * 100 : 0;

    const buildVals = (totals: Record<string, number> | ReportRow): Record<string, number> => {
        const vals: Record<string, number> = {};
        for (const col of columns) {
            const costVal = getCellValue(totals as ReportRow, col);
            const revVal = getCellValue(revenueRow, col);
            vals[col.sourceMonths[0]] = pct(costVal, revVal);
        }
        const costTotal = (totals as Record<string, number>)['TOTAL'] ?? null;
        const revTotal = (revenueRow['TOTAL'] as number) ?? null;
        vals['TOTAL'] = pct(costTotal, revTotal);
        return vals;
    };

    const flat: PlanillaExportRow[] = [];
    for (const p of partidas) {
        flat.push({ label: p.name, level: 0, values: buildVals(p.totals) });
        for (const c of p.cecos) {
            flat.push({ label: `${c.code} ${c.desc}`, level: 1, values: buildVals(c.totals) });
            for (const row of c.cuentaRows) {
                flat.push({ label: `${row['CUENTA_CONTABLE']} ${row['DESCRIPCION']}`, level: 2, values: buildVals(row) });
            }
        }
    }
    return flat;
}

/** Sheet 4: Gasto / HC (per-worker cost) */
function buildPerWorkerRows(
    partidas: PlanillaPartida[], headcountMap: HeadcountMap, columns: DisplayColumn[], colYm: Map<DisplayColumn, string>,
): PlanillaExportRow[] {
    const pw = (cost: number | null, hc: number | null): number =>
        cost != null && hc != null && hc > 0 ? cost / hc : 0;

    const flat: PlanillaExportRow[] = [];
    for (const p of partidas) {
        // Partida-level: aggregate cost & hc across CECOs
        const pVals: Record<string, number> = {};
        for (const col of columns) {
            let costSum = 0, hcSum = 0;
            for (const c of p.cecos) {
                const hc = hcForCol(headcountMap[c.code], col, colYm);
                if (hc && hc > 0) {
                    costSum += (c.totals[col.sourceMonths[0]] ?? 0);
                    hcSum += hc;
                }
            }
            pVals[col.sourceMonths[0]] = pw(costSum, hcSum);
        }
        // Total: aggregate cost & avg hc
        let costTotal = 0, hcTotal = 0;
        for (const c of p.cecos) {
            const avg = hcAvg(headcountMap[c.code], colYm);
            if (avg && avg > 0) {
                costTotal += (c.totals['TOTAL'] ?? 0);
                hcTotal += avg;
            }
        }
        pVals['TOTAL'] = pw(costTotal, hcTotal);
        flat.push({ label: p.name, level: 0, values: pVals });

        // CECO-level
        for (const c of p.cecos) {
            const cecoData = headcountMap[c.code];
            const cVals: Record<string, number> = {};
            for (const col of columns) {
                const hc = hcForCol(cecoData, col, colYm);
                const cost = getCellValue(c.totals as ReportRow, col);
                cVals[col.sourceMonths[0]] = pw(cost, hc);
            }
            const avg = hcAvg(cecoData, colYm);
            cVals['TOTAL'] = pw(c.totals['TOTAL'] ?? null, avg);
            flat.push({ label: `${c.code} ${c.desc}`, level: 1, values: cVals });

            // Cuenta-level (inherits CECO headcount)
            for (const row of c.cuentaRows) {
                const vals: Record<string, number> = {};
                for (const col of columns) {
                    const hc = hcForCol(cecoData, col, colYm);
                    const cost = getCellValue(row, col);
                    vals[col.sourceMonths[0]] = pw(cost, hc);
                }
                const avg2 = hcAvg(cecoData, colYm);
                vals['TOTAL'] = pw((row['TOTAL'] as number) ?? null, avg2);
                flat.push({ label: `${row['CUENTA_CONTABLE']} ${row['DESCRIPCION']}`, level: 2, values: vals });
            }
        }
    }
    return flat;
}

// ═══════════════════════════════════════════════════════════════════════

export function useViewExport(): { handleExport: () => void; canExport: boolean } {
    const {
        currentView, reportData, selectedCompany, selectedYear,
        getDisplayColumns, getMergedRows, getMergedDetailRows,
        periodRange, isLoading, trailingMonthSources,
    } = useReport();

    const { headcount: headcountMap } = useHeadcount(selectedCompany, selectedYear, periodRange);

    const canExport = !!reportData && !isLoading;

    const handleExport = useCallback(() => {
        if (!reportData) return;

        const sheets: ExportSheet[] = [];
        const viewTitle = VIEW_TITLE_MAP[currentView] ?? currentView;

        if (currentView === 'pl') {
            const rows = getMergedRows('pl_summary', 'PARTIDA_PL', 'pl');
            const sheet: SummarySheetDef = {
                kind: 'summary',
                sheetName: viewTitle,
                rows,
                columns: getDisplayColumns('pl'),
                labelKey: 'PARTIDA_PL',
                showTotal: true,
                variant: 'pl',
            };
            sheets.push(sheet);
        } else if (currentView === 'bs') {
            const rows = getMergedRows('bs_summary', 'PARTIDA_BS', 'bs');
            const sheet: SummarySheetDef = {
                kind: 'summary',
                sheetName: viewTitle,
                rows,
                columns: getDisplayColumns('bs'),
                labelKey: 'PARTIDA_BS',
                showTotal: false,
                variant: 'bs',
            };
            sheets.push(sheet);
        } else if (currentView === 'analysis_planilla') {
            const planillaKeys = ['PARTIDA_PL', 'CENTRO_COSTO', 'DESC_CECO', 'CUENTA_CONTABLE', 'DESCRIPCION'];
            const planillaRows = getMergedDetailRows('planilla_by_cuenta', planillaKeys);
            const cols = getDisplayColumns('pl');
            const partidas = buildPlanillaHierarchy(planillaRows, cols);
            const monthSources = periodRange === 'trailing12' ? trailingMonthSources : null;
            const colYm = buildColYm(cols, selectedYear, monthSources);

            // Sheet 1: Gasto
            sheets.push({
                kind: 'planilla',
                sheetName: 'Gasto',
                flatRows: buildExpenseRows(partidas),
                columns: cols,
                year: selectedYear,
            });

            // Sheet 2: Headcount (only if data available)
            if (headcountMap && Object.keys(headcountMap).length > 0) {
                sheets.push({
                    kind: 'planilla',
                    sheetName: 'Headcount',
                    flatRows: buildHeadcountRows(partidas, headcountMap, cols, colYm),
                    columns: cols,
                    year: selectedYear,
                    numFmt: '#,##0',
                });
            }

            // Sheet 3: % de Ingresos
            const plSummaryRows = getMergedRows('pl_summary', 'PARTIDA_PL', 'pl');
            const revenueRow = plSummaryRows.find(r => r['PARTIDA_PL'] === 'INGRESOS ORDINARIOS');
            if (revenueRow) {
                sheets.push({
                    kind: 'planilla',
                    sheetName: '% de Ingresos',
                    flatRows: buildPctRows(partidas, revenueRow, cols),
                    columns: cols,
                    year: selectedYear,
                    numFmt: '0.0"%"',
                });
            }

            // Sheet 4: Gasto / HC (only if headcount available)
            if (headcountMap && Object.keys(headcountMap).length > 0) {
                sheets.push({
                    kind: 'planilla',
                    sheetName: 'Gasto x HC',
                    flatRows: buildPerWorkerRows(partidas, headcountMap, cols, colYm),
                    columns: cols,
                    year: selectedYear,
                });
            }
        } else if (currentView === 'analysis_pl_finanzas') {
            const rows = getMergedRows('pl_summary', 'PARTIDA_PL', 'pl');
            const cols = getDisplayColumns('pl');
            sheets.push({
                kind: 'planilla',
                sheetName: viewTitle,
                flatRows: buildFinanzasRows(rows, cols, getMergedDetailRows),
                columns: cols,
                year: selectedYear,
            });
        } else if (currentView === 'analysis_flujo_caja') {
            const cols = getDisplayColumns('pl');
            sheets.push({
                kind: 'planilla',
                sheetName: viewTitle,
                flatRows: buildFlujoCajaRows(cols, getMergedDetailRows),
                columns: cols,
                year: selectedYear,
            });
        } else if (currentView === 'analysis_proveedores') {
            const proveedoresKeys = ['NIT', 'RAZON_SOCIAL'];
            const proveedoresRows = getMergedDetailRows('proveedores_transporte', proveedoresKeys);
            const cols = getDisplayColumns('pl');
            const sheet: DetailSheetDef = {
                kind: 'detail',
                sheetName: viewTitle,
                rows: proveedoresRows,
                columns: cols,
                headerLabels: ['NIT', 'Proveedor'],
                labelKeys: proveedoresKeys,
                year: selectedYear,
            };
            sheets.push(sheet);
        } else {
            // Note views
            const noteConfig = VIEW_TABLE_CONFIGS[currentView as NoteView];
            if (noteConfig) {
                let tables = noteConfig.tables(reportData);

                // Apply trailing 12M merge if active
                if (periodRange === 'trailing12') {
                    tables = tables.map(t => {
                        const dataKey = getDataKeyForTable(t, reportData);
                        if (dataKey) {
                            return { ...t, rows: getMergedDetailRows(dataKey, t.labelKeys) };
                        }
                        return t;
                    });
                }

                // Filter out all-zero tables
                tables = tables.filter(t => !isAllZeroTable(t.rows, ALL_MONTHS));

                for (const t of tables) {
                    const sheet: DetailSheetDef = {
                        kind: 'detail',
                        sheetName: t.title,
                        rows: t.rows,
                        columns: getDisplayColumns('pl'),
                        headerLabels: t.headerLabels,
                        labelKeys: t.labelKeys,
                        year: selectedYear,
                    };
                    sheets.push(sheet);
                }
            }
        }

        if (sheets.length === 0) return;

        const safeName = viewTitle.replace(/\s+/g, '_');
        const filename = `${safeName}_${selectedCompany}_${selectedYear}.xlsx`;

        exportToExcel({ sheets, filename });
    }, [
        reportData, currentView, selectedCompany, selectedYear,
        getDisplayColumns, getMergedRows, getMergedDetailRows, periodRange,
        headcountMap, trailingMonthSources,
    ]);

    return { handleExport, canExport };
}
