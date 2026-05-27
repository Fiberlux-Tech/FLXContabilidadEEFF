import { useReducer, useRef, useEffect, useCallback, useState } from 'react';
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

interface Period {
    year: number;
    month: string;
}

interface DetailQuery {
    selection: CellSelection;
    periods: Period[];
    ic_filter: 'all' | 'ex_ic' | 'only_ic';
}

interface DetailState {
    query: DetailQuery | null;
    detailRows: ReportRow[];
    total: number | null;
    offset: number;
    limit: number;
    isLoadingDetail: boolean;
    detailError: string | null;
    filters: Record<string, string>;
}

type DetailAction =
    | { type: 'SELECT'; query: DetailQuery; limit: number }
    | { type: 'CLEAR_SELECTION' }
    | { type: 'FETCH_START' }
    | { type: 'LOAD_SUCCESS'; rows: ReportRow[]; total: number; offset: number }
    | { type: 'LOAD_ERROR'; error: string }
    | { type: 'SET_OFFSET'; offset: number }
    | { type: 'SET_LIMIT'; limit: number }
    | { type: 'SET_FILTER'; col: string; value: string };

const detailInitialState: DetailState = {
    query: null,
    detailRows: [],
    total: null,
    offset: 0,
    limit: DEFAULT_PAGE_SIZE,
    isLoadingDetail: false,
    detailError: null,
    filters: {},
};

function detailReducer(state: DetailState, action: DetailAction): DetailState {
    switch (action.type) {
        case 'SELECT':
            // Reset everything except the user's preferred page size.
            return {
                ...detailInitialState,
                query: action.query,
                limit: action.limit,
                isLoadingDetail: true,
            };
        case 'CLEAR_SELECTION':
            return { ...detailInitialState, limit: state.limit };
        case 'FETCH_START':
            return { ...state, isLoadingDetail: true, detailError: null };
        case 'LOAD_SUCCESS':
            return {
                ...state,
                isLoadingDetail: false,
                detailError: null,
                detailRows: action.rows,
                total: action.total,
                offset: action.offset,
            };
        case 'LOAD_ERROR':
            return { ...state, isLoadingDetail: false, detailRows: [], total: null, detailError: action.error };
        case 'SET_OFFSET':
            return { ...state, offset: action.offset };
        case 'SET_LIMIT':
            return { ...state, limit: action.limit, offset: 0 };
        case 'SET_FILTER':
            // Mutually exclusive: typing in column A clears column B.
            // Server only supports one filter at a time.
            return action.value
                ? { ...state, filters: { [action.col]: action.value }, offset: 0 }
                : { ...state, filters: {}, offset: 0 };
    }
}


interface DetailResponse {
    records: ReportRow[];
    total: number;
    offset: number;
    limit: number;
}

const FILTER_DEBOUNCE_MS = 300;
const EXPORT_LIMIT = 50_000;


function buildPeriods(
    selMonths: string[] | null,
    trailingMonthSources: { month: string; year: number }[],
    fallbackYear: number,
    isTrailing12: boolean,
): Period[] {
    if (!selMonths || selMonths.length === 0) {
        return [];
    }
    if (isTrailing12) {
        const monthYearMap = new Map<string, number>();
        for (const src of trailingMonthSources) {
            monthYearMap.set(src.month, src.year);
        }
        return selMonths.map(m => ({ month: m, year: monthYearMap.get(m) ?? fallbackYear }));
    }
    return selMonths.map(m => ({ month: m, year: fallbackYear }));
}

function firstActiveFilter(filters: Record<string, string>): { col: string; val: string } | null {
    for (const [col, val] of Object.entries(filters)) {
        if (val.length > 0) return { col, val };
    }
    return null;
}


