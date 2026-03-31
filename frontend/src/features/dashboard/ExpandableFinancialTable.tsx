import { useState, useMemo } from 'react';
import type { ReportRow, DisplayColumn } from '@/types';
import { formatNumber } from '@/utils/format';
import { getCellValue, getSummaryTotal, BOLD_ROWS_PL } from '@/utils/cellValue';

// ── CECO grouping definitions (COSTO only) ──────────────────────────

interface CecoGroupDef {
    label: string;
    codes: string[];
}

const CECO_GROUPS: CecoGroupDef[] = [
    { label: 'NOC', codes: ['100.101.01', '100.101.02'] },
    { label: 'PLANTA EXTERNA', codes: [
        '100.102.01', '100.102.02', '100.102.03', '100.102.04',
        '100.102.06', '100.102.07', '100.102.08', '100.102.09',
        '100.102.10', '100.102.13', '100.102.14', '100.102.15',
    ]},
    { label: 'COSTO INTERNET', codes: ['100.112.01'] },
    { label: 'COSTO TRANSPORTE', codes: ['100.113.01'] },
    { label: 'COSTO FIBRA OSCURA', codes: ['100.114'] },
    { label: 'COSTO CONTRATAS', codes: ['100.115.01'] },
    { label: 'CONSUMO ACCESORIOS Y EQUIPOS', codes: ['100.116.01'] },
    { label: 'COSTO INTERCOMPANY', codes: ['100.121.01', '100.121.02'] },
];

const OTROS_LABEL = 'OTROS';

function getGroupLabel(ccCode: string): string {
    for (const group of CECO_GROUPS) {
        for (const code of group.codes) {
            if (ccCode === code || ccCode.startsWith(code + '.')) return group.label;
        }
    }
    return OTROS_LABEL;
}

// ── CUENTA_CONTABLE grouping by 2-digit prefix ──────────────────────

const CUENTA_PREFIX_LABELS: Record<string, string> = {
    '61': 'Variacion de Inventario',
    '62': 'Gasto de Personal',
    '63': 'Servicios prestados por Terceros',
    '64': 'Gastos por Tributos',
    '65': 'Otros Gastos de Gestion',
    '67': 'Gastos Financieros',
    '68': 'Deterioro de Activos',
};

const KNOWN_PREFIXES = Object.keys(CUENTA_PREFIX_LABELS);

const FILTER_OPTIONS: { value: string; label: string }[] = [
    { value: 'all', label: 'Todas' },
    ...KNOWN_PREFIXES.map(p => ({ value: p, label: `${p}: ${CUENTA_PREFIX_LABELS[p]}` })),
];

function getCuentaPrefix(cuenta: string): string | null {
    const prefix = cuenta.substring(0, 2);
    return KNOWN_PREFIXES.includes(prefix) ? prefix : null;
}

// ── Cuenta category structures ───────────────────────────────────────

interface CuentaCategory {
    prefix: string;
    label: string;
    data: ReportRow;
    cuentaRows: ReportRow[];
}

interface UngroupedCuenta {
    prefix: null;
    row: ReportRow;
}

type CuentaEntry = CuentaCategory | UngroupedCuenta;

function buildCuentaEntries(cuentaRows: ReportRow[], columns: DisplayColumn[]): CuentaEntry[] {
    const monthKeys = new Set<string>();
    for (const col of columns) {
        for (const m of col.sourceMonths) monthKeys.add(m);
    }

    const categoryMap = new Map<string, { rows: ReportRow[]; data: Record<string, number> }>();
    const ungrouped: ReportRow[] = [];

    for (const row of cuentaRows) {
        const cuenta = String(row['CUENTA_CONTABLE'] ?? '');
        const prefix = getCuentaPrefix(cuenta);

        if (prefix) {
            if (!categoryMap.has(prefix)) {
                categoryMap.set(prefix, { rows: [], data: {} });
            }
            const cat = categoryMap.get(prefix)!;
            cat.rows.push(row);
            for (const m of monthKeys) {
                cat.data[m] = (cat.data[m] ?? 0) + ((row[m] as number) ?? 0);
            }
            cat.data['TOTAL'] = (cat.data['TOTAL'] ?? 0) + ((row['TOTAL'] as number) ?? 0);
        } else {
            ungrouped.push(row);
        }
    }

    const entries: CuentaEntry[] = [];
    for (const prefix of KNOWN_PREFIXES) {
        const cat = categoryMap.get(prefix);
        if (!cat || cat.rows.length === 0) continue;
        entries.push({
            prefix,
            label: `${prefix}: ${CUENTA_PREFIX_LABELS[prefix]}`,
            data: cat.data as ReportRow,
            cuentaRows: cat.rows,
        });
    }
    for (const row of ungrouped) {
        entries.push({ prefix: null, row });
    }

    return entries;
}

