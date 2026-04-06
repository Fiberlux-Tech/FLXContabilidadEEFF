import { useState, useMemo, useEffect, useCallback } from 'react';
import type { ReportRow, DisplayColumn, MonthSource, Month } from '@/types';
import { ALL_MONTHS } from '@/types';
import type { HeadcountMap } from '@/features/dashboard/useHeadcount';
import { formatNumber } from '@/utils/format';
import { getCellValue } from '@/utils/cellValue';
import { negClass } from '@/utils/classHelpers';
import { api } from '@/lib/api';
import { API_CONFIG } from '@/config';
import Modal from '@/components/Modal';

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


// ── Metric type definitions ─────────────────────────────────────────

type MetricType = 'gasto' | 'headcount' | 'salario';

const METRIC_OPTIONS: { value: MetricType; label: string }[] = [
    { value: 'gasto', label: 'Gasto' },
    { value: 'headcount', label: 'Headcount' },
    { value: 'salario', label: 'Salario Prom' },
];

const SECONDARY_NONE = 'none' as const;

const METRIC_LABEL: Record<MetricType, string> = {
    gasto: '$',
    headcount: 'HC',
    salario: 'S//HC',
};

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

function buildHierarchy(rows: ReportRow[], columns: DisplayColumn[]): { partidas: PlanillaPartida[] } {
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
    }

    const fallback = PARTIDA_PL_ORDER.length;
    partidas.sort((a, b) =>
        (PARTIDA_ORDER_INDEX.get(a.name) ?? fallback) - (PARTIDA_ORDER_INDEX.get(b.name) ?? fallback)
    );

    return { partidas };
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


// ── Metric formatting ─────────────────────────────────────────────

function fmtHc(hc: number | null): string {
    return hc != null && hc > 0 ? String(Math.round(hc)) : '';
}

function fmtPw(pw: number | null): string {
    return pw !== null && pw !== 0 ? formatPerWorker(pw) : '';
}

// ── Cell renderers ──────────────────────────────────────────────────

