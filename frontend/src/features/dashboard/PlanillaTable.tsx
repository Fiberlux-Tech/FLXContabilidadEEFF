import { useState, useMemo } from 'react';
import type { ReportRow, DisplayColumn, MonthSource, Month } from '@/types';
import { ALL_MONTHS } from '@/types';
import type { HeadcountMap } from '@/features/dashboard/useHeadcount';
import { formatNumber } from '@/utils/format';
import { getCellValue } from '@/utils/cellValue';
import { negClass } from '@/utils/classHelpers';

// ── Canonical P&L partida ordering ──────────────────────────────────

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

// ── Filter definitions ──────────────────────────────────────────────

type PlanillaFilter = 'all' | 'variable' | 'fija';

const VARIABLE_CUENTA = '62.1.2.1.01';

const FILTER_OPTIONS: { value: PlanillaFilter; label: string }[] = [
    { value: 'all', label: 'Todas' },
    { value: 'variable', label: 'Planilla Variable' },
    { value: 'fija', label: 'Planilla Fija' },
];

const TOTAL_LABELS: Record<PlanillaFilter, string> = {
    all: 'Total Planilla',
    variable: 'Total Planilla Variable',
    fija: 'Total Planilla Fija',
};

// ── Metric mode definitions ─────────────────────────────────────────

type MetricMode = 'solo_gasto' | 'headcount' | 'gasto_hc';

const METRIC_OPTIONS: { value: MetricMode; label: string }[] = [
    { value: 'solo_gasto', label: 'Solo Gasto' },
    { value: 'headcount', label: 'Headcount' },
    { value: 'gasto_hc', label: 'Gasto / HC' },
];

// ── Types ───────────────────────────────────────────────────────────

interface PlanillaCuenta {
    row: ReportRow;
}

interface PlanillaCeco {
    code: string;
    desc: string;
    totals: Record<string, number>;
    cuentas: PlanillaCuenta[];
}

interface PlanillaPartida {
    name: string;
    totals: Record<string, number>;
    cecos: PlanillaCeco[];
}

// ── Grouping logic ──────────────────────────────────────────────────

function buildHierarchy(rows: ReportRow[], columns: DisplayColumn[]): { partidas: PlanillaPartida[]; grandTotal: Record<string, number> } {
    const monthKeys = new Set<string>();
    for (const col of columns) {
        for (const m of col.sourceMonths) monthKeys.add(m);
    }

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

    const sumMonths = (rows: ReportRow[]): Record<string, number> => {
        const sums: Record<string, number> = {};
        for (const row of rows) {
            for (const m of monthKeys) {
                sums[m] = (sums[m] ?? 0) + ((row[m] as number) ?? 0);
            }
            sums['TOTAL'] = (sums['TOTAL'] ?? 0) + ((row['TOTAL'] as number) ?? 0);
        }
        return sums;
    };

    const partidas: PlanillaPartida[] = [];
    const grandTotalRows: ReportRow[] = [];

    for (const [partidaName, cecoMap] of partidaMap) {
        const cecos: PlanillaCeco[] = [];
        const allPartidaRows: ReportRow[] = [];

        for (const [cecoCode, { desc, rows: cecoRows }] of cecoMap) {
            cecos.push({
                code: cecoCode,
                desc,
                totals: sumMonths(cecoRows),
                cuentas: cecoRows.map(r => ({ row: r })),
            });
            allPartidaRows.push(...cecoRows);
        }

        cecos.sort((a, b) => a.code.localeCompare(b.code));

        partidas.push({
            name: partidaName,
            totals: sumMonths(allPartidaRows),
            cecos,
        });

        grandTotalRows.push(...allPartidaRows);
    }

    const fallback = PARTIDA_PL_ORDER.length;
    partidas.sort((a, b) =>
        (PARTIDA_ORDER_INDEX.get(a.name) ?? fallback) - (PARTIDA_ORDER_INDEX.get(b.name) ?? fallback)
    );

    return { partidas, grandTotal: sumMonths(grandTotalRows) };
}

