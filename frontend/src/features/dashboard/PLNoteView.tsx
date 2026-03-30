import { useReducer, useRef, useEffect, useMemo, useCallback } from 'react';
import { api } from '@/lib/api';
import { API_CONFIG } from '@/config';
import { useReport } from '@/contexts/ReportContext';
import type { ReportRow, CellSelection, TableConfig, DisplayColumn } from '@/types';
import { formatNumber } from '@/utils/format';
import { exportDetailToExcel } from '@/utils/exportDetailExcel';
import DetailTable from './DetailTable';
import Modal from '@/components/Modal';

const DETAIL_HEADERS: Record<string, string> = {
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

const DETAIL_COLS = Object.keys(DETAIL_HEADERS);
const PAGE_SIZES: number[] = [25, 50, 100];
const DEFAULT_PAGE_SIZE = PAGE_SIZES[0];

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

function DetailDataTable({ detailRows, filteredRows, filters, updateFilter, page, setPage, pageSize, setPageSize }: DetailDataTableProps) {
    const totalPages = Math.ceil(filteredRows.length / pageSize);
    const start = page * pageSize;
    const pageRows = filteredRows.slice(start, start + pageSize);
    const hasFilters = Object.values(filters).some(v => v.length > 0);

    return (
        <>
            <div className="table-card overflow-x-auto">
                <table className="min-w-full text-xs">
                    <thead>
                        <tr className="thead-row">
                            {DETAIL_COLS.map(col => (
                                <th scope="col" key={col} className={`thead-cell text-[11px] font-semibold ${col === 'SALDO' ? 'text-right' : 'text-left'}`}>
                                    {DETAIL_HEADERS[col]}
                                </th>
                            ))}
                        </tr>
                        <tr className="bg-surface border-b border-border">
                            {DETAIL_COLS.map(col => (
                                <th key={col} className="px-2 py-1.5">
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
                            <tr key={idx} className={`row-base ${idx % 2 === 1 ? 'bg-surface-alt/30' : ''}`}>
                                {DETAIL_COLS.map(col => {
                                    const val = row[col];
                                    const isSaldo = col === 'SALDO';
                                    const numVal = isSaldo ? (val as number) : null;
                                    return (
                                        <td
                                            key={col}
                                            className={`px-3.5 py-2 whitespace-nowrap
                                                ${isSaldo ? 'text-right font-mono font-medium' : 'text-left'}
                                                ${isSaldo && numVal !== null && numVal < 0 ? 'cell-neg' :
                                                  isSaldo && numVal === 0 ? 'cell-zero' : 'text-txt-secondary'}`}
                                        >
                                            {isSaldo ? formatNumber(val as number) : (val ?? '')}
                                        </td>
                                    );
                                })}
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Pagination */}
            <div className="flex items-center justify-between mt-3 px-1">
                <div className="flex items-center gap-1.5 text-xs text-txt-muted">
                    <span>Filas:</span>
                    {PAGE_SIZES.map(size => (
                        <button
                            key={size}
                            onClick={() => { setPageSize(size); setPage(() => 0); }}
                            className={`px-2 py-0.5 rounded-md text-xs font-medium transition-colors
                                ${pageSize === size
                                    ? 'bg-accent text-white'
                                    : 'text-txt-muted hover:bg-surface-alt'}`}
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

interface PLNoteViewProps {
    tables: TableConfig[];
    columns: DisplayColumn[];
    year: number;
}

interface DetailState {
    selection: CellSelection | null;
    detailRows: ReportRow[];
    isLoadingDetail: boolean;
    detailError: string | null;
    page: number;
    pageSize: number;
    filters: Record<string, string>;
}

type DetailAction =
    | { type: 'SELECT'; selection: CellSelection }
    | { type: 'CLEAR_SELECTION' }
    | { type: 'LOAD_SUCCESS'; rows: ReportRow[] }
    | { type: 'LOAD_ERROR'; error: string }
    | { type: 'SET_PAGE'; page: number }
    | { type: 'SET_PAGE_SIZE'; size: number }
    | { type: 'SET_FILTER'; col: string; value: string };

const detailInitialState: DetailState = {
    selection: null,
    detailRows: [],
    isLoadingDetail: false,
    detailError: null,
    page: 0,
    pageSize: DEFAULT_PAGE_SIZE,
    filters: {},
};

function detailReducer(state: DetailState, action: DetailAction): DetailState {
    switch (action.type) {
        case 'SELECT':
            return { ...detailInitialState, selection: action.selection, isLoadingDetail: true, pageSize: state.pageSize };
        case 'CLEAR_SELECTION':
            return { ...state, selection: null, detailRows: [] };
        case 'LOAD_SUCCESS':
            return { ...state, isLoadingDetail: false, detailRows: action.rows };
        case 'LOAD_ERROR':
            return { ...state, isLoadingDetail: false, detailRows: [], detailError: action.error };
        case 'SET_PAGE':
            return { ...state, page: action.page };
        case 'SET_PAGE_SIZE':
            return { ...state, pageSize: action.size, page: 0 };
        case 'SET_FILTER':
            return { ...state, filters: { ...state.filters, [action.col]: action.value }, page: 0 };
    }
}


export default function PLNoteView({ tables, columns, year }: PLNoteViewProps) {
    const { selectedCompany, selectedYear, periodRange, trailingMonthSources } = useReport();
    const [state, dispatch] = useReducer(detailReducer, detailInitialState);

    const companyRef = useRef(selectedCompany);
    const yearRef = useRef(selectedYear);
    useEffect(() => { companyRef.current = selectedCompany; }, [selectedCompany]);
    useEffect(() => { yearRef.current = selectedYear; }, [selectedYear]);

    const filteredRows = useMemo(() => {
        const activeFilters = Object.entries(state.filters).filter(([, v]) => v.length > 0);
        if (activeFilters.length === 0) return state.detailRows;
        return state.detailRows.filter(row =>
            activeFilters.every(([col, term]) => {
                const val = String(row[col] ?? '').toLowerCase();
                return val.includes(term.toLowerCase());
            })
        );
    }, [state.detailRows, state.filters]);

    const updateFilter = (col: string, value: string) => {
        dispatch({ type: 'SET_FILTER', col, value });
    };

    const handleCellClick = useCallback(async (sel: CellSelection) => {
        dispatch({ type: 'SELECT', selection: sel });

        try {
            // Parse months from selection (could be "JAN" or "JAN,FEB,MAR" for quarterly)
            const selMonths = sel.month ? sel.month.split(',') : null;

            if (periodRange === 'trailing12' && selMonths) {
                // For trailing 12M, we may need to fetch from two different years
                const monthYearMap = new Map<string, number>();
                for (const src of trailingMonthSources) {
                    monthYearMap.set(src.month, src.year);
                }

                // Group months by year
                const byYear = new Map<number, string[]>();
                for (const m of selMonths) {
                    const y = monthYearMap.get(m) ?? yearRef.current;
                    if (!byYear.has(y)) byYear.set(y, []);
                    byYear.get(y)!.push(m);
                }

                // Fetch from each year and merge
                const allRows: ReportRow[] = [];
                for (const [fetchYear, months] of byYear) {
                    for (const month of months) {
                        const body: Record<string, unknown> = {
                            company: companyRef.current,
                            year: fetchYear,
                            partida: sel.partida,
                            month,
                        };
                        if (sel.filterCol && sel.filterVal != null) {
                            body.filter_col = sel.filterCol;
                            body.filter_val = sel.filterVal;
                        }
                        const resp = await api.post<{ records: ReportRow[] }>(API_CONFIG.ENDPOINTS.DATA_DETAIL, body);
                        allRows.push(...resp.records);
                    }
                }
                dispatch({ type: 'LOAD_SUCCESS', rows: allRows });
            } else if (selMonths && selMonths.length > 1) {
                // Quarterly in YTD mode: fetch each month separately and merge
                const allRows: ReportRow[] = [];
                for (const month of selMonths) {
                    const body: Record<string, unknown> = {
                        company: companyRef.current,
                        year: yearRef.current,
                        partida: sel.partida,
                        month,
                    };
                    if (sel.filterCol && sel.filterVal != null) {
                        body.filter_col = sel.filterCol;
                        body.filter_val = sel.filterVal;
                    }
                    const resp = await api.post<{ records: ReportRow[] }>(API_CONFIG.ENDPOINTS.DATA_DETAIL, body);
                    allRows.push(...resp.records);
                }
                dispatch({ type: 'LOAD_SUCCESS', rows: allRows });
            } else {
                // Single month or full period
                const body: Record<string, unknown> = {
                    company: companyRef.current,
                    year: yearRef.current,
                    partida: sel.partida,
                };
                if (selMonths && selMonths.length === 1) body.month = selMonths[0];
                if (sel.filterCol && sel.filterVal != null) {
                    body.filter_col = sel.filterCol;
                    body.filter_val = sel.filterVal;
                }
                const resp = await api.post<{ records: ReportRow[] }>(API_CONFIG.ENDPOINTS.DATA_DETAIL, body);
                dispatch({ type: 'LOAD_SUCCESS', rows: resp.records });
            }
        } catch (err) {
            dispatch({ type: 'LOAD_ERROR', error: err instanceof Error ? err.message : 'Error al cargar detalle' });
        }
    }, [periodRange, trailingMonthSources]);

    const handleExportDetail = useCallback(() => {
        if (filteredRows.length === 0 || !state.selection) return;
        exportDetailToExcel(filteredRows, state.selection.label, companyRef.current, yearRef.current);
    }, [filteredRows, state.selection]);

    const renderDetailContent = () => {
        if (state.isLoadingDetail) {
            return (
                <div className="flex items-center justify-center py-12">
                    <div className="animate-spin rounded-full h-6 w-6 border-2 border-accent border-t-transparent mr-3"></div>
                    <span className="text-sm text-txt-muted">Cargando detalle...</span>
                </div>
            );
        }
        if (state.detailError) {
            return (
                <div className="text-center py-8">
                    <div className="inline-flex items-center gap-2 text-sm text-negative">
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                        {state.detailError}
                    </div>
                </div>
            );
        }
        if (state.detailRows.length === 0) {
            return <div className="text-center py-8 text-sm text-txt-muted">Sin registros</div>;
        }
        return (
            <DetailDataTable
                detailRows={state.detailRows}
                filteredRows={filteredRows}
                filters={state.filters}
                updateFilter={updateFilter}
                page={state.page}
                setPage={(fn) => dispatch({ type: 'SET_PAGE', page: fn(state.page) })}
                pageSize={state.pageSize}
                setPageSize={(size) => dispatch({ type: 'SET_PAGE_SIZE', size })}
            />
        );
    };

    return (
        <div className="space-y-8">
            {tables.map((table, idx) => (
                <DetailTable
                    key={idx}
                    {...table}
                    columns={columns}
                    year={year}
                    selection={state.selection}
                    onCellClick={handleCellClick}
                />
            ))}

            <Modal
                isOpen={state.selection !== null}
                onClose={() => dispatch({ type: 'CLEAR_SELECTION' })}
                title={`Detalle: ${state.selection?.label ?? ''}`}
                headerActions={
                    <button
                        onClick={handleExportDetail}
                        disabled={filteredRows.length === 0 || state.isLoadingDetail}
                        className="btn-export-green"
                        title="Exportar detalle filtrado a Excel"
                    >
                        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        Excel
                    </button>
                }
            >
                {renderDetailContent()}
            </Modal>
        </div>
    );
}
