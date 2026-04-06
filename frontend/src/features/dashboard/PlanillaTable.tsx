import { useState, useMemo } from 'react';
import type { ReportRow, DisplayColumn } from '@/types';
import type { HeadcountMap } from '@/features/dashboard/useHeadcount';
import { formatNumber } from '@/utils/format';
import { getCellValue } from '@/utils/cellValue';
import { negClass } from '@/utils/classHelpers';

// ── Canonical P&L partida ordering ──────────────────────────────────

const PARTIDA_PL_ORDER = [
    'INGRESOS ORDINARIOS', 'INGRESOS PROYECTOS', 'INGRESOS INTERCOMPANY',
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
    return formatNumber(value);
}

// ── Headcount aggregation helpers ──────────────────────────────────

/** Sum headcounts across CECOs for a partida, per month. */
function partidaHeadcountCells({
    partida, headcountMap, columns,
}: {
    partida: PlanillaPartida;
    headcountMap: HeadcountMap;
    columns: DisplayColumn[];
}) {
    const cells = columns.map(col => {
        let totalHc = 0;
        for (const ceco of partida.cecos) {
            const cecoHc = headcountMap[ceco.code];
            if (!cecoHc) continue;
            const hc = cecoHc[col.sourceMonths[0]];
            if (hc && hc > 0) totalHc += hc;
        }
        return { key: col.header, hc: totalHc > 0 ? totalHc : null };
    });

    let totalHc = 0;
    for (const ceco of partida.cecos) {
        const cecoHc = headcountMap[ceco.code];
        if (!cecoHc?.['TOTAL_AVG'] || cecoHc['TOTAL_AVG'] <= 0) continue;
        totalHc += cecoHc['TOTAL_AVG'];
    }
    return { cells, totalHc: totalHc > 0 ? Math.round(totalHc) : null };
}

/** Sum headcounts across all CECOs in all partidas, per month. */
function grandTotalHeadcount({
    partidas, headcountMap, columns,
}: {
    partidas: PlanillaPartida[];
    headcountMap: HeadcountMap;
    columns: DisplayColumn[];
}) {
    const cells = columns.map(col => {
        let totalHc = 0;
        for (const p of partidas) {
            for (const ceco of p.cecos) {
                const cecoHc = headcountMap[ceco.code];
                if (!cecoHc) continue;
                const hc = cecoHc[col.sourceMonths[0]];
                if (hc && hc > 0) totalHc += hc;
            }
        }
        return { key: col.header, hc: totalHc > 0 ? totalHc : null };
    });

    let totalHc = 0;
    for (const p of partidas) {
        for (const ceco of p.cecos) {
            const cecoHc = headcountMap[ceco.code];
            if (!cecoHc?.['TOTAL_AVG'] || cecoHc['TOTAL_AVG'] <= 0) continue;
            totalHc += cecoHc['TOTAL_AVG'];
        }
    }
    return { cells, totalHc: totalHc > 0 ? Math.round(totalHc) : null };
}

/** Compute weighted per-worker values for a partida (sum costs / sum headcounts). */
function partidaPerWorkerCells({
    partida, headcountMap, columns,
}: {
    partida: PlanillaPartida;
    headcountMap: HeadcountMap;
    columns: DisplayColumn[];
}) {
    const cells = columns.map(col => {
        let totalCost = 0;
        let totalHc = 0;
        for (const ceco of partida.cecos) {
            const cecoHc = headcountMap[ceco.code];
            if (!cecoHc) continue;
            const hc = cecoHc[col.sourceMonths[0]];
            if (!hc || hc <= 0) continue;
            totalCost += (ceco.totals[col.sourceMonths[0]] ?? 0);
            totalHc += hc;
        }
        const pw = totalHc > 0 ? totalCost / totalHc : null;
        return { key: col.header, pw };
    });

    let totalCost = 0;
    let totalHc = 0;
    for (const ceco of partida.cecos) {
        const cecoHc = headcountMap[ceco.code];
        if (!cecoHc?.['TOTAL_AVG'] || cecoHc['TOTAL_AVG'] <= 0) continue;
        totalCost += (ceco.totals['TOTAL'] ?? 0);
        totalHc += cecoHc['TOTAL_AVG'];
    }
    const totalPw = totalHc > 0 ? totalCost / totalHc : null;

    return { cells, totalPw };
}