// ── Aggregation helpers ──────────────────────────────────────────────

function sumRows(rows: ReportRow[], columns: DisplayColumn[]): Record<string, number> {
    const monthKeys = new Set<string>();
    for (const col of columns) {
        for (const m of col.sourceMonths) monthKeys.add(m);
    }
    const sums: Record<string, number> = {};
    for (const row of rows) {
        for (const m of monthKeys) {
            sums[m] = (sums[m] ?? 0) + ((row[m] as number) ?? 0);
        }
        sums['TOTAL'] = (sums['TOTAL'] ?? 0) + ((row['TOTAL'] as number) ?? 0);
    }
    return sums;
}

// ── CECO group building (COSTO only, derived from costoByCuenta) ─────

interface CecoGroup {
    label: string;
    data: ReportRow;
    cuentaRows: ReportRow[];
}

function buildCecoGroups(costoByCuenta: ReportRow[], columns: DisplayColumn[]): CecoGroup[] {
    const cuentaByGroup = new Map<string, ReportRow[]>();
    for (const row of costoByCuenta) {
        const cc = String(row['CENTRO_COSTO'] ?? '');
        const groupLabel = getGroupLabel(cc);
        if (!cuentaByGroup.has(groupLabel)) cuentaByGroup.set(groupLabel, []);
        cuentaByGroup.get(groupLabel)!.push(row);
    }

    const result: CecoGroup[] = [];
    for (const g of CECO_GROUPS) {
        const rows = cuentaByGroup.get(g.label);
        if (!rows || rows.length === 0) continue;
        result.push({ label: g.label, data: sumRows(rows, columns) as ReportRow, cuentaRows: rows });
    }
    const otrosRows = cuentaByGroup.get(OTROS_LABEL);
    if (otrosRows && otrosRows.length > 0) {
        result.push({ label: OTROS_LABEL, data: sumRows(otrosRows, columns) as ReportRow, cuentaRows: otrosRows });
    }
    return result;
}

// ── Which PARTIDA_PL rows are expandable and how ─────────────────────

/** COSTO uses the CECO → Cuenta Category → Cuenta hierarchy */
const CECO_EXPANDABLE = new Set(['COSTO']);

/** These use the simpler Cuenta Category → Cuenta hierarchy (no CECO) */
const CUENTA_EXPANDABLE = new Set([
    'GASTO VENTA', 'GASTO ADMIN', 'D&A - COSTO', 'D&A - GASTO',
    'OTROS INGRESOS', 'OTROS EGRESOS', 'PARTICIPACION DE TRABAJADORES', 'PROVISION INCOBRABLE',
]);

// ── Component ────────────────────────────────────────────────────────

interface ExpandableFinancialTableProps {
    rows: ReportRow[];
    columns: DisplayColumn[];
    costoByCuenta: ReportRow[];
    gastoVentaByCuenta: ReportRow[];
    gastoAdminByCuenta: ReportRow[];
    dyaCostoByCuenta: ReportRow[];
    dyaGastoByCuenta: ReportRow[];
    otrosIngresosByCuenta: ReportRow[];
    otrosEgresosByCuenta: ReportRow[];
    participacionByCuenta: ReportRow[];
    provisionByCuenta: ReportRow[];
}

function cellClass(val: number | null | undefined, isBold: boolean): string {
    if (val === null || val === undefined) return 'cell-normal';
    if (val === 0) return 'cell-zero';
    if (val < 0) return 'cell-neg';
    return isBold ? 'cell-bold' : 'cell-normal';
}

function Chevron({ expanded }: { expanded: boolean }) {
    return (
        <svg
            className={`w-3.5 h-3.5 shrink-0 text-txt-muted transition-transform duration-150 ${expanded ? 'rotate-90' : ''}`}
            fill="none" stroke="currentColor" viewBox="0 0 24 24"
        >
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
        </svg>
    );
}