/** Standard numeric cells (no metric sub-column). getPrimary overrides the default row value. */
function NumCells({ row, columns, activeHeaders, getPrimary }: {
    row: Record<string, number> | ReportRow;
    columns: DisplayColumn[];
    activeHeaders?: Set<string>;
    getPrimary?: (col: DisplayColumn) => React.ReactNode;
}) {
    return (
        <>
            {columns.map(col => {
                if (activeHeaders && !activeHeaders.has(col.header)) {
                    return <td key={col.header} className="rpt-inactive">{'\u2014'}</td>;
                }
                if (getPrimary) {
                    return <td key={col.header}>{getPrimary(col)}</td>;
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

/** Amount + metric sub-column pair, per column. */
function NumCellsDual({
    row, columns, activeHeaders, getMetric, getPrimary,
}: {
    row: Record<string, number> | ReportRow;
    columns: DisplayColumn[];
    activeHeaders?: Set<string>;
    getMetric: (col: DisplayColumn) => React.ReactNode;
    getPrimary?: (col: DisplayColumn) => React.ReactNode;
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
                if (getPrimary) {
                    return (
                        <Fragment key={col.header}>
                            <td>{getPrimary(col)}</td>
                            <td className="rpt-col-metric">{getMetric(col)}</td>
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

function TableHeadDual({ columns, metricLabel, primaryLabel }: { columns: DisplayColumn[]; metricLabel: string; primaryLabel?: string }) {
    return (
        <thead>
            <tr>
                <th className="rpt-sticky">Concepto</th>
                {columns.map(col => (
                    <Fragment key={col.header}>
                        <th>{primaryLabel ? `${col.header}` : col.header}</th>
                        <th className="rpt-col-metric">{metricLabel}</th>
                    </Fragment>
                ))}
                <th className="rpt-col-total rpt-col-total-val">{primaryLabel ? primaryLabel : 'Total'}</th>
                <th className="rpt-col-metric">{metricLabel === 'HC' ? 'HC Prom' : metricLabel}</th>
            </tr>
        </thead>
    );
}

// ── Main component ──────────────────────────────────────────────────

interface RosterModalState {
    cecoCode: string;
    cecoDesc: string;
    yearMonth: string;
}

interface PlanillaTableProps {
    rows: ReportRow[];
    columns: DisplayColumn[];
    revenueRow: ReportRow | null;
    headcountMap?: HeadcountMap | null;
    selectedYear: number;
    /** MonthSource[] for trailing 12M, null for YTD */
    monthSources: MonthSource[] | null;
    company: string;
}

export default function PlanillaTable({ rows, columns, revenueRow, headcountMap, selectedYear, monthSources, company }: PlanillaTableProps) {
    const [expandedPartidas, setExpandedPartidas] = useState<Set<string>>(new Set());
    const [expandedCecos, setExpandedCecos] = useState<Set<string>>(new Set());
    const [expandedPctPartidas, setExpandedPctPartidas] = useState<Set<string>>(new Set());
    const [expandedPctCecos, setExpandedPctCecos] = useState<Set<string>>(new Set());
    const [planillaFilter, setPlanillaFilter] = useState<PlanillaFilter>('all');
    const [primaryMetric, setPrimaryMetric] = useState<MetricType>('gasto');
    const [secondaryMetric, setSecondaryMetric] = useState<MetricType | typeof SECONDARY_NONE>('none');
    const [rosterModal, setRosterModal] = useState<RosterModalState | null>(null);
    const [rosterEmployees, setRosterEmployees] = useState<{ empleado: string; nombre: string }[]>([]);
    const [rosterLoading, setRosterLoading] = useState(false);

    const openRoster = useCallback((cecoCode: string, cecoDesc: string, yearMonth: string) => {
        setRosterModal({ cecoCode, cecoDesc, yearMonth });
    }, []);

    useEffect(() => {
        if (!rosterModal) return;
        setRosterLoading(true);
        setRosterEmployees([]);
        const { cecoCode, yearMonth } = rosterModal;
        api.get<{ employees: { empleado: string; nombre: string }[] }>(
            `${API_CONFIG.ENDPOINTS.HEADCOUNT_ROSTER}?company=${encodeURIComponent(company)}&centro_costo=${encodeURIComponent(cecoCode)}&year_month=${yearMonth}`
        ).then(data => {
            setRosterEmployees(data.employees);
        }).catch(() => {
            setRosterEmployees([]);
        }).finally(() => {
            setRosterLoading(false);
        });
    }, [rosterModal, company]);

    const filteredRows = useMemo(() => {
        if (planillaFilter === 'all') return rows;
        if (planillaFilter === 'variable')
            return rows.filter(r => String(r['CUENTA_CONTABLE'] ?? '') === VARIABLE_CUENTA);
        return rows.filter(r => String(r['CUENTA_CONTABLE'] ?? '') !== VARIABLE_CUENTA);
    }, [rows, planillaFilter]);

    const { partidas } = useMemo(() => buildHierarchy(filteredRows, columns), [filteredRows, columns]);

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

    // If secondary requires HC data but it's unavailable, reset to none
    const effectiveSecondary = (secondaryMetric !== SECONDARY_NONE && !hasHeadcount && secondaryMetric !== 'gasto')
        ? SECONDARY_NONE : secondaryMetric;
    const isDual = effectiveSecondary !== SECONDARY_NONE;
    const metricLabel = isDual ? METRIC_LABEL[effectiveSecondary as MetricType] : '';
    const colSpanAll = isDual ? columns.length * 2 + 3 : columns.length + 2;

    // Primary metric requires HC data for headcount/salario — fall back to gasto
    const effectivePrimary = (!hasHeadcount && primaryMetric !== 'gasto') ? 'gasto' : primaryMetric;

    const revTotal = (revenueRow?.['TOTAL'] as number | null) ?? null;

    /** Render an HC value as a clickable link (CECO-level only, when we know the exact month). */
    const renderHcLink = (hc: number | null, cecoCode: string, cecoDesc: string, col: DisplayColumn): React.ReactNode => {
        const text = fmtHc(hc);
        if (!text) return '';
        const ym = colYm.get(col);
        if (!ym) return text;
        return (
            <span
                className="cursor-pointer underline decoration-dotted hover:text-accent transition-colors"
                onClick={(e) => { e.stopPropagation(); openRoster(cecoCode, cecoDesc, ym); }}
            >
                {text}
            </span>
        );
    };

    // ── Generic metric resolvers ──────────────────────────────────────
    // These produce cell content for any MetricType at partida / ceco / cuenta level.

    /** Resolve a metric value for a partida at a given column. */
    const resolvePartidaMetric = (metric: MetricType, partida: PlanillaPartida, col: DisplayColumn): React.ReactNode => {
        if (metric === 'gasto') {
            const val = getCellValue(partida.totals as ReportRow, col);
            return formatEmpty(val);
        }
        if (!headcountMap) return '';
        if (metric === 'headcount') return fmtHc(partidaHcPerCol(partida, headcountMap, col, colYm));
        // salario
        return fmtPw(partidaPwPerCol(partida, headcountMap, col, colYm));
    };

    /** Resolve total/avg metric for a partida. */
    const resolvePartidaTotal = (metric: MetricType, partida: PlanillaPartida): React.ReactNode => {
        if (metric === 'gasto') return formatEmpty(partida.totals['TOTAL'] ?? null);
        if (!headcountMap) return '';
        if (metric === 'headcount') return fmtHc(partidaHcAvg(partida, headcountMap, colYm));
        return fmtPw(partidaPwAvg(partida, headcountMap, colYm));
    };

    /** Resolve a metric value for a CECO at a given column. */
    const resolveCecoMetric = (metric: MetricType, ceco: PlanillaCeco, col: DisplayColumn): React.ReactNode => {
        const cecoHcData = headcountMap?.[ceco.code] ?? undefined;
        if (metric === 'gasto') {
            const val = getCellValue(ceco.totals as ReportRow, col);
            return formatEmpty(val);
        }
        if (!cecoHcData) return '';
        const hc = hcForCol(cecoHcData, col, colYm);
        if (metric === 'headcount') return renderHcLink(hc, ceco.code, ceco.desc, col);
        const val = getCellValue(ceco.totals as ReportRow, col);
        return fmtPw(perWorkerValue(val, hc));
    };

    /** Resolve total/avg metric for a CECO. */
    const resolveCecoTotal = (metric: MetricType, ceco: PlanillaCeco): React.ReactNode => {
        const cecoHcData = headcountMap?.[ceco.code] ?? undefined;
        const cecoHcAvgVal = hcAvg(cecoHcData, colYm);
        if (metric === 'gasto') return formatEmpty(ceco.totals['TOTAL'] ?? null);
        if (metric === 'headcount') return fmtHc(cecoHcAvgVal != null ? Math.round(cecoHcAvgVal) : null);
        return fmtPw(perWorkerValue(ceco.totals['TOTAL'] ?? null, cecoHcAvgVal));
    };

    /** Resolve a metric value for a cuenta row at a given column (inherits CECO headcount). */
    const resolveCuentaMetric = (metric: MetricType, cuenta: PlanillaCuenta, ceco: PlanillaCeco, col: DisplayColumn): React.ReactNode => {
        const cecoHcData = headcountMap?.[ceco.code] ?? undefined;
        if (metric === 'gasto') {
            const val = getCellValue(cuenta.row, col);
            return formatEmpty(val);
        }
        if (!cecoHcData) return '';
        const hc = hcForCol(cecoHcData, col, colYm);
        if (metric === 'headcount') return renderHcLink(hc, ceco.code, ceco.desc, col);
        const val = getCellValue(cuenta.row, col);
        return fmtPw(perWorkerValue(val, hc));
    };

    /** Resolve total/avg metric for a cuenta (inherits CECO headcount). */
    const resolveCuentaTotal = (metric: MetricType, cuenta: PlanillaCuenta, ceco: PlanillaCeco): React.ReactNode => {
        const cecoHcData = headcountMap?.[ceco.code] ?? undefined;
        const cecoHcAvgVal = hcAvg(cecoHcData, colYm);
        if (metric === 'gasto') return formatEmpty(cuenta.row['TOTAL'] as number | null);
        if (metric === 'headcount') return fmtHc(cecoHcAvgVal != null ? Math.round(cecoHcAvgVal) : null);
        return fmtPw(perWorkerValue(cuenta.row['TOTAL'] as number | null, cecoHcAvgVal));
    };

    // Whether the primary metric is the default (gasto from row data) or needs a custom getter
    const needsPrimaryGetter = effectivePrimary !== 'gasto';

    /** Format a year_month like "202501" to "Ene 2025". */
    const fmtYm = (ym: string): string => {
        const y = ym.slice(0, 4);
        const m = parseInt(ym.slice(4), 10);
        const names = ['Ene','Feb','Mar','Abr','May','Jun','Jul','Ago','Sep','Oct','Nov','Dic'];
        return `${names[m - 1] ?? ''} ${y}`;
    };

    return (
        <div>
            {/* ── Filter Bar ── */}
            <nav className="flex items-center justify-between mb-10">
                <div className="flex items-center gap-3">
                    <span className="filter-label !mb-0">Tipo</span>
                    <select
                        value={planillaFilter}
                        onChange={e => setPlanillaFilter(e.target.value as PlanillaFilter)}
                        className="select-base"
                    >
                        {FILTER_OPTIONS.map(opt => (
                            <option key={opt.value} value={opt.value}>{opt.label}</option>
                        ))}
                    </select>
                </div>
                <div className="flex items-center gap-4">
                    <div className="flex items-center gap-2">
                        <span className="filter-label !mb-0">Principal</span>
                        <select
                            value={effectivePrimary}
                            onChange={e => {
                                const v = e.target.value as MetricType;
                                setPrimaryMetric(v);
                                if (secondaryMetric === v) setSecondaryMetric(SECONDARY_NONE);
                            }}
                            className="select-base"
                        >
                            {METRIC_OPTIONS.map(opt => (
                                <option key={opt.value} value={opt.value}
                                    disabled={!hasHeadcount && opt.value !== 'gasto'}
                                >{opt.label}</option>
                            ))}
                        </select>
                    </div>
                    <div className="flex items-center gap-2">
                        <span className="filter-label !mb-0">Secundario</span>
                        <select
                            value={effectiveSecondary}
                            onChange={e => setSecondaryMetric(e.target.value as MetricType | typeof SECONDARY_NONE)}
                            className="select-base"
                        >
                            <option value="none">Ninguno</option>
                            {METRIC_OPTIONS.filter(opt => opt.value !== effectivePrimary).map(opt => (
                                <option key={opt.value} value={opt.value}
                                    disabled={!hasHeadcount && opt.value !== 'gasto'}
                                >{opt.label}</option>
                            ))}
                        </select>
                    </div>
                </div>
            </nav>

            {/* ═══ TABLE 1: COSTS ═══ */}
            <div className="overflow-x-auto">
            <table className={isDual ? 'rpt-table-auto' : 'rpt-table'}>
                {isDual
                    ? <TableHeadDual columns={columns} metricLabel={metricLabel} primaryLabel={needsPrimaryGetter ? METRIC_LABEL[effectivePrimary] : undefined} />
                    : <TableHead columns={columns} />
                }
                <tbody>
                    {/* Revenue row — always shows gasto regardless of primary metric */}
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

                        const primaryGetter = needsPrimaryGetter
                            ? (col: DisplayColumn) => resolvePartidaMetric(effectivePrimary, partida, col)
                            : undefined;

                        const secondaryGetter = isDual
                            ? (col: DisplayColumn) => resolvePartidaMetric(effectiveSecondary as MetricType, partida, col)
                            : undefined;

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
                                            <NumCellsDual row={partida.totals as ReportRow} columns={columns} activeHeaders={activeHeaders} getMetric={secondaryGetter!} getPrimary={primaryGetter} />
                                            <td className={`rpt-col-total-val`}>{resolvePartidaTotal(effectivePrimary, partida)}</td>
                                            <td className="rpt-col-metric">{resolvePartidaTotal(effectiveSecondary as MetricType, partida)}</td>
                                        </>
                                    ) : (
                                        <>
                                            <NumCells row={partida.totals as ReportRow} columns={columns} activeHeaders={activeHeaders} getPrimary={primaryGetter} />
                                            <td className={`rpt-col-total-val`}>{resolvePartidaTotal(effectivePrimary, partida)}</td>
                                        </>
                                    )}
                                </tr>

                                {/* L1: CECOs */}
                                {isExpanded && partida.cecos.map((ceco) => {
                                    const cecoExpanded = expandedCecos.has(`${partida.name}|${ceco.code}`);

                                    const cecoPrimaryGetter = needsPrimaryGetter
                                        ? (col: DisplayColumn) => resolveCecoMetric(effectivePrimary, ceco, col)
                                        : undefined;

                                    const cecoSecondaryGetter = isDual
                                        ? (col: DisplayColumn) => resolveCecoMetric(effectiveSecondary as MetricType, ceco, col)
                                        : undefined;

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
                                                        <NumCellsDual row={ceco.totals as ReportRow} columns={columns} activeHeaders={activeHeaders} getMetric={cecoSecondaryGetter!} getPrimary={cecoPrimaryGetter} />
                                                        <td className={`rpt-col-total-val`}>{resolveCecoTotal(effectivePrimary, ceco)}</td>
                                                        <td className="rpt-col-metric">{resolveCecoTotal(effectiveSecondary as MetricType, ceco)}</td>
                                                    </>
                                                ) : (
                                                    <>
                                                        <NumCells row={ceco.totals as ReportRow} columns={columns} activeHeaders={activeHeaders} getPrimary={cecoPrimaryGetter} />
                                                        <td className={`rpt-col-total-val`}>{resolveCecoTotal(effectivePrimary, ceco)}</td>
                                                    </>
                                                )}
                                            </tr>

                                            {/* L2: Cuentas (only in dual mode, inheriting CECO headcount) */}
                                            {isDual && cecoExpanded && ceco.cuentas.map((cuenta, ci) => {
                                                const cuentaPrimaryGetter = needsPrimaryGetter
                                                    ? (col: DisplayColumn) => resolveCuentaMetric(effectivePrimary, cuenta, ceco, col)
                                                    : undefined;

                                                return (
                                                    <tr key={ci} className="rpt-row-l2">
                                                        <td className="rpt-sticky">{cuenta.row['CUENTA_CONTABLE']} {cuenta.row['DESCRIPCION']}</td>
                                                        <NumCellsDual
                                                            row={cuenta.row as unknown as Record<string, number>}
                                                            columns={columns}
                                                            activeHeaders={activeHeaders}
                                                            getMetric={(col) => resolveCuentaMetric(effectiveSecondary as MetricType, cuenta, ceco, col)}
                                                            getPrimary={cuentaPrimaryGetter}
                                                        />
                                                        <td className={`rpt-col-total-val`}>{resolveCuentaTotal(effectivePrimary, cuenta, ceco)}</td>
                                                        <td className="rpt-col-metric">{resolveCuentaTotal(effectiveSecondary as MetricType, cuenta, ceco)}</td>
                                                    </tr>
                                                );
                                            })}
                                        </Fragment>
                                    );
                                })}
                            </Fragment>
                        );
                    })}

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

                        </tbody>
                    </table>
                    </div>
                </>
            )}

            {/* ═══ ROSTER MODAL ═══ */}
            <Modal
                isOpen={rosterModal !== null}
                onClose={() => setRosterModal(null)}
                title={rosterModal ? `${rosterModal.cecoCode} ${rosterModal.cecoDesc} — ${fmtYm(rosterModal.yearMonth)}` : ''}
            >
                {rosterLoading ? (
                    <p className="text-txt-muted text-sm py-4 text-center">Cargando...</p>
                ) : rosterEmployees.length === 0 ? (
                    <p className="text-txt-muted text-sm py-4 text-center">Sin registros</p>
                ) : (
                    <table className="w-full text-sm">
                        <thead>
                            <tr className="border-b border-border-light text-left text-txt-muted">
                                <th className="py-1.5 pr-4">#</th>
                                <th className="py-1.5 pr-4">Codigo</th>
                                <th className="py-1.5">Nombre</th>
                            </tr>
                        </thead>
                        <tbody>
                            {rosterEmployees.map((emp, i) => (
                                <tr key={emp.empleado} className="border-b border-border-light/50">
                                    <td className="py-1.5 pr-4 text-txt-muted">{i + 1}</td>
                                    <td className="py-1.5 pr-4 font-mono text-xs">{emp.empleado}</td>
                                    <td className="py-1.5">{emp.nombre}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                )}
            </Modal>
        </div>
    );
}

// React Fragment alias
const Fragment = ({ children }: { children: React.ReactNode }) => <>{children}</>;
