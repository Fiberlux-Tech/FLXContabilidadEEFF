import { Fragment, useMemo, useState, type CSSProperties, type ReactNode } from 'react';
import type { ReportRow } from '@/types';
import { formatNumber } from '@/utils/format';
import { CUENTA_PREFIX_LABELS, getCuentaPrefixAny } from '@/config/cecoGroups';

export const DETAIL_HEADERS: Record<string, string> = {
    ASIENTO: 'Asiento',
    CUENTA_CONTABLE: 'Cuenta',
    DESCRIPCION: 'Descripcion',
    NIT: 'NIT',
    RAZON_SOCIAL: 'Razon Social',
    CENTRO_COSTO: 'Centro Costo',
    DESC_CECO: 'Desc. CECO',
    FECHA: 'Fecha',
    SALDO: 'Saldo',
};

export const DETAIL_COLS = Object.keys(DETAIL_HEADERS);
export const PAGE_SIZES: number[] = [25, 50, 100];
export const DEFAULT_PAGE_SIZE = PAGE_SIZES[0];

const COL_WIDTHS: Record<string, string> = {
    ASIENTO: '9%',
    CUENTA_CONTABLE: '9%',
    DESCRIPCION: '22%',
    NIT: '10%',
    RAZON_SOCIAL: '18%',
    CENTRO_COSTO: '9%',
    DESC_CECO: '11%',
    FECHA: '8%',
    SALDO: '9%',
};

interface DetailDataTableProps {
    detailRows: ReportRow[];
    filteredRows: ReportRow[];
    filters: Record<string, string>;
    updateFilter: (col: string, value: string) => void;
    page: number;
    setPage: (fn: (p: number) => number) => void;
    pageSize: number;
    setPageSize: (size: number) => void;
    grouped: boolean;
}

interface CuentaGroup {
    prefix: string;
    rows: ReportRow[];
    subtotal: number;
}

function buildGroups(rows: ReportRow[]): CuentaGroup[] {
    const map = new Map<string, CuentaGroup>();
    for (const row of rows) {
        const prefix = getCuentaPrefixAny(row.CUENTA_CONTABLE as string);
        let g = map.get(prefix);
        if (!g) {
            g = { prefix, rows: [], subtotal: 0 };
            map.set(prefix, g);
        }
        g.rows.push(row);
        const saldo = row.SALDO;
        if (typeof saldo === 'number') g.subtotal += saldo;
    }
    return Array.from(map.values()).sort((a, b) => a.prefix.localeCompare(b.prefix));
}

function renderDataRow(row: ReportRow, key: string | number): ReactNode {
    return (
        <tr key={key} className="rpt-row-data">
            {DETAIL_COLS.map(col => {
                const val = row[col];
                const isSaldo = col === 'SALDO';
                const numVal = isSaldo ? (val as number) : null;
                const baseStyle: CSSProperties = isSaldo
                    ? { textAlign: 'right', fontWeight: 500 }
                    : {
                        textAlign: 'left',
                        overflow: 'hidden',
                        textOverflow: 'ellipsis',
                        whiteSpace: 'nowrap',
                    };
                const display = isSaldo ? formatNumber(val as number) : (val ?? '');
                return (
                    <td
                        key={col}
                        className={isSaldo && numVal !== null && numVal < 0 ? 'rpt-neg' : ''}
                        style={baseStyle}
                        title={!isSaldo ? String(val ?? '') : undefined}
                    >
                        {display}
                    </td>
                );
            })}
        </tr>
    );
}

