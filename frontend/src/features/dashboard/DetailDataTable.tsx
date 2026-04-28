import type { CSSProperties } from 'react';
import type { ReportRow } from '@/types';
import { formatNumber } from '@/utils/format';

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
    ASIENTO: '90px',
    RAZON_SOCIAL: '180px',
    FECHA: '100px',
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
}

export default function DetailDataTable({ detailRows, filteredRows, filters, updateFilter, page, setPage, pageSize, setPageSize }: DetailDataTableProps) {
    const totalPages = Math.ceil(filteredRows.length / pageSize);
    const start = page * pageSize;
    const pageRows = filteredRows.slice(start, start + pageSize);
    const hasFilters = Object.values(filters).some(v => v.length > 0);

    return (
        <>
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
                        {pageRows.map((row, idx) => (
                            <tr key={idx} className="rpt-row-data">
                                {DETAIL_COLS.map(col => {
                                    const val = row[col];
                                    const isSaldo = col === 'SALDO';
                                    const isRazon = col === 'RAZON_SOCIAL';
                                    const numVal = isSaldo ? (val as number) : null;
                                    const baseStyle: CSSProperties = isSaldo
                                        ? { textAlign: 'right', fontWeight: 500 }
                                        : { textAlign: 'left' };
                                    if (isRazon) {
                                        baseStyle.overflow = 'hidden';
                                        baseStyle.textOverflow = 'ellipsis';
                                        baseStyle.whiteSpace = 'nowrap';
                                    }
                                    const display = isSaldo ? formatNumber(val as number) : (val ?? '');
                                    return (
                                        <td
                                            key={col}
                                            className={isSaldo && numVal !== null && numVal < 0 ? 'rpt-neg' : ''}
                                            style={baseStyle}
                                            title={isRazon ? String(val ?? '') : undefined}
                                        >
                                            {display}
                                        </td>
                                    );
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Pagination */}
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
                            `${start + 1}\u2013${Math.min(start + pageSize, filteredRows.length)} de ${filteredRows.length}`}
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
        </>
    );
}