/** Compute grand-total per-worker (weighted across all CECOs with headcount). */
function grandTotalPerWorker({
    partidas, headcountMap, columns,
}: {
    partidas: PlanillaPartida[];
    headcountMap: HeadcountMap;
    columns: DisplayColumn[];
}) {
    const cells = columns.map(col => {
        let totalCost = 0;
        let totalHc = 0;
        for (const p of partidas) {
            for (const ceco of p.cecos) {
                const cecoHc = headcountMap[ceco.code];
                if (!cecoHc) continue;
                const hc = cecoHc[col.sourceMonths[0]];
                if (!hc || hc <= 0) continue;
                totalCost += (ceco.totals[col.sourceMonths[0]] ?? 0);
                totalHc += hc;
            }
        }
        return { key: col.header, pw: totalHc > 0 ? totalCost / totalHc : null };
    });

    let totalCost = 0;
    let totalHc = 0;
    for (const p of partidas) {
        for (const ceco of p.cecos) {
            const cecoHc = headcountMap[ceco.code];
            if (!cecoHc?.['TOTAL_AVG'] || cecoHc['TOTAL_AVG'] <= 0) continue;
            totalCost += (ceco.totals['TOTAL'] ?? 0);
            totalHc += cecoHc['TOTAL_AVG'];
        }
    }
    return { cells, totalPw: totalHc > 0 ? totalCost / totalHc : null };
}

// ── Cell renderers ──────────────────────────────────────────────────