export default function DetailDataTable({ detailRows, filteredRows, filters, updateFilter, page, setPage, pageSize, setPageSize, grouped }: DetailDataTableProps) {
    const [expandedGroups, setExpandedGroups] = useState<Set<string>>(new Set());

    const groups = useMemo(() => (grouped ? buildGroups(filteredRows) : []), [grouped, filteredRows]);
    const grandTotal = useMemo(() => {
        if (!grouped) return 0;
        return filteredRows.reduce((acc, r) => acc + (typeof r.SALDO === 'number' ? r.SALDO : 0), 0);
    }, [grouped, filteredRows]);

    const totalPages = Math.ceil(filteredRows.length / pageSize);
    const start = page * pageSize;
    const pageRows = filteredRows.slice(start, start + pageSize);
    const hasFilters = Object.values(filters).some(v => v.length > 0);

    const toggleGroup = (prefix: string) => {
        setExpandedGroups(prev => {
            const next = new Set(prev);
            if (next.has(prefix)) next.delete(prefix);
            else next.add(prefix);
            return next;
        });
    };

    return (
        <>
            {grouped && (
                <div className="flex justify-end mb-2 px-1">
                    <span className="text-xs text-txt-muted">
                        {groups.length} grupo{groups.length === 1 ? '' : 's'} · {filteredRows.length} registro{filteredRows.length === 1 ? '' : 's'}
                        {hasFilters && ` (${detailRows.length} total)`}
                    </span>
                </div>
            )}

            <div className="overflow-x-auto">
                <table className="rpt-table-auto" style={{ tableLayout: 'fixed', width: '100%' }}>
                    <colgroup>
                        {DETAIL_COLS.map(col => (
                            <col key={col} style={COL_WIDTHS[col] ? { width: COL_WIDTHS[col] } : undefined} />
                        ))}
                    </colgroup>
                    <thead>
                        <tr>
                            {DETAIL_COLS.map(col => (
                                <th key={col} className={col === 'SALDO' ? 'text-right' : 'text-left'}>
                                    {DETAIL_HEADERS[col]}
                                </th>
                            ))}
                        </tr>
                        <tr>
                            {DETAIL_COLS.map(col => (
                                <th key={col} style={{ padding: '4px 8px 10px', borderBottom: '1px solid #eee' }}>
                                    <input
                                        type="text"
                                        value={filters[col] ?? ''}
                                        onChange={e => updateFilter(col, e.target.value)}
                                        placeholder="Filtrar..."
                                        className={`filter-input ${col === 'SALDO' ? 'text-right' : 'text-left'}`}
                                    />
                                </th>
                            ))}
                        </tr>
                    </thead>
                    <tbody>
                        {grouped ? (
                            <>
                                {groups.map(g => {
                                    const isOpen = expandedGroups.has(g.prefix);
                                    const label = CUENTA_PREFIX_LABELS[g.prefix];
                                    const labelColSpan = DETAIL_COLS.length - 1;
                                    return (
                                        <Fragment key={g.prefix}>
                                            <tr className="rpt-row-l0">
                                                <td
                                                    colSpan={labelColSpan}
                                                    className="rpt-clickable"
                                                    onClick={() => toggleGroup(g.prefix)}
                                                >
                                                    <span className="rpt-chevron">{isOpen ? '▾' : '▸'}</span>
                                                    <span style={{ fontFamily: 'ui-monospace, Menlo, monospace', fontSize: 12, marginRight: 8 }}>
                                                        {g.prefix}
                                                    </span>
                                                    {label && <span style={{ fontWeight: 500 }}>{label}</span>}
                                                    <span style={{ marginLeft: 10, fontWeight: 400, color: '#888', fontSize: 12 }}>
                                                        · {g.rows.length} registro{g.rows.length === 1 ? '' : 's'}
                                                    </span>
                                                </td>
                                                <td
                                                    style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                                                    className={g.subtotal < 0 ? 'rpt-neg' : ''}
                                                >
                                                    {formatNumber(g.subtotal)}
                                                </td>
                                            </tr>
                                            {isOpen && g.rows.map((row, i) => renderDataRow(row, `${g.prefix}-${i}`))}
                                        </Fragment>
                                    );
                                })}
                                {groups.length > 0 && (
                                    <tr className="rpt-row-total">
                                        <td colSpan={DETAIL_COLS.length - 1}>TOTAL</td>
                                        <td
                                            style={{ textAlign: 'right', fontVariantNumeric: 'tabular-nums' }}
                                            className={grandTotal < 0 ? 'rpt-neg' : ''}
                                        >
                                            {formatNumber(grandTotal)}
                                        </td>
                                    </tr>
                                )}
                            </>
                        ) : (
                            pageRows.map((row, idx) => renderDataRow(row, idx))
                        )}
                    </tbody>
                </table>
            </div>

            {!grouped && (
                <div className="flex items-center justify-between mt-4 px-1">
                    <div className="flex items-baseline gap-3 text-xs">
                        <span className="text-txt-muted" style={{ letterSpacing: '0.5px' }}>Filas:</span>
                        {PAGE_SIZES.map(size => (
                            <button
                                key={size}
                                onClick={() => { setPageSize(size); setPage(() => 0); }}
                                className={`text-[13px] bg-transparent border-none cursor-pointer pb-0.5 transition-all
                                    ${pageSize === size
                                        ? 'text-txt font-semibold border-b-2 border-b-txt'
                                        : 'text-txt-muted font-normal border-b border-b-transparent hover:text-txt-secondary'
                                    }`}
                            >
                                {size}
                            </button>
                        ))}
                    </div>
                    <div className="flex items-center gap-3 text-xs text-txt-muted">
                        <span className="font-medium">
                            {filteredRows.length === 0 ? '0 registros' :
                                `${start + 1}–${Math.min(start + pageSize, filteredRows.length)} de ${filteredRows.length}`}
                            {hasFilters && ` (${detailRows.length} total)`}
                        </span>
                        <div className="flex gap-1">
                            <button
                                onClick={() => setPage(p => p - 1)}
                                disabled={page === 0}
                                className="px-2.5 py-1 rounded-md border border-border hover:bg-surface-alt
                                           disabled:opacity-30 disabled:cursor-not-allowed transition-colors text-txt-secondary"
                            >
                                Anterior
                            </button>
                            <button
                                onClick={() => setPage(p => p + 1)}
                                disabled={page >= totalPages - 1}
                                className="px-2.5 py-1 rounded-md border border-border hover:bg-surface-alt
                                           disabled:opacity-30 disabled:cursor-not-allowed transition-colors text-txt-secondary"
                            >
                                Siguiente
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </>
    );
}