export default function PLNoteView({ tables, columns, year, showTitles }: PLNoteViewProps) {
    const { selectedCompany, selectedYear, periodRange, trailingMonthSources, intercompanyFilter, currentView } = useReport();
    const [state, dispatch] = useReducer(detailReducer, detailInitialState);
    const [grouped, setGrouped] = useState(false);

    const companyRef = useRef(selectedCompany);
    const yearRef = useRef(selectedYear);
    const viewIdRef = useRef(currentView);
    useEffect(() => { companyRef.current = selectedCompany; }, [selectedCompany]);
    useEffect(() => { yearRef.current = selectedYear; }, [selectedYear]);
    useEffect(() => { viewIdRef.current = currentView; }, [currentView]);

    // Map intercompanyFilter to API ic_filter value ("expanded" → "all" for detail drill-down)
    const icFilterRef = useRef(intercompanyFilter);
    useEffect(() => { icFilterRef.current = intercompanyFilter; }, [intercompanyFilter]);

    // Keep one in-flight detail request at a time; cancel previous on new fire.
    const inflightRef = useRef<AbortController | null>(null);
    const filterTimerRef = useRef<number | null>(null);

    const fetchDetail = useCallback(async (
        query: DetailQuery,
        offset: number,
        limit: number,
        filterPair: { col: string; val: string } | null,
    ) => {
        inflightRef.current?.abort();
        const controller = new AbortController();
        inflightRef.current = controller;
        dispatch({ type: 'FETCH_START' });
        try {
            const body: Record<string, unknown> = {
                company: companyRef.current,
                year: yearRef.current,
                view_id: viewIdRef.current,
                partida: query.selection.partida,
                periods: query.periods,
                offset,
                limit,
            };
            if (query.ic_filter !== 'all') body.ic_filter = query.ic_filter;
            if (filterPair) {
                body.filter_col = filterPair.col;
                body.filter_val = filterPair.val;
            } else if (query.selection.filterCol && query.selection.filterVal != null) {
                // Cell-level filter (when DetailTable passes a column-locked selection)
                body.filter_col = query.selection.filterCol;
                body.filter_val = query.selection.filterVal;
            }
            const resp = await api.post<DetailResponse>(
                API_CONFIG.ENDPOINTS.DATA_DETAIL,
                body,
                { signal: controller.signal },
            );
            if (controller.signal.aborted) return;
            dispatch({ type: 'LOAD_SUCCESS', rows: resp.records, total: resp.total, offset: resp.offset });
        } catch (err) {
            if (controller.signal.aborted || (err instanceof DOMException && err.name === 'AbortError')) {
                return;
            }
            dispatch({
                type: 'LOAD_ERROR',
                error: err instanceof Error ? err.message : 'Error al cargar detalle',
            });
        }
    }, []);

    const handleCellClick = useCallback((sel: CellSelection) => {
        const icApi = icFilterRef.current === 'ex_ic' || icFilterRef.current === 'only_ic'
            ? icFilterRef.current : 'all';
        const selMonths = sel.month ? sel.month.split(',') : null;
        const periods = buildPeriods(
            selMonths, trailingMonthSources, yearRef.current,
            periodRange === 'trailing12',
        );
        const query: DetailQuery = { selection: sel, periods, ic_filter: icApi };
        dispatch({ type: 'SELECT', query, limit: state.limit });
        fetchDetail(query, 0, state.limit, null);
    }, [periodRange, trailingMonthSources, fetchDetail, state.limit]);

    const updateFilter = useCallback((col: string, value: string) => {
        dispatch({ type: 'SET_FILTER', col, value });
        if (filterTimerRef.current !== null) {
            window.clearTimeout(filterTimerRef.current);
        }
        const query = state.query;
        if (!query) return;
        filterTimerRef.current = window.setTimeout(() => {
            const pair = value ? { col, val: value } : null;
            fetchDetail(query, 0, state.limit, pair);
        }, FILTER_DEBOUNCE_MS);
    }, [state.query, state.limit, fetchDetail]);

    const onOffsetChange = useCallback((newOffset: number) => {
        if (!state.query) return;
        const pair = firstActiveFilter(state.filters);
        fetchDetail(state.query, newOffset, state.limit, pair);
    }, [state.query, state.limit, state.filters, fetchDetail]);

    const onLimitChange = useCallback((newLimit: number) => {
        if (!state.query) return;
        dispatch({ type: 'SET_LIMIT', limit: newLimit });
        const pair = firstActiveFilter(state.filters);
        fetchDetail(state.query, 0, newLimit, pair);
    }, [state.query, state.filters, fetchDetail]);

    const handleExportDetail = useCallback(async () => {
        if (!state.query || state.detailRows.length === 0) return;
        // Capture state at click time so the export reflects the visible query.
        const pair = firstActiveFilter(state.filters);
        const body: Record<string, unknown> = {
            company: companyRef.current,
            year: yearRef.current,
            view_id: viewIdRef.current,
            partida: state.query.selection.partida,
            periods: state.query.periods,
            offset: 0,
            limit: EXPORT_LIMIT,
        };
        if (state.query.ic_filter !== 'all') body.ic_filter = state.query.ic_filter;
        if (pair) {
            body.filter_col = pair.col;
            body.filter_val = pair.val;
        } else if (state.query.selection.filterCol && state.query.selection.filterVal != null) {
            body.filter_col = state.query.selection.filterCol;
            body.filter_val = state.query.selection.filterVal;
        }
        try {
            const resp = await api.post<DetailResponse>(API_CONFIG.ENDPOINTS.DATA_DETAIL, body);
            if (resp.total > EXPORT_LIMIT) {
                window.alert(`Export truncado a ${EXPORT_LIMIT.toLocaleString()} filas de ${resp.total.toLocaleString()} totales. Aplica un filtro para reducir el resultado.`);
            }
            exportDetailToExcel(
                resp.records,
                state.query.selection.label,
                companyRef.current,
                yearRef.current,
            );
        } catch (err) {
            dispatch({
                type: 'LOAD_ERROR',
                error: err instanceof Error ? err.message : 'Error al exportar',
            });
        }
    }, [state.query, state.filters, state.detailRows.length]);

    // Clean up debounce timer on unmount / selection change
    useEffect(() => {
        return () => {
            if (filterTimerRef.current !== null) window.clearTimeout(filterTimerRef.current);
            inflightRef.current?.abort();
        };
    }, []);

    const renderDetailContent = () => {
        if (state.isLoadingDetail && state.detailRows.length === 0) {
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
        if (!state.isLoadingDetail && state.detailRows.length === 0) {
            return <div className="text-center py-8 text-sm text-txt-muted">Sin registros</div>;
        }
        const activeFilterCol = firstActiveFilter(state.filters)?.col ?? null;
        return (
            <DetailDataTable
                detailRows={state.detailRows}
                filters={state.filters}
                activeFilterCol={activeFilterCol}
                updateFilter={updateFilter}
                offset={state.offset}
                limit={state.limit}
                total={state.total ?? 0}
                onOffsetChange={onOffsetChange}
                onLimitChange={onLimitChange}
                isLoading={state.isLoadingDetail}
                grouped={grouped}
            />
        );
    };

    const totalForGrouping = state.total ?? 0;
    const groupedDisabled = totalForGrouping > state.limit;

    return (
        <div className="space-y-10">
            {tables.map((table, idx) => (
                <DetailTable
                    key={idx}
                    {...table}
                    columns={columns}
                    year={year}
                    selection={state.query?.selection ?? null}
                    onCellClick={handleCellClick}
                    showTitle={showTitles ?? tables.length > 1}
                />
            ))}

            <Modal
                isOpen={state.query !== null}
                onClose={() => dispatch({ type: 'CLEAR_SELECTION' })}
                title={`Detalle: ${state.query?.selection.label ?? ''}`}
                headerActions={
                    <div className="flex items-center gap-4">
                        <label
                            className={`flex items-center gap-2 text-xs text-txt-secondary select-none ${groupedDisabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
                            title={groupedDisabled ? 'Agrupacion deshabilitada cuando hay mas de una pagina (los subtotales serian incompletos)' : undefined}
                        >
                            <input
                                type="checkbox"
                                checked={grouped && !groupedDisabled}
                                disabled={groupedDisabled}
                                onChange={e => setGrouped(e.target.checked)}
                            />
                            Agrupar por cuenta (2 díg.)
                        </label>
                        <ExportButton
                            variant="excel"
                            onClick={handleExportDetail}
                            disabled={state.detailRows.length === 0 || state.isLoadingDetail}
                        />
                    </div>
                }
            >
                {renderDetailContent()}
            </Modal>
        </div>
    );
}
