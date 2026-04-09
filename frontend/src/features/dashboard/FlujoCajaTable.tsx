import { useState, useMemo } from 'react';
import type { ReportRow, DisplayColumn } from '@/types';
import { formatNumber } from '@/utils/format';
import { getCellValue } from '@/utils/cellValue';
import { negClass } from '@/utils/classHelpers';
import { buildCecoGroups, sumRows } from '@/utils/cecoGrouping';
import type { CecoGroup } from '@/utils/cecoGrouping';

// ── Row definitions ─────────────────────────────────────────────────

interface DataRowDef {
    key: string;
    label: string;
    isComputed: false;
    hasCeco: boolean;
}

interface ComputedRowDef {
    key: string;
    label: string;
    isComputed: true;
    sumOf: string[];
}

type RowDef = DataRowDef | ComputedRowDef;

interface SectionDef {
    title: string;
    rows: RowDef[];
}

const FLUJO_SECTIONS: SectionDef[] = [
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

const FLUJO_GRAND_TOTAL: ComputedRowDef = {
    key: 'total', label: 'TOTAL', isComputed: true,
    sumOf: ['ingresos_ord', 'ingresos_proy', 'costo', 'gasto_venta', 'gasto_admin', 'participacion', 'otros_ingresos', 'otros_egresos'],
};

// ── Helpers ──────────────────────────────────────────────────────────

function NumCells({ row, columns }: { row: ReportRow; columns: DisplayColumn[] }) {
    return (
        <>
            {columns.map(col => {
                const val = getCellValue(row, col);
                return (
                    <td key={col.header} className={negClass(val)}>
                        {formatNumber(val)}
                    </td>
                );
            })}
        </>
    );
}

function TotalCell({ row }: { row: ReportRow }) {
    const total = row['TOTAL'] as number | null ?? null;
    return (
        <td className={negClass(total)} style={{ fontWeight: 600 }}>
            {formatNumber(total)}
        </td>
    );
}

// ── Component ────────────────────────────────────────────────────────

interface FlujoCajaTableProps {
    columns: DisplayColumn[];
    ingresosOrdByCuenta: ReportRow[];
    ingresosProyByCuenta: ReportRow[];
    costoByCuenta: ReportRow[];
    gastoVentaByCuenta: ReportRow[];
    gastoAdminByCuenta: ReportRow[];
    participacionByCuenta: ReportRow[];
    otrosIngresosByCuenta: ReportRow[];
    otrosEgresosByCuenta: ReportRow[];
}

export default function FlujoCajaTable(props: FlujoCajaTableProps) {
    const {
        columns, ingresosOrdByCuenta, ingresosProyByCuenta,
        costoByCuenta, gastoVentaByCuenta, gastoAdminByCuenta,
        participacionByCuenta, otrosIngresosByCuenta, otrosEgresosByCuenta,
    } = props;

    const [expandedPartidas, setExpandedPartidas] = useState<Set<string>>(new Set());
    const [expandedCecos, setExpandedCecos] = useState<Set<string>>(new Set());
    const [excludedCuentas, setExcludedCuentas] = useState<Set<string>>(new Set());
    const [filterOpen, setFilterOpen] = useState(false);
    const [filterSearch, setFilterSearch] = useState('');

    const togglePartida = (key: string) => {
        setExpandedPartidas(prev => {
            const next = new Set(prev);
            if (next.has(key)) {
                next.delete(key);
                // Collapse child CECOs
                setExpandedCecos(prev2 => {
                    const next2 = new Set(prev2);
                    for (const k of next2) if (k.startsWith(key + '|')) next2.delete(k);
                    return next2;
                });
            } else {
                next.add(key);
            }
            return next;
        });
    };

    const toggleCeco = (partidaKey: string, cecoLabel: string) => {
        const key = `${partidaKey}|${cecoLabel}`;
        setExpandedCecos(prev => {
            const next = new Set(prev);
            if (next.has(key)) next.delete(key);
            else next.add(key);
            return next;
        });
    };

    const toggleExcludeCuenta = (cuenta: string) => {
        setExcludedCuentas(prev => {
            const next = new Set(prev);
            if (next.has(cuenta)) next.delete(cuenta);
            else next.add(cuenta);
            return next;
        });
    };

    // Map partida keys to their raw data arrays
    const rawMap: Record<string, ReportRow[]> = useMemo(() => ({
        ingresos_ord: ingresosOrdByCuenta,
        ingresos_proy: ingresosProyByCuenta,
        costo: costoByCuenta,
        gasto_venta: gastoVentaByCuenta,
        gasto_admin: gastoAdminByCuenta,
        participacion: participacionByCuenta,
        otros_ingresos: otrosIngresosByCuenta,
        otros_egresos: otrosEgresosByCuenta,
    }), [ingresosOrdByCuenta, ingresosProyByCuenta, costoByCuenta, gastoVentaByCuenta, gastoAdminByCuenta, participacionByCuenta, otrosIngresosByCuenta, otrosEgresosByCuenta]);

    // Collect all distinct CUENTA_CONTABLEs for the exclusion filter
    const allCuentas = useMemo(() => {
        const map = new Map<string, string>();
        for (const rows of Object.values(rawMap)) {
            for (const row of rows) {
                const cc = String(row['CUENTA_CONTABLE'] ?? '');
                if (cc && cc !== 'TOTAL') {
                    if (!map.has(cc)) map.set(cc, String(row['DESCRIPCION'] ?? ''));
                }
            }
        }
        return Array.from(map.entries())
            .sort(([a], [b]) => a.localeCompare(b))
            .map(([code, desc]) => ({ code, desc }));
    }, [rawMap]);

    // Filter rows by excluded cuentas, then build CECO groups + totals
    const partidaData = useMemo(() => {
        const hasExclusions = excludedCuentas.size > 0;
        const result = new Map<string, {
            cecoGroups: CecoGroup[];
            cuentaRows: ReportRow[];
            totalRow: ReportRow;
        }>();

        for (const [key, rows] of Object.entries(rawMap)) {
            const filtered = hasExclusions
                ? rows.filter(r => !excludedCuentas.has(String(r['CUENTA_CONTABLE'] ?? '')))
                : rows;

            const def = FLUJO_SECTIONS.flatMap(s => s.rows).find(r => r.key === key);
            const hasCeco = def && !def.isComputed ? def.hasCeco : false;

            const cecoGroups = hasCeco ? buildCecoGroups(filtered, columns) : [];
            const totalRow = sumRows(filtered, columns) as ReportRow;
            result.set(key, { cecoGroups, cuentaRows: filtered, totalRow });
        }

        return result;
    }, [rawMap, excludedCuentas, columns]);

    // Compute subtotal rows
    const computeSum = (keys: string[]): ReportRow => {
        const sums: Record<string, number> = {};
        for (const key of keys) {
            const data = partidaData.get(key)?.totalRow ?? {};
            for (const [m, v] of Object.entries(data)) {
                if (typeof v === 'number') {
                    sums[m] = (sums[m] ?? 0) + v;
                }
            }
        }
        return sums as ReportRow;
    };

    // Filter the cuenta list for the search input
    const filteredCuentaList = useMemo(() => {
        if (!filterSearch) return allCuentas;
        const q = filterSearch.toLowerCase();
        return allCuentas.filter(c =>
            c.code.toLowerCase().includes(q) || c.desc.toLowerCase().includes(q)
        );
    }, [allCuentas, filterSearch]);

    const hasExclusions = excludedCuentas.size > 0;

    return (
        <div>
            {/* CUENTA_CONTABLE exclusion filter */}
            <nav className="flex items-baseline gap-6 mb-10 flex-wrap">
                <span className="text-[11px] font-semibold uppercase text-txt-muted" style={{ letterSpacing: '1.2px' }}>
                    Excluir Cuentas
                </span>
                <button
                    onClick={() => setFilterOpen(!filterOpen)}
                    className={`text-[13px] bg-transparent border-none cursor-pointer pb-1.5 transition-all
                        ${filterOpen || hasExclusions
                            ? 'text-txt font-semibold border-b-[3px] border-b-txt'
                            : 'text-txt-muted font-normal border-b-2 border-b-transparent hover:text-txt-secondary'
                        }`}
                    style={{ letterSpacing: '0.2px' }}
                >
                    {hasExclusions ? `${excludedCuentas.size} excluida${excludedCuentas.size > 1 ? 's' : ''}` : 'Ninguna'}
                </button>
                {hasExclusions && (
                    <button
                        onClick={() => setExcludedCuentas(new Set())}
                        className="text-[12px] text-txt-muted hover:text-txt-secondary bg-transparent border-none cursor-pointer"
                    >
                        Limpiar
                    </button>
                )}
            </nav>

            {filterOpen && (
                <div className="mb-8 border border-border rounded-[10px] p-4 max-w-2xl">
                    <input
                        type="text"
                        placeholder="Buscar cuenta..."
                        value={filterSearch}
                        onChange={e => setFilterSearch(e.target.value)}
                        className="w-full mb-3 px-3 py-1.5 text-[13px] border border-border rounded-md bg-bg text-txt outline-none focus:border-accent"
                    />
                    <div className="max-h-64 overflow-y-auto space-y-1">
                        {filteredCuentaList.map(c => (
                            <label key={c.code} className="flex items-center gap-2 py-0.5 cursor-pointer text-[13px] text-txt-secondary hover:text-txt">
                                <input
                                    type="checkbox"
                                    checked={excludedCuentas.has(c.code)}
                                    onChange={() => toggleExcludeCuenta(c.code)}
                                    className="accent-accent"
                                />
                                <span className="font-mono text-[12px] text-txt-muted">{c.code}</span>
                                <span>{c.desc}</span>
                            </label>
                        ))}
                        {filteredCuentaList.length === 0 && (
                            <p className="text-[13px] text-txt-muted py-2">Sin resultados</p>
                        )}
                    </div>
                </div>
            )}

            {/* Table */}
            <div className="overflow-x-auto">
                <table className="rpt-table">
                    <thead>
                        <tr>
                            <th className="text-left rpt-sticky">Partida</th>
                            {columns.map(col => (
                                <th key={col.header}>{col.header}</th>
                            ))}
                            <th className="rpt-col-total">Total</th>
                        </tr>
                    </thead>
                    <tbody>
                        {FLUJO_SECTIONS.map(section => (
                            <Rows key={section.title}>
                                <tr className="rpt-section-header">
                                    <td className="rpt-sticky" colSpan={columns.length + 2}>
                                        {section.title}
                                    </td>
                                </tr>
                                {section.rows.map(rowDef => {
                                    if (rowDef.isComputed) {
                                        const sumRow = computeSum(rowDef.sumOf);
                                        return (
                                            <tr key={rowDef.key} className="rpt-row-l0" style={{ fontWeight: 700 }}>
                                                <td className="rpt-sticky">{rowDef.label}</td>
                                                <NumCells row={sumRow} columns={columns} />
                                                <TotalCell row={sumRow} />
                                            </tr>
                                        );
                                    }

                                    const data = partidaData.get(rowDef.key);
                                    if (!data) return null;
                                    const isExpanded = expandedPartidas.has(rowDef.key);

                                    return (
                                        <Rows key={rowDef.key}>
                                            <tr
                                                className="rpt-row-l0"
                                                onClick={() => togglePartida(rowDef.key)}
                                                style={{ cursor: 'pointer' }}
                                            >
                                                <td className="rpt-sticky">
                                                    <span className="rpt-chevron">{isExpanded ? '\u25BE' : '\u25B8'}</span>
                                                    {rowDef.label}
                                                    {hasExclusions && (
                                                        <span className="text-[10px] text-txt-muted ml-2">(filtrado)</span>
                                                    )}
                                                </td>
                                                <NumCells row={data.totalRow} columns={columns} />
                                                <TotalCell row={data.totalRow} />
                                            </tr>

                                            {isExpanded && rowDef.hasCeco && (
                                                <CecoExpansion
                                                    partidaKey={rowDef.key}
                                                    cecoGroups={data.cecoGroups}
                                                    expandedCecos={expandedCecos}
                                                    toggleCeco={toggleCeco}
                                                    columns={columns}
                                                />
                                            )}

                                            {isExpanded && !rowDef.hasCeco && (
                                                <CuentaDirectRows rows={data.cuentaRows} columns={columns} />
                                            )}
                                        </Rows>
                                    );
                                })}
                            </Rows>
                        ))}
                        {/* Grand total */}
                        {(() => {
                            const sumRow = computeSum(FLUJO_GRAND_TOTAL.sumOf);
                            return (
                                <tr className="rpt-row-l0" style={{ fontWeight: 700 }}>
                                    <td className="rpt-sticky">{FLUJO_GRAND_TOTAL.label}</td>
                                    <NumCells row={sumRow} columns={columns} />
                                    <TotalCell row={sumRow} />
                                </tr>
                            );
                        })()}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

// ── CECO expansion (for expense/cost lines) ─────────────────────────

function CecoExpansion({ partidaKey, cecoGroups, expandedCecos, toggleCeco, columns }: {
    partidaKey: string;
    cecoGroups: CecoGroup[];
    expandedCecos: Set<string>;
    toggleCeco: (partidaKey: string, cecoLabel: string) => void;
    columns: DisplayColumn[];
}) {
    return (
        <>
            {cecoGroups.map(group => {
                const groupKey = `${partidaKey}|${group.label}`;
                const isGroupExpanded = expandedCecos.has(groupKey);

                return (
                    <Rows key={`cg-${group.label}`}>
                        <tr
                            className="rpt-row-l1"
                            onClick={() => toggleCeco(partidaKey, group.label)}
                            style={{ cursor: 'pointer' }}
                        >
                            <td className="rpt-sticky">
                                <span className="rpt-chevron">{isGroupExpanded ? '\u25BE' : '\u25B8'}</span>
                                {group.label}
                            </td>
                            <NumCells row={group.data} columns={columns} />
                            <TotalCell row={group.data} />
                        </tr>

                        {isGroupExpanded && (
                            <CuentaDirectRows rows={group.cuentaRows} columns={columns} level="l2" />
                        )}
                    </Rows>
                );
            })}
        </>
    );
}

// ── Cuenta-level detail rows (used for revenue lines and CECO drill-down) ──

function CuentaDirectRows({ rows, columns, level = 'l1' }: {
    rows: ReportRow[];
    columns: DisplayColumn[];
    level?: 'l1' | 'l2';
}) {
    return (
        <>
            {rows.map((row, i) => {
                const cuenta = String(row['CUENTA_CONTABLE'] ?? '');
                const desc = String(row['DESCRIPCION'] ?? '');
                if (!cuenta || cuenta === 'TOTAL') return null;
                return (
                    <tr key={`c-${cuenta}-${i}`} className={`rpt-row-${level}`}>
                        <td className="rpt-sticky">
                            {cuenta} {desc}
                        </td>
                        <NumCells row={row} columns={columns} />
                        <TotalCell row={row} />
                    </tr>
                );
            })}
        </>
    );
}

function Rows({ children }: { children: React.ReactNode }) {
    return <>{children}</>;
}
