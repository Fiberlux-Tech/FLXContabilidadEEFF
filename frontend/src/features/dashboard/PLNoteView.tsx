import { useReducer, useRef, useEffect, useMemo, useCallback } from 'react';
import { api } from '@/lib/api';
import { API_CONFIG } from '@/config';
import { useReport } from '@/contexts/ReportContext';
import type { ReportRow, CellSelection, TableConfig, DisplayColumn } from '@/types';
import { exportDetailToExcel } from '@/utils/exportDetailExcel';
import DetailDataTable, { DEFAULT_PAGE_SIZE } from './DetailDataTable';
import DetailTable from './DetailTable';
import Modal from '@/components/Modal';
import ExportButton from '@/components/ExportButton';

interface PLNoteViewProps {
    tables: TableConfig[];
    columns: DisplayColumn[];
    year: number;
    showTitles?: boolean;
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


export default function PLNoteView({ tables, columns, year, showTitles }: PLNoteViewProps) {
    const { selectedCompany, selectedYear, periodRange, trailingMonthSources, intercompanyFilter, currentView } = useReport();
    const [state, dispatch] = useReducer(detailReducer, detailInitialState);

    const companyRef = useRef(selectedCompany);
    const yearRef = useRef(selectedYear);
    const viewIdRef = useRef(currentView);
    useEffect(() => { companyRef.current = selectedCompany; }, [selectedCompany]);
    useEffect(() => { yearRef.current = selectedYear; }, [selectedYear]);
    useEffect(() => { viewIdRef.current = currentView; }, [currentView]);

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

    // Map intercompanyFilter to API ic_filter value ("expanded" → "all" for detail drill-down)
    const icFilterRef = useRef(intercompanyFilter);
    useEffect(() => { icFilterRef.current = intercompanyFilter; }, [intercompanyFilter]);

    const handleCellClick = useCallback(async (sel: CellSelection) => {
        dispatch({ type: 'SELECT', selection: sel });

        // Resolve ic_filter: "expanded" falls back to "all" in detail views
        const icApi = icFilterRef.current === 'ex_ic' || icFilterRef.current === 'only_ic'
            ? icFilterRef.current : 'all';

        const buildBody = (yr: number, month?: string): Record<string, unknown> => {
            const body: Record<string, unknown> = {
                company: companyRef.current,
                year: yr,
                view_id: viewIdRef.current,
                partida: sel.partida,
            };
            if (month) body.month = month;
            if (sel.filterCol && sel.filterVal != null) {
                body.filter_col = sel.filterCol;
                body.filter_val = sel.filterVal;
            }
            if (icApi !== 'all') body.ic_filter = icApi;
            return body;
        };

        try {
            const selMonths = sel.month ? sel.month.split(',') : null;

            if (periodRange === 'trailing12' && selMonths) {
                const monthYearMap = new Map<string, number>();
                for (const src of trailingMonthSources) {
                    monthYearMap.set(src.month, src.year);
                }

                const byYear = new Map<number, string[]>();
                for (const m of selMonths) {
                    const y = monthYearMap.get(m) ?? yearRef.current;
                    if (!byYear.has(y)) byYear.set(y, []);
                    byYear.get(y)!.push(m);
                }

                const allRows: ReportRow[] = [];
                for (const [fetchYear, months] of byYear) {
                    for (const month of months) {
                        const resp = await api.post<{ records: ReportRow[] }>(API_CONFIG.ENDPOINTS.DATA_DETAIL, buildBody(fetchYear, month));
                        allRows.push(...resp.records);
                    }
                }
                dispatch({ type: 'LOAD_SUCCESS', rows: allRows });
            } else if (selMonths && selMonths.length > 1) {
                const allRows: ReportRow[] = [];
                for (const month of selMonths) {
                    const resp = await api.post<{ records: ReportRow[] }>(API_CONFIG.ENDPOINTS.DATA_DETAIL, buildBody(yearRef.current, month));
                    allRows.push(...resp.records);
                }
                dispatch({ type: 'LOAD_SUCCESS', rows: allRows });
            } else {
                const resp = await api.post<{ records: ReportRow[] }>(
                    API_CONFIG.ENDPOINTS.DATA_DETAIL,
                    buildBody(yearRef.current, selMonths?.[0]),
                );
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
        <div className="space-y-10">
            {tables.map((table, idx) => (
                <DetailTable
                    key={idx}
                    {...table}
                    columns={columns}
                    year={year}
                    selection={state.selection}
                    onCellClick={handleCellClick}
                    showTitle={showTitles ?? tables.length > 1}
                />
            ))}

            <Modal
                isOpen={state.selection !== null}
                onClose={() => dispatch({ type: 'CLEAR_SELECTION' })}
                title={`Detalle: ${state.selection?.label ?? ''}`}
                headerActions={
                    <ExportButton
                        variant="excel"
                        onClick={handleExportDetail}
                        disabled={filteredRows.length === 0 || state.isLoadingDetail}
                    />
                }
            >
                {renderDetailContent()}
            </Modal>
        </div>
    );
}