export default function ExpandableFinancialTable(props: ExpandableFinancialTableProps) {
    const { rows, columns, costoByCuenta, gastoVentaByCuenta, gastoAdminByCuenta, dyaCostoByCuenta, dyaGastoByCuenta, otrosIngresosByCuenta, otrosEgresosByCuenta, participacionByCuenta, provisionByCuenta } = props;

    const [expandedPartidas, setExpandedPartidas] = useState<Set<string>>(new Set());
    const [expandedCecoGroups, setExpandedCecoGroups] = useState<Set<string>>(new Set());
    // "PARTIDA|groupOrPrefix" for cuenta categories inside CECO groups
    // "PARTIDA|prefix" for cuenta categories directly under a partida
    const [expandedCuentaCats, setExpandedCuentaCats] = useState<Set<string>>(new Set());
    const [cuentaFilter, setCuentaFilter] = useState<string>('all');

    const togglePartida = (partida: string) => {
        setExpandedPartidas(prev => {
            const next = new Set(prev);
            if (next.has(partida)) {
                next.delete(partida);
                // Collapse all children
                setExpandedCecoGroups(prev2 => {
                    const next2 = new Set(prev2);
                    for (const key of next2) if (key.startsWith(partida + '|')) next2.delete(key);
                    return next2;
                });
                setExpandedCuentaCats(prev2 => {
                    const next2 = new Set(prev2);
                    for (const key of next2) if (key.startsWith(partida + '|')) next2.delete(key);
                    return next2;
                });
            } else {
                next.add(partida);
            }
            return next;
        });
    };

    const toggleCecoGroup = (partida: string, groupLabel: string) => {
        const key = `${partida}|${groupLabel}`;
        setExpandedCecoGroups(prev => {
            const next = new Set(prev);
            if (next.has(key)) {
                next.delete(key);
                setExpandedCuentaCats(prev2 => {
                    const next2 = new Set(prev2);
                    for (const k of next2) if (k.startsWith(`${partida}|${groupLabel}|`)) next2.delete(k);
                    return next2;
                });
            } else {
                next.add(key);
            }
            return next;
        });
    };

    const toggleCuentaCat = (key: string) => {
        setExpandedCuentaCats(prev => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

    const isFiltered = cuentaFilter !== 'all';

    // Get the by-cuenta data for a given partida
    const byCuentaMap: Record<string, ReportRow[]> = useMemo(() => ({
        'GASTO VENTA': gastoVentaByCuenta,
        'GASTO ADMIN': gastoAdminByCuenta,
        'D&A - COSTO': dyaCostoByCuenta,
        'D&A - GASTO': dyaGastoByCuenta,
        'OTROS INGRESOS': otrosIngresosByCuenta,
        'OTROS EGRESOS': otrosEgresosByCuenta,
        'PARTICIPACION DE TRABAJADORES': participacionByCuenta,
        'PROVISION INCOBRABLE': provisionByCuenta,
    }), [gastoVentaByCuenta, gastoAdminByCuenta, dyaCostoByCuenta, dyaGastoByCuenta, otrosIngresosByCuenta, otrosEgresosByCuenta, participacionByCuenta, provisionByCuenta]);

    // Filter all cuenta data by selected prefix
    const filterCuenta = (rows: ReportRow[]): ReportRow[] => {
        if (!isFiltered) return rows;
        return rows.filter(r => String(r['CUENTA_CONTABLE'] ?? '').startsWith(cuentaFilter));
    };

    // COSTO: filtered cuenta data → CECO groups
    const filteredCostoCuenta = useMemo(() => filterCuenta(costoByCuenta), [costoByCuenta, cuentaFilter]);
    const cecoGroups = useMemo(() => buildCecoGroups(filteredCostoCuenta, columns), [filteredCostoCuenta, columns]);
    const cuentaEntriesByCecoGroup = useMemo(() => {
        const map = new Map<string, CuentaEntry[]>();
        for (const g of cecoGroups) {
            map.set(g.label, buildCuentaEntries(g.cuentaRows, columns));
        }
        return map;
    }, [cecoGroups, columns]);

    // Simple expandable partidas: filtered cuenta → entries
    const cuentaEntriesByPartida = useMemo(() => {
        const map = new Map<string, { entries: CuentaEntry[]; filteredTotal: ReportRow }>();
        for (const partida of CUENTA_EXPANDABLE) {
            const raw = byCuentaMap[partida] ?? [];
            const filtered = filterCuenta(raw);
            const entries = buildCuentaEntries(filtered, columns);
            const filteredTotal = { PARTIDA_PL: partida, ...sumRows(filtered, columns) } as ReportRow;
            map.set(partida, { entries, filteredTotal });
        }
        return map;
    }, [byCuentaMap, cuentaFilter, columns]);

    // Filtered COSTO total
    const filteredCostoRow = useMemo(
        () => isFiltered ? { PARTIDA_PL: 'COSTO', ...sumRows(filteredCostoCuenta, columns) } as ReportRow : null,
        [isFiltered, filteredCostoCuenta, columns],
    );

    const headerCols = useMemo(() => [...columns.map(c => c.header), 'TOTAL'], [columns]);

    const isExpandable = (label: string) => CECO_EXPANDABLE.has(label) || CUENTA_EXPANDABLE.has(label);

    /** Get display row — if filtered, use recomputed values for expandable partidas */
    const getDisplayRow = (row: ReportRow, label: string): ReportRow => {
        if (!isFiltered) return row;
        if (label === 'COSTO' && filteredCostoRow) return filteredCostoRow;
        const partidaData = cuentaEntriesByPartida.get(label);
        if (partidaData) return partidaData.filteredTotal;
        return row;
    };

    return (
        <div className="space-y-3">
            {/* Filter bar */}
            <div className="flex items-center gap-2 flex-wrap">
                <span className="text-[11px] uppercase font-semibold text-txt-muted tracking-wide">Cuenta:</span>
                {FILTER_OPTIONS.map(opt => (
                    <button
                        key={opt.value}
                        onClick={() => setCuentaFilter(opt.value)}
                        className={`px-3 py-1.5 text-xs font-medium rounded-md border transition-colors
                            ${cuentaFilter === opt.value
                                ? 'bg-accent text-white border-accent'
                                : 'bg-surface border-border text-txt-secondary hover:bg-surface-alt hover:text-txt'}`}
                    >
                        {opt.label}
                    </button>
                ))}
            </div>

            {/* Table */}
            <div className="table-card overflow-x-auto">
                <table className="min-w-full text-xs">
                    <thead>
                        <tr className="thead-row">
                            <th scope="col" className="thead-cell sticky-col bg-surface-alt text-left min-w-[360px]">
                                PARTIDA
                            </th>
                            {columns.map(col => (
                                <th scope="col" key={col.header} className="thead-cell text-right min-w-[90px]">
                                    {col.header}
                                </th>
                            ))}
                            <th scope="col" className="thead-cell text-right min-w-[90px] cell-total-col">
                                TOTAL
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row, idx) => {
                            const label = row['PARTIDA_PL'] as string;
                            const isEmpty = !label || label.trim() === '';
                            const isBold = BOLD_ROWS_PL.has(label);
                            const canExpand = isExpandable(label);
                            const isExpanded = expandedPartidas.has(label);
                            const displayRow = getDisplayRow(row, label);

                            if (isEmpty) {
                                return (
                                    <tr key={idx} className="h-1.5">
                                        <td colSpan={headerCols.length + 1} className="bg-surface-alt/50"></td>
                                    </tr>
                                );
                            }

                            return (
                                <Frag key={idx}>
                                    {/* Summary row */}
                                    <tr
                                        className={`row-base
                                            ${isBold ? 'bg-surface-alt hover:bg-surface-alt' : ''}
                                            ${canExpand ? 'cursor-pointer' : ''}`}
                                        onClick={canExpand ? () => togglePartida(label) : undefined}
                                    >
                                        <td className={`sticky-col px-4 py-2 whitespace-nowrap
                                            ${isBold
                                                ? 'font-bold text-txt bg-surface-alt'
                                                : 'text-txt-secondary bg-surface'}`}>
                                            <span className="flex items-center gap-1.5">
                                                {canExpand && <Chevron expanded={isExpanded} />}
                                                {label}
                                                {isFiltered && canExpand && (
                                                    <span className="text-[10px] font-medium text-accent bg-accent/10 px-1.5 py-0.5 rounded">
                                                        {cuentaFilter}
                                                    </span>
                                                )}
                                            </span>
                                        </td>
                                        {columns.map(col => {
                                            const val = getCellValue(displayRow, col);
                                            return (
                                                <td key={col.header} className={`cell-base ${cellClass(val, isBold)}`}>
                                                    {formatNumber(val)}
                                                </td>
                                            );
                                        })}
                                        {(() => {
                                            const total = (isFiltered && canExpand)
                                                ? (displayRow['TOTAL'] as number | null)
                                                : getSummaryTotal(displayRow, columns, 'pl');
                                            return (
                                                <td className={`cell-base cell-total-col ${cellClass(total, true)}`}>
                                                    {formatNumber(total)}
                                                </td>
                                            );
                                        })()}
                                    </tr>

                                    {/* COSTO expansion: CECO groups → cuenta categories → cuentas */}
                                    {isExpanded && CECO_EXPANDABLE.has(label) && (
                                        <CecoExpansion
                                            partida={label}
                                            cecoGroups={cecoGroups}
                                            cuentaEntriesByCecoGroup={cuentaEntriesByCecoGroup}
                                            expandedCecoGroups={expandedCecoGroups}
                                            expandedCuentaCats={expandedCuentaCats}
                                            toggleCecoGroup={toggleCecoGroup}
                                            toggleCuentaCat={toggleCuentaCat}
                                            columns={columns}
                                        />
                                    )}

                                    {/* Simple expansion: cuenta categories → cuentas */}
                                    {isExpanded && CUENTA_EXPANDABLE.has(label) && (
                                        <CuentaExpansion
                                            partida={label}
                                            entries={cuentaEntriesByPartida.get(label)?.entries ?? []}
                                            expandedCuentaCats={expandedCuentaCats}
                                            toggleCuentaCat={toggleCuentaCat}
                                            columns={columns}
                                        />
                                    )}
                                </Frag>
                            );
                        })}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

// ── CECO expansion (COSTO) ───────────────────────────────────────────

function CecoExpansion({ partida, cecoGroups, cuentaEntriesByCecoGroup, expandedCecoGroups, expandedCuentaCats, toggleCecoGroup, toggleCuentaCat, columns }: {
    partida: string;
    cecoGroups: CecoGroup[];
    cuentaEntriesByCecoGroup: Map<string, CuentaEntry[]>;
    expandedCecoGroups: Set<string>;
    expandedCuentaCats: Set<string>;
    toggleCecoGroup: (partida: string, groupLabel: string) => void;
    toggleCuentaCat: (key: string) => void;
    columns: DisplayColumn[];
}) {
    return (
        <>
            {cecoGroups.map((group) => {
                const groupKey = `${partida}|${group.label}`;
                const isGroupExpanded = expandedCecoGroups.has(groupKey);
                const cuentaEntries = cuentaEntriesByCecoGroup.get(group.label) ?? [];

                return (
                    <Frag key={`cg-${group.label}`}>
                        <tr
                            className="row-base cursor-pointer bg-blue-50/40 hover:bg-blue-50/70"
                            onClick={() => toggleCecoGroup(partida, group.label)}
                        >
                            <td className="sticky-col px-4 py-2 whitespace-nowrap text-txt-secondary bg-blue-50/40">
                                <span className="flex items-center gap-1.5 pl-5">
                                    <Chevron expanded={isGroupExpanded} />
                                    <span className="font-semibold text-txt-secondary">{group.label}</span>
                                </span>
                            </td>
                            <NumCells row={group.data} columns={columns} bold={false} />
                            <TotalCell val={group.data['TOTAL'] as number | null} />
                        </tr>

                        {isGroupExpanded && (
                            <CuentaEntryRows
                                entries={cuentaEntries}
                                parentKey={`${partida}|${group.label}`}
                                expandedCuentaCats={expandedCuentaCats}
                                toggleCuentaCat={toggleCuentaCat}
                                columns={columns}
                                indent={10}
                                childIndent="4.5rem"
                            />
                        )}
                    </Frag>
                );
            })}
        </>
    );
}

// ── Simple cuenta expansion (GASTO VENTA, etc.) ──────────────────────

function CuentaExpansion({ partida, entries, expandedCuentaCats, toggleCuentaCat, columns }: {
    partida: string;
    entries: CuentaEntry[];
    expandedCuentaCats: Set<string>;
    toggleCuentaCat: (key: string) => void;
    columns: DisplayColumn[];
}) {
    return (
        <CuentaEntryRows
            entries={entries}
            parentKey={partida}
            expandedCuentaCats={expandedCuentaCats}
            toggleCuentaCat={toggleCuentaCat}
            columns={columns}
            indent={5}
            childIndent="3rem"
        />
    );
}

// ── Cuenta entry rows (shared between CECO and simple modes) ─────────

function CuentaEntryRows({ entries, parentKey, expandedCuentaCats, toggleCuentaCat, columns, indent, childIndent }: {
    entries: CuentaEntry[];
    parentKey: string;
    expandedCuentaCats: Set<string>;
    toggleCuentaCat: (key: string) => void;
    columns: DisplayColumn[];
    indent: number;       // pl- value for category rows
    childIndent: string;  // pl-[...] value for individual cuenta rows
}) {
    return (
        <>
            {entries.map((entry, ei) => {
                if (entry.prefix === null) {
                    const cuentaRow = entry.row;
                    return (
                        <tr key={`ug-${ei}`} className="row-base bg-amber-50/30 hover:bg-amber-50/60">
                            <td className="sticky-col px-4 py-1.5 whitespace-nowrap text-txt-muted bg-amber-50/30">
                                <span className="flex items-center gap-1.5" style={{ paddingLeft: childIndent }}>
                                    <span className="font-mono text-[11px]">{cuentaRow['CUENTA_CONTABLE']}</span>
                                    <span className="text-txt-faint">&mdash;</span>
                                    <span className="text-[11px]">{cuentaRow['DESCRIPCION']}</span>
                                </span>
                            </td>
                            <NumCells row={cuentaRow} columns={columns} bold={false} small />
                            <TotalCell val={cuentaRow['TOTAL'] as number | null} small />
                        </tr>
                    );
                }

                const catKey = `${parentKey}|${entry.prefix}`;
                const isCatExpanded = expandedCuentaCats.has(catKey);

                return (
                    <Frag key={`cat-${entry.prefix}`}>
                        <tr
                            className="row-base cursor-pointer bg-amber-50/30 hover:bg-amber-50/60"
                            onClick={() => toggleCuentaCat(catKey)}
                        >
                            <td className="sticky-col px-4 py-1.5 whitespace-nowrap text-txt-secondary bg-amber-50/30">
                                <span className="flex items-center gap-1.5" style={{ paddingLeft: `${indent * 4}px` }}>
                                    <Chevron expanded={isCatExpanded} />
                                    <span className="font-medium text-[12px]">{entry.label}</span>
                                </span>
                            </td>
                            <NumCells row={entry.data} columns={columns} bold={false} small />
                            <TotalCell val={entry.data['TOTAL'] as number | null} small />
                        </tr>

                        {isCatExpanded && entry.cuentaRows.map((cuentaRow, ki) => (
                            <tr key={`cr-${ki}`} className="row-base bg-emerald-50/25 hover:bg-emerald-50/50">
                                <td className="sticky-col px-4 py-1.5 whitespace-nowrap text-txt-muted bg-emerald-50/25">
                                    <span className="flex items-center gap-1.5" style={{ paddingLeft: childIndent }}>
                                        <span className="font-mono text-[11px]">{cuentaRow['CUENTA_CONTABLE']}</span>
                                        <span className="text-txt-faint">&mdash;</span>
                                        <span className="text-[11px]">{cuentaRow['DESCRIPCION']}</span>
                                    </span>
                                </td>
                                <NumCells row={cuentaRow} columns={columns} bold={false} small />
                                <TotalCell val={cuentaRow['TOTAL'] as number | null} small />
                            </tr>
                        ))}
                    </Frag>
                );
            })}
        </>
    );
}

// ── Shared small components ──────────────────────────────────────────

function NumCells({ row, columns, bold, small }: { row: ReportRow; columns: DisplayColumn[]; bold: boolean; small?: boolean }) {
    return (
        <>
            {columns.map(col => {
                const val = getCellValue(row, col);
                return (
                    <td key={col.header} className={`cell-base ${small ? 'text-[11px]' : ''} ${cellClass(val, bold)}`}>
                        {formatNumber(val)}
                    </td>
                );
            })}
        </>
    );
}

function TotalCell({ val, small }: { val: number | null; small?: boolean }) {
    return (
        <td className={`cell-base cell-total-col ${small ? 'text-[11px]' : ''} ${cellClass(val, !small)}`}>
            {formatNumber(val)}
        </td>
    );
}

function Frag({ children }: { children: React.ReactNode }) {
    return <>{children}</>;
}