function NumCells({ row, columns }: { row: Record<string, number> | ReportRow; columns: DisplayColumn[] }) {
    return (
        <>
            {columns.map(col => {
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

function TotalCell({ val }: { val: number | null }) {
    return <td className={negClass(val)}>{formatEmpty(val)}</td>;
}

function NumCellsPct({ row, revenueRow, columns }: { row: Record<string, number> | ReportRow; revenueRow: ReportRow; columns: DisplayColumn[] }) {
    return (
        <>
            {columns.map(col => {
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
    return <td className={pct !== null && pct < 0 ? 'rpt-neg' : ''}>{formatPercent(pct)}</td>;
}

// ── Dual-column cell renderers (amount + metric) ────────────────────

/** Revenue / empty metric: amount + em-dash in metric column */
function NumCellsWithEmptyMetric({ row, columns }: { row: Record<string, number> | ReportRow; columns: DisplayColumn[] }) {
    return (
        <>
            {columns.map(col => {
                const val = getCellValue(row as ReportRow, col);
                return (
                    <Fragment key={col.header}>
                        <td className={negClass(val)}>{formatEmpty(val)}</td>
                        <td className="rpt-col-metric">{'\u2014'}</td>
                    </Fragment>
                );
            })}
        </>
    );
}

/** CECO-level: amount + HC or amount + Gasto/HC */
function NumCellsCecoMetric({
    row, cecoCode, headcountMap, columns, mode,
}: {
    row: Record<string, number>;
    cecoCode: string;
    headcountMap: HeadcountMap;
    columns: DisplayColumn[];
    mode: 'headcount' | 'gasto_hc';
}) {
    const cecoHc = headcountMap[cecoCode] ?? null;
    return (
        <>
            {columns.map(col => {
                const val = getCellValue(row as ReportRow, col);
                const hc = cecoHc ? cecoHc[col.sourceMonths[0]] ?? null : null;
                if (mode === 'headcount') {
                    return (
                        <Fragment key={col.header}>
                            <td className={negClass(val)}>{formatEmpty(val)}</td>
                            <td className="rpt-col-metric">{hc != null && hc > 0 ? hc : '\u2014'}</td>
                        </Fragment>
                    );
                }
                const pw = perWorkerValue(val, hc);
                return (
                    <Fragment key={col.header}>
                        <td className={negClass(val)}>{formatEmpty(val)}</td>
                        <td className={`rpt-col-metric ${negClass(pw)}`}>
                            {pw !== null ? formatPerWorker(pw) : '\u2014'}
                        </td>
                    </Fragment>
                );
            })}
        </>
    );
}

// ── Table headers ──────────────────────────────────────────────────

function TableHead({ columns }: { columns: DisplayColumn[] }) {
    return (
        <thead>
            <tr>
                <th>Concepto</th>
                {columns.map(col => (
                    <th key={col.header}>{col.header}</th>
                ))}
                <th className="rpt-col-total">Total</th>
            </tr>
        </thead>
    );
}

function TableHeadWithMetric({ columns, metricLabel }: { columns: DisplayColumn[]; metricLabel: string }) {
    return (
        <thead>
            <tr>
                <th rowSpan={2} style={{ verticalAlign: 'bottom' }}>Concepto</th>
                {columns.map(col => (
                    <th key={col.header} colSpan={2} style={{ textAlign: 'center', borderBottom: '1px solid #ddd' }}>
                        {col.header}
                    </th>
                ))}
                <th colSpan={2} className="rpt-col-total" style={{ textAlign: 'center', borderBottom: '1px solid #ddd' }}>
                    Total
                </th>
            </tr>
            <tr>
                {columns.map(col => (
                    <Fragment key={col.header}>
                        <th style={{ fontSize: '9px' }}>S/</th>
                        <th className="rpt-col-metric" style={{ fontSize: '9px' }}>{metricLabel}</th>
                    </Fragment>
                ))}
                <th className="rpt-col-total" style={{ fontSize: '9px' }}>S/</th>
                <th className="rpt-col-total rpt-col-metric" style={{ fontSize: '9px' }}>{metricLabel === 'HC' ? 'Prom' : metricLabel}</th>
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
}

export default function PlanillaTable({ rows, columns, revenueRow, headcountMap }: PlanillaTableProps) {
    const [expandedPartidas, setExpandedPartidas] = useState<Set<string>>(new Set());
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

    const togglePartida = (name: string) => {
        setExpandedPartidas(prev => {
            const next = new Set(prev);
            if (next.has(name)) next.delete(name);
            else next.add(name);
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
            {/* ── Filter Tabs ── */}
            <nav className="flex items-baseline gap-10 mb-6">
                <span className="text-[11px] font-semibold uppercase text-txt-muted" style={{ letterSpacing: '1.2px' }}>
                    Tipo
                </span>
                <div className="flex gap-8">
                    {FILTER_OPTIONS.map(opt => (
                        <button
                            key={opt.value}
                            onClick={() => setPlanillaFilter(opt.value)}
                            className={`text-[13px] bg-transparent border-none cursor-pointer pb-1.5 transition-all
                                ${planillaFilter === opt.value
                                    ? 'text-txt font-semibold border-b-[3px] border-b-txt'
                                    : 'text-txt-muted font-normal border-b-2 border-b-transparent hover:text-txt-secondary'
                                }`}
                            style={{ letterSpacing: '0.2px' }}
                        >
                            {opt.label}
                        </button>
                    ))}
                </div>
            </nav>

            {/* ── Metric Toggle ── */}
            {hasHeadcount && (
                <nav className="flex items-center gap-3 mb-10">
                    <span className="text-[11px] font-semibold uppercase text-txt-muted mr-1" style={{ letterSpacing: '1.2px' }}>
                        Metrica
                    </span>
                    <div className="inline-flex rounded-md overflow-hidden" style={{ border: '1px solid #cbd5e1' }}>
                        {METRIC_OPTIONS.map(opt => (
                            <button
                                key={opt.value}
                                onClick={() => setMetricMode(opt.value)}
                                className={`px-3 py-1.5 text-[11px] font-medium transition-all whitespace-nowrap border-none cursor-pointer
                                    ${metricMode === opt.value
                                        ? 'text-white'
                                        : 'bg-white hover:bg-blue-50'
                                    }`}
                                style={metricMode === opt.value
                                    ? { background: '#2563EB', color: '#fff' }
                                    : { color: '#64748b' }
                                }
                            >
                                {opt.label}
                            </button>
                        ))}
                    </div>
                </nav>
            )}

            {/* ═══ TABLE 1: COSTS (L0 → L1 only, with optional metric sub-column) ═══ */}
            <table className={isDual ? 'rpt-table-auto' : 'rpt-table'}>
                {isDual
                    ? <TableHeadWithMetric columns={columns} metricLabel={metricLabel} />
                    : <TableHead columns={columns} />
                }
                <tbody>
                    {/* Revenue row */}
                    {revenueRow && (
                        <>
                            <tr className="rpt-row-highlight">
                                <td>Ingresos Ordinarios</td>
                                {isDual ? (
                                    <>
                                        <NumCellsWithEmptyMetric row={revenueRow} columns={columns} />
                                        <TotalCell val={revenueRow['TOTAL'] as number | null} />
                                        <td className="rpt-col-metric">{'\u2014'}</td>
                                    </>
                                ) : (
                                    <>
                                        <NumCells row={revenueRow} columns={columns} />
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

                        return (
                            <Fragment key={partida.name}>
                                {/* L0: Partida */}
                                <tr className="rpt-row-l0" onClick={() => togglePartida(partida.name)}>
                                    <td>
                                        <span className="rpt-chevron">{isExpanded ? '\u25BE' : '\u25B8'}</span>
                                        {partida.name}
                                    </td>
                                    {isDual ? (
                                        <>
                                            {metricMode === 'headcount' ? (() => {
                                                const { cells: hcCells, totalHc } = partidaHeadcountCells({ partida, headcountMap: headcountMap!, columns });
                                                return (
                                                    <>
                                                        {hcCells.map((c, i) => {
                                                            const val = getCellValue(partida.totals as ReportRow, columns[i]);
                                                            return (
                                                                <Fragment key={c.key}>
                                                                    <td className={negClass(val)}>{formatEmpty(val)}</td>
                                                                    <td className="rpt-col-metric">{c.hc ?? '\u2014'}</td>
                                                                </Fragment>
                                                            );
                                                        })}
                                                        <TotalCell val={partida.totals['TOTAL'] ?? null} />
                                                        <td className="rpt-col-metric">{totalHc ?? '\u2014'}</td>
                                                    </>
                                                );
                                            })() : (() => {
                                                const { cells: pwCells, totalPw } = partidaPerWorkerCells({ partida, headcountMap: headcountMap!, columns });
                                                return (
                                                    <>
                                                        {pwCells.map((c, i) => {
                                                            const val = getCellValue(partida.totals as ReportRow, columns[i]);
                                                            return (
                                                                <Fragment key={c.key}>
                                                                    <td className={negClass(val)}>{formatEmpty(val)}</td>
                                                                    <td className={`rpt-col-metric ${negClass(c.pw)}`}>
                                                                        {c.pw !== null ? formatPerWorker(c.pw) : '\u2014'}
                                                                    </td>
                                                                </Fragment>
                                                            );
                                                        })}
                                                        <TotalCell val={partida.totals['TOTAL'] ?? null} />
                                                        <td className={`rpt-col-metric ${negClass(totalPw)}`}>
                                                            {totalPw !== null ? formatPerWorker(totalPw) : '\u2014'}
                                                        </td>
                                                    </>
                                                );
                                            })()}
                                        </>
                                    ) : (
                                        <>
                                            <NumCells row={partida.totals as ReportRow} columns={columns} />
                                            <TotalCell val={partida.totals['TOTAL'] ?? null} />
                                        </>
                                    )}
                                </tr>

                                {/* L1: CECOs (non-expandable leaf in this table) */}
                                {isExpanded && partida.cecos.map((ceco) => (
                                    <tr key={`${partida.name}|${ceco.code}`} className="rpt-row-l1">
                                        <td style={{ cursor: 'default' }}>
                                            {ceco.code} {ceco.desc}
                                        </td>
                                        {isDual ? (
                                            <>
                                                <NumCellsCecoMetric
                                                    row={ceco.totals}
                                                    cecoCode={ceco.code}
                                                    headcountMap={headcountMap!}
                                                    columns={columns}
                                                    mode={metricMode as 'headcount' | 'gasto_hc'}
                                                />
                                                {metricMode === 'headcount' ? (
                                                    <>
                                                        <TotalCell val={ceco.totals['TOTAL'] ?? null} />
                                                        <td className="rpt-col-metric">
                                                            {headcountMap![ceco.code]?.['TOTAL_AVG'] != null
                                                                ? Math.round(headcountMap![ceco.code]['TOTAL_AVG'])
                                                                : '\u2014'}
                                                        </td>
                                                    </>
                                                ) : (
                                                    <>
                                                        <TotalCell val={ceco.totals['TOTAL'] ?? null} />
                                                        {(() => {
                                                            const pw = perWorkerValue(
                                                                ceco.totals['TOTAL'] ?? null,
                                                                headcountMap![ceco.code]?.['TOTAL_AVG'] ?? null,
                                                            );
                                                            return (
                                                                <td className={`rpt-col-metric ${negClass(pw)}`}>
                                                                    {pw !== null ? formatPerWorker(pw) : '\u2014'}
                                                                </td>
                                                            );
                                                        })()}
                                                    </>
                                                )}
                                            </>
                                        ) : (
                                            <>
                                                <NumCells row={ceco.totals as ReportRow} columns={columns} />
                                                <TotalCell val={ceco.totals['TOTAL'] ?? null} />
                                            </>
                                        )}
                                    </tr>
                                ))}
                            </Fragment>
                        );
                    })}

                    {/* Grand total */}
                    <tr className="rpt-row-total">
                        <td>{TOTAL_LABELS[planillaFilter]}</td>
                        {isDual ? (
                            <>
                                {metricMode === 'headcount' ? (() => {
                                    const { cells: hcCells, totalHc } = grandTotalHeadcount({ partidas, headcountMap: headcountMap!, columns });
                                    return (
                                        <>
                                            {hcCells.map((c, i) => {
                                                const val = getCellValue(grandTotal as ReportRow, columns[i]);
                                                return (
                                                    <Fragment key={c.key}>
                                                        <td className={negClass(val)}>{formatEmpty(val)}</td>
                                                        <td className="rpt-col-metric" style={{ fontWeight: 700 }}>{c.hc ?? '\u2014'}</td>
                                                    </Fragment>
                                                );
                                            })}
                                            <TotalCell val={grandTotal['TOTAL'] ?? null} />
                                            <td className="rpt-col-metric" style={{ fontWeight: 700 }}>{totalHc ?? '\u2014'}</td>
                                        </>
                                    );
                                })() : (() => {
                                    const { cells: pwCells, totalPw } = grandTotalPerWorker({ partidas, headcountMap: headcountMap!, columns });
                                    return (
                                        <>
                                            {pwCells.map((c, i) => {
                                                const val = getCellValue(grandTotal as ReportRow, columns[i]);
                                                return (
                                                    <Fragment key={c.key}>
                                                        <td className={negClass(val)}>{formatEmpty(val)}</td>
                                                        <td className={`rpt-col-metric ${negClass(c.pw)}`} style={{ fontWeight: 700 }}>
                                                            {c.pw !== null ? formatPerWorker(c.pw) : '\u2014'}
                                                        </td>
                                                    </Fragment>
                                                );
                                            })}
                                            <TotalCell val={grandTotal['TOTAL'] ?? null} />
                                            <td className={`rpt-col-metric ${negClass(totalPw)}`} style={{ fontWeight: 700 }}>
                                                {totalPw !== null ? formatPerWorker(totalPw) : '\u2014'}
                                            </td>
                                        </>
                                    );
                                })()}
                            </>
                        ) : (
                            <>
                                <NumCells row={grandTotal as ReportRow} columns={columns} />
                                <TotalCell val={grandTotal['TOTAL'] ?? null} />
                            </>
                        )}
                    </tr>
                </tbody>
            </table>

            {/* ═══ TABLE 2: % DE INGRESOS (L0 → L1 → L2) ═══ */}
            {revenueRow && (
                <>
                    <div className="rpt-separator">
                        <div className="sep-line"></div>
                        <span className="sep-label">% de Ingresos</span>
                        <div className="sep-line"></div>
                    </div>

                    <table className="rpt-table">
                        <TableHead columns={columns} />
                        <tbody>
                            {partidas.map((partida) => {
                                const isPctExpanded = expandedPctPartidas.has(partida.name);

                                return (
                                    <Fragment key={partida.name}>
                                        <tr className="rpt-row-l0" onClick={() => togglePctPartida(partida.name)}>
                                            <td>
                                                <span className="rpt-chevron">{isPctExpanded ? '\u25BE' : '\u25B8'}</span>
                                                {partida.name}
                                            </td>
                                            <NumCellsPct row={partida.totals as ReportRow} revenueRow={revenueRow} columns={columns} />
                                            <TotalCellPct costVal={partida.totals['TOTAL'] ?? null} revenueVal={revTotal} />
                                        </tr>

                                        {/* L1: CECOs */}
                                        {isPctExpanded && partida.cecos.map((ceco) => {
                                            const cecoKey = `${partida.name}|${ceco.code}`;
                                            const isCecoExpanded = expandedPctCecos.has(cecoKey);

                                            return (
                                                <Fragment key={cecoKey}>
                                                    <tr className="rpt-row-l1" onClick={() => togglePctCeco(partida.name, ceco.code)}>
                                                        <td>
                                                            <span className="rpt-chevron">{isCecoExpanded ? '\u25BE' : '\u25B8'}</span>
                                                            {ceco.code} {ceco.desc}
                                                        </td>
                                                        <NumCellsPct row={ceco.totals as ReportRow} revenueRow={revenueRow} columns={columns} />
                                                        <TotalCellPct costVal={ceco.totals['TOTAL'] ?? null} revenueVal={revTotal} />
                                                    </tr>

                                                    {/* L2: Cuentas */}
                                                    {isCecoExpanded && ceco.cuentas.map((cuenta, ci) => (
                                                        <tr key={ci} className="rpt-row-l2">
                                                            <td>
                                                                {cuenta.row['CUENTA_CONTABLE']} {cuenta.row['DESCRIPCION']}
                                                            </td>
                                                            <NumCellsPct row={cuenta.row} revenueRow={revenueRow} columns={columns} />
                                                            <TotalCellPct costVal={cuenta.row['TOTAL'] as number | null} revenueVal={revTotal} />
                                                        </tr>
                                                    ))}
                                                </Fragment>
                                            );
                                        })}
                                    </Fragment>
                                );
                            })}

                            {/* Pct grand total */}
                            <tr className="rpt-row-total">
                                <td>{TOTAL_LABELS[planillaFilter]}</td>
                                <NumCellsPct row={grandTotal as ReportRow} revenueRow={revenueRow} columns={columns} />
                                <TotalCellPct costVal={grandTotal['TOTAL'] ?? null} revenueVal={revTotal} />
                            </tr>
                        </tbody>
                    </table>
                </>
            )}
        </div>
    );
}

// React Fragment alias
const Fragment = ({ children }: { children: React.ReactNode }) => <>{children}</>;