// ── Small helpers ───────────────────────────────────────────────────

function formatEmpty(val: number | null | undefined): string {
    if (val === null || val === undefined) return '';
    if (val === 0) return '';
    return formatNumber(val);
}

// ── Percentage helpers ──────────────────────────────────────────────

function pctValue(costVal: number | null, revenueVal: number | null): number | null {
    if (costVal === null || costVal === undefined) return null;
    if (revenueVal === null || revenueVal === undefined || revenueVal === 0) return null;
    return (costVal / revenueVal) * 100;
}

function formatPercent(value: number | null | undefined): string {
    if (value === null || value === undefined) return '';
    if (value === 0) return '';
    return value.toFixed(1) + '%';
}

// ── Per-worker helpers ─────────────────────────────────────────────

function perWorkerValue(costVal: number | null, headcount: number | null | undefined): number | null {
    if (costVal === null || costVal === undefined) return null;
    if (!headcount || headcount <= 0) return null;
    return costVal / headcount;
}

function formatPerWorker(value: number | null | undefined): string {
    if (value === null || value === undefined) return '';
    if (value === 0) return '';
    return formatNumber(Math.round(value));
}

// ── year_month resolution (DB convention: 202501 = Jan 2025) ────────

const MONTH_TO_NUM: Record<Month, number> = Object.fromEntries(
    ALL_MONTHS.map((m, i) => [m, i + 1])
) as Record<Month, number>;

/**
 * Build a lookup from DisplayColumn → year_month string ("202501").
 * In trailing 12M mode, monthSources carries the year for each month.
 * In YTD mode (monthSources is null), all months belong to selectedYear.
 */
function buildColYm(
    columns: DisplayColumn[],
    selectedYear: number,
    monthSources: MonthSource[] | null,
): Map<DisplayColumn, string> {
    const map = new Map<DisplayColumn, string>();
    if (monthSources) {
        const srcMap = new Map<Month, string>();
        for (const s of monthSources) {
            srcMap.set(s.month, String(s.year * 100 + MONTH_TO_NUM[s.month]));
        }
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

/** Get the headcount for a CECO at the year_month corresponding to a column. */
function hcForCol(
    cecoData: Record<string, number> | undefined,
    col: DisplayColumn,
    colYm: Map<DisplayColumn, string>,
): number | null {
    if (!cecoData) return null;
    const ym = colYm.get(col);
    if (ym === undefined) return null;
    const hc = cecoData[ym];
    return hc != null && hc > 0 ? hc : null;
}

/** Average headcount across all year_months present in the column set. */
function hcAvg(
    cecoData: Record<string, number> | undefined,
    colYm: Map<DisplayColumn, string>,
): number | null {
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

// ── Headcount / per-worker aggregation ──────────────────────────────

function partidaHcPerCol(partida: PlanillaPartida, headcountMap: HeadcountMap, col: DisplayColumn, colYm: Map<DisplayColumn, string>): number | null {
    let total = 0;
    for (const ceco of partida.cecos) {
        const hc = hcForCol(headcountMap[ceco.code], col, colYm);
        if (hc && hc > 0) total += hc;
    }
    return total > 0 ? total : null;
}

function partidaHcAvg(partida: PlanillaPartida, headcountMap: HeadcountMap, colYm: Map<DisplayColumn, string>): number | null {
    let total = 0;
    for (const ceco of partida.cecos) {
        const avg = hcAvg(headcountMap[ceco.code], colYm);
        if (avg && avg > 0) total += avg;
    }
    return total > 0 ? Math.round(total) : null;
}

function partidaPwPerCol(partida: PlanillaPartida, headcountMap: HeadcountMap, col: DisplayColumn, colYm: Map<DisplayColumn, string>): number | null {
    let costSum = 0, hcSum = 0;
    for (const ceco of partida.cecos) {
        const hc = hcForCol(headcountMap[ceco.code], col, colYm);
        if (!hc || hc <= 0) continue;
        costSum += (ceco.totals[col.sourceMonths[0]] ?? 0);
        hcSum += hc;
    }
    return hcSum > 0 ? costSum / hcSum : null;
}

function partidaPwAvg(partida: PlanillaPartida, headcountMap: HeadcountMap, colYm: Map<DisplayColumn, string>): number | null {
    let costSum = 0, hcSum = 0;
    for (const ceco of partida.cecos) {
        const avg = hcAvg(headcountMap[ceco.code], colYm);
        if (!avg || avg <= 0) continue;
        costSum += (ceco.totals['TOTAL'] ?? 0);
        hcSum += avg;
    }
    return hcSum > 0 ? costSum / hcSum : null;
}

function grandHcPerCol(partidas: PlanillaPartida[], headcountMap: HeadcountMap, col: DisplayColumn, colYm: Map<DisplayColumn, string>): number | null {
    let total = 0;
    for (const p of partidas) {
        const v = partidaHcPerCol(p, headcountMap, col, colYm);
        if (v) total += v;
    }
    return total > 0 ? total : null;
}

function grandHcAvg(partidas: PlanillaPartida[], headcountMap: HeadcountMap, colYm: Map<DisplayColumn, string>): number | null {
    let total = 0;
    for (const p of partidas) {
        const v = partidaHcAvg(p, headcountMap, colYm);
        if (v) total += v;
    }
    return total > 0 ? total : null;
}

function grandPwPerCol(partidas: PlanillaPartida[], headcountMap: HeadcountMap, col: DisplayColumn, colYm: Map<DisplayColumn, string>): number | null {
    let costSum = 0, hcSum = 0;
    for (const p of partidas) {
        for (const ceco of p.cecos) {
            const hc = hcForCol(headcountMap[ceco.code], col, colYm);
            if (!hc || hc <= 0) continue;
            costSum += (ceco.totals[col.sourceMonths[0]] ?? 0);
            hcSum += hc;
        }
    }
    return hcSum > 0 ? costSum / hcSum : null;
}

function grandPwAvg(partidas: PlanillaPartida[], headcountMap: HeadcountMap, colYm: Map<DisplayColumn, string>): number | null {
    let costSum = 0, hcSum = 0;
    for (const p of partidas) {
        for (const ceco of p.cecos) {
            const avg = hcAvg(headcountMap[ceco.code], colYm);
            if (!avg || avg <= 0) continue;
            costSum += (ceco.totals['TOTAL'] ?? 0);
            hcSum += avg;
        }
    }
    return hcSum > 0 ? costSum / hcSum : null;
}

// ── Metric formatting ─────────────────────────────────────────────

function fmtHc(hc: number | null): string {
    return hc != null && hc > 0 ? String(Math.round(hc)) : '';
}

function fmtPw(pw: number | null): string {
    return pw !== null && pw !== 0 ? formatPerWorker(pw) : '';
}

// ── Cell renderers ──────────────────────────────────────────────────

/** Standard numeric cells (no metric sub-column). */
function NumCells({ row, columns, activeHeaders }: { row: Record<string, number> | ReportRow; columns: DisplayColumn[]; activeHeaders?: Set<string> }) {
    return (
        <>
            {columns.map(col => {
                if (activeHeaders && !activeHeaders.has(col.header)) {
                    return <td key={col.header} className="rpt-inactive">{'\u2014'}</td>;
                }
                const val = getCellValue(row as ReportRow, col);
                return (
                    <td key={col.header} className={negClass(val)}>
                        {formatEmpty(val)}
                    </td>
                );
            })}
        </>
    );
}

/** Amount + metric sub-column pair, per column. getMetric returns the formatted string for the metric td. */
function NumCellsDual({
    row, columns, activeHeaders, getMetric,
}: {
    row: Record<string, number> | ReportRow;
    columns: DisplayColumn[];
    activeHeaders?: Set<string>;
    getMetric: (col: DisplayColumn) => string;
}) {
    return (
        <>
            {columns.map(col => {
                if (activeHeaders && !activeHeaders.has(col.header)) {
                    return (
                        <Fragment key={col.header}>
                            <td className="rpt-inactive">{'\u2014'}</td>
                            <td className="rpt-col-metric"></td>
                        </Fragment>
                    );
                }
                const val = getCellValue(row as ReportRow, col);
                return (
                    <Fragment key={col.header}>
                        <td className={negClass(val)}>{formatEmpty(val)}</td>
                        <td className="rpt-col-metric">{getMetric(col)}</td>
                    </Fragment>
                );
            })}
        </>
    );
}

function TotalCell({ val }: { val: number | null }) {
    return <td className={`rpt-col-total-val ${negClass(val)}`}>{formatEmpty(val)}</td>;
}

function NumCellsPct({ row, revenueRow, columns, activeHeaders }: { row: Record<string, number> | ReportRow; revenueRow: ReportRow; columns: DisplayColumn[]; activeHeaders?: Set<string> }) {
    return (
        <>
            {columns.map(col => {
                if (activeHeaders && !activeHeaders.has(col.header)) {
                    return <td key={col.header}></td>;
                }
                const costVal = getCellValue(row as ReportRow, col);
                const revVal = getCellValue(revenueRow, col);
                const pct = pctValue(costVal, revVal);
                return (
                    <td key={col.header} className={pct !== null && pct < 0 ? 'rpt-neg' : ''}>
                        {formatPercent(pct)}
                    </td>
                );
            })}
        </>
    );
}

function TotalCellPct({ costVal, revenueVal }: { costVal: number | null; revenueVal: number | null }) {
    const pct = pctValue(costVal, revenueVal);
    return <td className={`rpt-col-total-val ${pct !== null && pct < 0 ? 'rpt-neg' : ''}`}>{formatPercent(pct)}</td>;
}

// ── Table headers ──────────────────────────────────────────────────

function TableHead({ columns }: { columns: DisplayColumn[] }) {
    return (
        <thead>
            <tr>
                <th className="rpt-sticky">Concepto</th>
                {columns.map(col => (
                    <th key={col.header}>{col.header}</th>
                ))}
                <th className="rpt-col-total rpt-col-total-val">Total</th>
            </tr>
        </thead>
    );
}

function TableHeadDual({ columns, metricLabel }: { columns: DisplayColumn[]; metricLabel: string }) {
    return (
        <thead>
            <tr>
                <th className="rpt-sticky">Concepto</th>
                {columns.map(col => (
                    <Fragment key={col.header}>
                        <th>{col.header}</th>
                        <th className="rpt-col-metric">{metricLabel}</th>
                    </Fragment>
                ))}
                <th className="rpt-col-total rpt-col-total-val">Total</th>
                <th className="rpt-col-metric">{metricLabel === 'HC' ? 'HC Prom' : metricLabel}</th>
            </tr>
        </thead>
    );
}

// ── Main component ──────────────────────────────────────────────────

interface PlanillaTableProps {
    rows: ReportRow[];
    columns: DisplayColumn[];
    revenueRow: ReportRow | null;
    headcountMap?: HeadcountMap | null;
    selectedYear: number;
    /** MonthSource[] for trailing 12M, null for YTD */
    monthSources: MonthSource[] | null;
}

export default function PlanillaTable({ rows, columns, revenueRow, headcountMap, selectedYear, monthSources }: PlanillaTableProps) {
    const [expandedPartidas, setExpandedPartidas] = useState<Set<string>>(new Set());
    const [expandedCecos, setExpandedCecos] = useState<Set<string>>(new Set());
    const [expandedPctPartidas, setExpandedPctPartidas] = useState<Set<string>>(new Set());
    const [expandedPctCecos, setExpandedPctCecos] = useState<Set<string>>(new Set());
    const [planillaFilter, setPlanillaFilter] = useState<PlanillaFilter>('all');
    const [metricMode, setMetricMode] = useState<MetricMode>('solo_gasto');

    const filteredRows = useMemo(() => {
        if (planillaFilter === 'all') return rows;
        if (planillaFilter === 'variable')
            return rows.filter(r => String(r['CUENTA_CONTABLE'] ?? '') === VARIABLE_CUENTA);
        return rows.filter(r => String(r['CUENTA_CONTABLE'] ?? '') !== VARIABLE_CUENTA);
    }, [rows, planillaFilter]);

    const { partidas, grandTotal } = useMemo(() => buildHierarchy(filteredRows, columns), [filteredRows, columns]);

    const colYm = useMemo(
        () => buildColYm(columns, selectedYear, monthSources),
        [columns, selectedYear, monthSources],
    );

    const activeHeaders = useMemo(() => {
        const s = new Set<string>();
        if (!revenueRow) return s;
        for (const col of columns) {
            const val = getCellValue(revenueRow, col);
            if (val !== null && val !== undefined && val !== 0) s.add(col.header);
        }
        return s;
    }, [revenueRow, columns]);

    const togglePartida = (name: string) => {
        setExpandedPartidas(prev => {
            const next = new Set(prev);
            if (next.has(name)) {
                next.delete(name);
                setExpandedCecos(prev2 => {
                    const next2 = new Set(prev2);
                    for (const key of next2) if (key.startsWith(name + '|')) next2.delete(key);
                    return next2;
                });
            } else {
                next.add(name);
            }
            return next;
        });
    };

    const toggleCeco = (partida: string, cecoCode: string) => {
        const key = `${partida}|${cecoCode}`;
        setExpandedCecos(prev => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

    const togglePctPartida = (name: string) => {
        setExpandedPctPartidas(prev => {
            const next = new Set(prev);
            if (next.has(name)) {
                next.delete(name);
                setExpandedPctCecos(prev2 => {
                    const next2 = new Set(prev2);
                    for (const key of next2) if (key.startsWith(name + '|')) next2.delete(key);
                    return next2;
                });
            } else {
                next.add(name);
            }
            return next;
        });
    };

    const togglePctCeco = (partida: string, cecoCode: string) => {
        const key = `${partida}|${cecoCode}`;
        setExpandedPctCecos(prev => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

    const hasHeadcount = headcountMap && Object.keys(headcountMap).length > 0;
    const isDual = metricMode !== 'solo_gasto' && hasHeadcount;
    const metricLabel = metricMode === 'headcount' ? 'HC' : 'S//HC';
    const colSpanAll = isDual ? columns.length * 2 + 3 : columns.length + 2;

    const revTotal = (revenueRow?.['TOTAL'] as number | null) ?? null;

    return (
        <div>
            {/* ── Filter Bar (TIPO + METRICA on one row) ── */}
            <nav className="flex items-center justify-between mb-10">
                <div className="flex items-center gap-3">
                    <span className="filter-label !mb-0">Tipo</span>
                    <div className="toggle-group">
                        {FILTER_OPTIONS.map(opt => (
                            <button
                                key={opt.value}
                                onClick={() => setPlanillaFilter(opt.value)}
                                className={`toggle-btn ${planillaFilter === opt.value ? 'toggle-active' : 'toggle-inactive'}`}
                            >
                                {opt.label}
                            </button>
                        ))}
                    </div>
                </div>
                {hasHeadcount && (
                    <div className="flex items-center gap-3">
                        <span className="filter-label !mb-0">Metrica</span>
                        <div className="toggle-group">
                            {METRIC_OPTIONS.map(opt => (
                                <button
                                    key={opt.value}
                                    onClick={() => setMetricMode(opt.value)}
                                    className={`toggle-btn ${metricMode === opt.value ? 'toggle-active' : 'toggle-inactive'}`}
                                >
                                    {opt.label}
                                </button>
                            ))}
                        </div>
                    </div>
                )}
            </nav>

            {/* ═══ TABLE 1: COSTS ═══ */}
            <div className="overflow-x-auto">
            <table className={isDual ? 'rpt-table-auto' : 'rpt-table'}>
                {isDual
                    ? <TableHeadDual columns={columns} metricLabel={metricLabel} />
                    : <TableHead columns={columns} />
                }
                <tbody>
                    {/* Revenue row */}
                    {revenueRow && (
                        <>
                            <tr className="rpt-row-highlight">
                                <td className="rpt-sticky">Ingresos Ordinarios</td>
                                {isDual ? (
                                    <>
                                        <NumCellsDual row={revenueRow} columns={columns} activeHeaders={activeHeaders} getMetric={() => ''} />
                                        <TotalCell val={revenueRow['TOTAL'] as number | null} />
                                        <td className="rpt-col-metric"></td>
                                    </>
                                ) : (
                                    <>
                                        <NumCells row={revenueRow} columns={columns} activeHeaders={activeHeaders} />
                                        <TotalCell val={revenueRow['TOTAL'] as number | null} />
                                    </>
                                )}
                            </tr>
                            <tr className="rpt-row-spacer"><td colSpan={colSpanAll}></td></tr>
                        </>
                    )}

                    {/* Cost partidas */}
                    {partidas.map((partida) => {
                        const isExpanded = expandedPartidas.has(partida.name);

                        const getPartidaMetric = (col: DisplayColumn): string => {
                            if (!headcountMap) return '';
                            if (metricMode === 'headcount') return fmtHc(partidaHcPerCol(partida, headcountMap, col, colYm));
                            return fmtPw(partidaPwPerCol(partida, headcountMap, col, colYm));
                        };

                        const partidaTotalMetric = (): string => {
                            if (!headcountMap) return '';
                            if (metricMode === 'headcount') return fmtHc(partidaHcAvg(partida, headcountMap, colYm));
                            return fmtPw(partidaPwAvg(partida, headcountMap, colYm));
                        };

                        return (
                            <Fragment key={partida.name}>
                                {/* L0: Partida */}
                                <tr className="rpt-row-l0" onClick={() => togglePartida(partida.name)}>
                                    <td className="rpt-sticky">
                                        <span className="rpt-chevron">{isExpanded ? '\u25BE' : '\u25B8'}</span>
                                        {partida.name}
                                    </td>
                                    {isDual ? (
                                        <>
                                            <NumCellsDual row={partida.totals as ReportRow} columns={columns} activeHeaders={activeHeaders} getMetric={getPartidaMetric} />
                                            <TotalCell val={partida.totals['TOTAL'] ?? null} />
                                            <td className="rpt-col-metric">{partidaTotalMetric()}</td>
                                        </>
                                    ) : (
                                        <>
                                            <NumCells row={partida.totals as ReportRow} columns={columns} activeHeaders={activeHeaders} />
                                            <TotalCell val={partida.totals['TOTAL'] ?? null} />
                                        </>
                                    )}
                                </tr>

                                {/* L1: CECOs */}
                                {isExpanded && partida.cecos.map((ceco) => {
                                    const cecoExpanded = expandedCecos.has(`${partida.name}|${ceco.code}`);
                                    const cecoHcData = headcountMap?.[ceco.code] ?? undefined;
                                    const cecoHcAvgVal = hcAvg(cecoHcData, colYm);

                                    const getCecoMetric = (col: DisplayColumn): string => {
                                        if (!cecoHcData) return '';
                                        const hc = hcForCol(cecoHcData, col, colYm);
                                        if (metricMode === 'headcount') return fmtHc(hc);
                                        const val = getCellValue(ceco.totals as ReportRow, col);
                                        return fmtPw(perWorkerValue(val, hc));
                                    };

                                    const cecoTotalMetric = (): string => {
                                        if (metricMode === 'headcount') return fmtHc(cecoHcAvgVal != null ? Math.round(cecoHcAvgVal) : null);
                                        return fmtPw(perWorkerValue(ceco.totals['TOTAL'] ?? null, cecoHcAvgVal));
                                    };

                                    return (
                                        <Fragment key={`${partida.name}|${ceco.code}`}>
                                            <tr
                                                className="rpt-row-l1"
                                                onClick={isDual ? () => toggleCeco(partida.name, ceco.code) : undefined}
                                                style={{ cursor: isDual ? 'pointer' : 'default' }}
                                            >
                                                <td className="rpt-sticky">
                                                    {isDual && <span className="rpt-chevron">{cecoExpanded ? '\u25BE' : '\u25B8'}</span>}
                                                    {ceco.code} {ceco.desc}
                                                </td>
                                                {isDual ? (
                                                    <>
                                                        <NumCellsDual row={ceco.totals as ReportRow} columns={columns} activeHeaders={activeHeaders} getMetric={getCecoMetric} />
                                                        <TotalCell val={ceco.totals['TOTAL'] ?? null} />
                                                        <td className="rpt-col-metric">{cecoTotalMetric()}</td>
                                                    </>
                                                ) : (
                                                    <>
                                                        <NumCells row={ceco.totals as ReportRow} columns={columns} activeHeaders={activeHeaders} />
                                                        <TotalCell val={ceco.totals['TOTAL'] ?? null} />
                                                    </>
                                                )}
                                            </tr>

                                            {/* L2: Cuentas (only in dual mode, inheriting CECO headcount) */}
                                            {isDual && cecoExpanded && ceco.cuentas.map((cuenta, ci) => {
                                                const getCuentaMetric = (col: DisplayColumn): string => {
                                                    if (!cecoHcData) return '';
                                                    const hc = hcForCol(cecoHcData, col, colYm);
                                                    if (metricMode === 'headcount') return fmtHc(hc);
                                                    const val = getCellValue(cuenta.row, col);
                                                    return fmtPw(perWorkerValue(val, hc));
                                                };

                                                const cuentaTotalMetric = (): string => {
                                                    if (metricMode === 'headcount') return fmtHc(cecoHcAvgVal != null ? Math.round(cecoHcAvgVal) : null);
                                                    return fmtPw(perWorkerValue(cuenta.row['TOTAL'] as number | null, cecoHcAvgVal));
                                                };

                                                return (
                                                    <tr key={ci} className="rpt-row-l2">
                                                        <td className="rpt-sticky">{cuenta.row['CUENTA_CONTABLE']} {cuenta.row['DESCRIPCION']}</td>
                                                        <NumCellsDual row={cuenta.row as unknown as Record<string, number>} columns={columns} activeHeaders={activeHeaders} getMetric={getCuentaMetric} />
                                                        <TotalCell val={cuenta.row['TOTAL'] as number | null} />
                                                        <td className="rpt-col-metric">{cuentaTotalMetric()}</td>
                                                    </tr>
                                                );
                                            })}
                                        </Fragment>
                                    );
                                })}
                            </Fragment>
                        );
                    })}

                    {/* Grand total */}
                    <tr className="rpt-row-total">
                        <td className="rpt-sticky">{TOTAL_LABELS[planillaFilter]}</td>
                        {isDual ? (
                            <>
                                <NumCellsDual
                                    row={grandTotal as ReportRow}
                                    columns={columns}
                                    activeHeaders={activeHeaders}
                                    getMetric={(col) => {
                                        if (!headcountMap) return '';
                                        if (metricMode === 'headcount') return fmtHc(grandHcPerCol(partidas, headcountMap, col, colYm));
                                        return fmtPw(grandPwPerCol(partidas, headcountMap, col, colYm));
                                    }}
                                />
                                <TotalCell val={grandTotal['TOTAL'] ?? null} />
                                <td className="rpt-col-metric" style={{ fontWeight: 700 }}>
                                    {headcountMap && (metricMode === 'headcount'
                                        ? fmtHc(grandHcAvg(partidas, headcountMap, colYm))
                                        : fmtPw(grandPwAvg(partidas, headcountMap, colYm))
                                    )}
                                </td>
                            </>
                        ) : (
                            <>
                                <NumCells row={grandTotal as ReportRow} columns={columns} activeHeaders={activeHeaders} />
                                <TotalCell val={grandTotal['TOTAL'] ?? null} />
                            </>
                        )}
                    </tr>
                </tbody>
            </table>
            </div>

            {/* ═══ TABLE 2: % DE INGRESOS (L0 → L1 → L2) ═══ */}
            {revenueRow && (
                <>
                    <div className="rpt-separator">
                        <div className="sep-line"></div>
                        <span className="sep-label">% de Ingresos</span>
                        <div className="sep-line"></div>
                    </div>

                    <div className="overflow-x-auto">
                    <table className="rpt-table">
                        <TableHead columns={columns} />
                        <tbody>
                            {partidas.map((partida) => {
                                const isPctExpanded = expandedPctPartidas.has(partida.name);

                                return (
                                    <Fragment key={partida.name}>
                                        <tr className="rpt-row-l0" onClick={() => togglePctPartida(partida.name)}>
                                            <td className="rpt-sticky">
                                                <span className="rpt-chevron">{isPctExpanded ? '\u25BE' : '\u25B8'}</span>
                                                {partida.name}
                                            </td>
                                            <NumCellsPct row={partida.totals as ReportRow} revenueRow={revenueRow} columns={columns} activeHeaders={activeHeaders} />
                                            <TotalCellPct costVal={partida.totals['TOTAL'] ?? null} revenueVal={revTotal} />
                                        </tr>

                                        {isPctExpanded && partida.cecos.map((ceco) => {
                                            const cecoKey = `${partida.name}|${ceco.code}`;
                                            const isCecoExpanded = expandedPctCecos.has(cecoKey);

                                            return (
                                                <Fragment key={cecoKey}>
                                                    <tr className="rpt-row-l1" onClick={() => togglePctCeco(partida.name, ceco.code)}>
                                                        <td className="rpt-sticky">
                                                            <span className="rpt-chevron">{isCecoExpanded ? '\u25BE' : '\u25B8'}</span>
                                                            {ceco.code} {ceco.desc}
                                                        </td>
                                                        <NumCellsPct row={ceco.totals as ReportRow} revenueRow={revenueRow} columns={columns} activeHeaders={activeHeaders} />
                                                        <TotalCellPct costVal={ceco.totals['TOTAL'] ?? null} revenueVal={revTotal} />
                                                    </tr>

                                                    {isCecoExpanded && ceco.cuentas.map((cuenta, ci) => (
                                                        <tr key={ci} className="rpt-row-l2">
                                                            <td className="rpt-sticky">
                                                                {cuenta.row['CUENTA_CONTABLE']} {cuenta.row['DESCRIPCION']}
                                                            </td>
                                                            <NumCellsPct row={cuenta.row} revenueRow={revenueRow} columns={columns} activeHeaders={activeHeaders} />
                                                            <TotalCellPct costVal={cuenta.row['TOTAL'] as number | null} revenueVal={revTotal} />
                                                        </tr>
                                                    ))}
                                                </Fragment>
                                            );
                                        })}
                                    </Fragment>
                                );
                            })}

                            <tr className="rpt-row-total">
                                <td className="rpt-sticky">{TOTAL_LABELS[planillaFilter]}</td>
                                <NumCellsPct row={grandTotal as ReportRow} revenueRow={revenueRow} columns={columns} activeHeaders={activeHeaders} />
                                <TotalCellPct costVal={grandTotal['TOTAL'] ?? null} revenueVal={revTotal} />
                            </tr>
                        </tbody>
                    </table>
                    </div>
                </>
            )}
        </div>
    );
}

// React Fragment alias
const Fragment = ({ children }: { children: React.ReactNode }) => <>{children}</>;
