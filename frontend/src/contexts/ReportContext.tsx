import { createContext, useContext, useReducer, useCallback, useEffect, useMemo, useRef } from 'react';
import { api } from '@/lib/api';
import { API_CONFIG } from '@/config';
import type { ReportData, PLReportData, PLSectionData, BSReportData, CompanyMap, Granularity, PeriodRange, DisplayColumn, MonthSource, ReportRow } from '@/types';
import { isBsView, isAnalysisView } from '@/config/viewRegistry';
import type { View } from '@/config/viewRegistry';
import { getTrailing12MonthSources, buildDisplayColumns } from '@/utils/displayColumns';
import { mergeTrailingRows, mergeTrailingDetailRows, mergeTrailingBSRows } from '@/utils/mergeTrailing';
import { buildExpandedPLRows } from '@/utils/expandedPL';

export type { View };
export { isBsView, isAnalysisView };

const DEFAULT_COMPANY = 'NEXTNET';

/** Map P&L detail views to their backend section name for lazy loading. */
const VIEW_TO_SECTION: Partial<Record<View, string>> = {
    ingresos: 'ingresos',
    costo: 'costo',
    gasto_venta: 'gasto_venta',
    gasto_admin: 'gasto_admin',
    otros_egresos: 'otros_egresos',
    dya: 'dya',
    resultado_financiero: 'resultado_financiero',
    analysis_pl_finanzas: 'analysis_pl_finanzas',
    analysis_planilla: 'analysis_planilla',
    analysis_proveedores: 'analysis_proveedores',
    analysis_flujo_caja: 'analysis_flujo_caja',
};

interface ReportState {
    companies: CompanyMap;
    companiesError: string | null;
    selectedCompany: string;
    selectedYear: number;
    granularity: Granularity;
    periodRange: PeriodRange;
    reportData: ReportData | null;
    /** For trailing 12M: the previous year's data */
    prevYearData: ReportData | null;
    currentView: View;
    isLoading: boolean;
    error: string | null;
    isExporting: boolean;
    /** Whether BS data is being fetched separately */
    isBsLoading: boolean;
    bsError: string | null;
    /** Intercompany filter: 'all' = no filter, 'only_ic' = only intercompany, 'ex_ic' = exclude intercompany, 'expanded' = show IC as separate rows */
    intercompanyFilter: 'all' | 'only_ic' | 'ex_ic' | 'expanded';
    /** Track which P&L detail sections have been loaded */
    loadedSections: Set<string>;
    /** Selected CECO for Analisis de Proveedores */
    proveedoresCeco: string;
    /** Whether a section is currently being fetched */
    isSectionLoading: boolean;
    sectionError: string | null;
}

type ReportAction =
    | { type: 'SET_COMPANIES'; companies: CompanyMap; defaultCompany: string }
    | { type: 'SET_COMPANIES_ERROR'; error: string }
    | { type: 'SET_COMPANY'; company: string }
    | { type: 'SET_YEAR'; year: number }
    | { type: 'SET_GRANULARITY'; granularity: Granularity }
    | { type: 'SET_PERIOD_RANGE'; periodRange: PeriodRange }
    | { type: 'SET_VIEW'; view: View }
    | { type: 'SET_INTERCOMPANY_FILTER'; filter: 'all' | 'only_ic' | 'ex_ic' | 'expanded' }
    | { type: 'LOAD_START' }
    | { type: 'LOAD_PL_SUCCESS'; data: PLReportData; prevYearData: PLReportData | null }
    | { type: 'LOAD_ERROR'; error: string }
    | { type: 'BS_LOAD_START' }
    | { type: 'BS_LOAD_SUCCESS'; data: BSReportData; prevYearData: BSReportData | null }
    | { type: 'BS_LOAD_ERROR'; error: string }
    | { type: 'EXPORT_START' }
    | { type: 'EXPORT_SUCCESS' }
    | { type: 'EXPORT_ERROR'; error: string }
    | { type: 'SECTION_LOAD_START' }
    | { type: 'SECTION_LOAD_SUCCESS'; section: string; data: PLSectionData; prevData: PLSectionData | null }
    | { type: 'SECTION_LOAD_ERROR'; error: string }
    | { type: 'SET_PROVEEDORES_CECO'; ceco: string };

const initialState: ReportState = {
    companies: {},
    companiesError: null,
    selectedCompany: '',
    selectedYear: new Date().getFullYear(),
    granularity: 'monthly',
    periodRange: 'ytd',
    reportData: null,
    prevYearData: null,
    currentView: 'pl',
    isLoading: false,
    error: null,
    isExporting: false,
    isBsLoading: false,
    bsError: null,
    intercompanyFilter: 'all',
    loadedSections: new Set<string>(),
    isSectionLoading: false,
    sectionError: null,
    proveedoresCeco: '100.113.01',
};

function reportReducer(state: ReportState, action: ReportAction): ReportState {
    switch (action.type) {
        case 'SET_COMPANIES':
            return { ...state, companies: action.companies, selectedCompany: action.defaultCompany };
        case 'SET_COMPANIES_ERROR':
            return { ...state, companiesError: action.error };
        case 'SET_COMPANY':
            return { ...state, selectedCompany: action.company };
        case 'SET_YEAR':
            return { ...state, selectedYear: action.year };
        case 'SET_GRANULARITY':
            return { ...state, granularity: action.granularity };
        case 'SET_PERIOD_RANGE':
            return { ...state, periodRange: action.periodRange };
        case 'SET_VIEW':
            return { ...state, currentView: action.view };
        case 'SET_INTERCOMPANY_FILTER':
            return { ...state, intercompanyFilter: action.filter };
        case 'LOAD_START':
            return { ...state, isLoading: true, error: null, bsError: null, sectionError: null };
        case 'LOAD_PL_SUCCESS':
            // Merge new summary into existing reportData to preserve loaded sections/BS,
            // but only if company+year match (otherwise start fresh).
            {
                const sameContext = state.reportData
                    && state.reportData.company === action.data.company
                    && state.reportData.year === action.data.year;
                const base = sameContext ? state.reportData : { bs_summary: [] as ReportRow[] };
                const prevBase = sameContext ? state.prevYearData : null;
                // Reset sections when company/year changed, OR when trailing12
                // toggled (sections need prev-year data that wasn't fetched before).
                const hadPrevData = !!state.prevYearData;
                const hasPrevData = !!action.prevYearData;
                const periodChanged = hadPrevData !== hasPrevData;
                const keepSections = sameContext && !periodChanged;
                return {
                    ...state, isLoading: false,
                    reportData: { ...base, ...action.data } as ReportData,
                    prevYearData: action.prevYearData
                        ? { ...(prevBase ?? {}), ...action.prevYearData, bs_summary: prevBase?.bs_summary ?? [] } as ReportData
                        : prevBase,
                    loadedSections: keepSections ? state.loadedSections : new Set<string>(),
                };
            }
        case 'LOAD_ERROR':
            return { ...state, isLoading: false, error: action.error, reportData: null, prevYearData: null };
        case 'BS_LOAD_START':
            return { ...state, isBsLoading: true, bsError: null };
        case 'BS_LOAD_SUCCESS': {
            // Merge all BS fields (summary + note details) into reportData
            const { company: _c, year: _y, months: _m, ...bsFields } = action.data;
            const prevBsFields = action.prevYearData
                ? (() => { const { company: _c2, year: _y2, months: _m2, ...rest } = action.prevYearData; return rest; })()
                : null;
            return {
                ...state, isBsLoading: false,
                reportData: state.reportData
                    ? { ...state.reportData, ...bsFields }
                    : null,
                prevYearData: prevBsFields && state.prevYearData
                    ? { ...state.prevYearData, ...prevBsFields }
                    : state.prevYearData,
            };
        }
        case 'BS_LOAD_ERROR':
            return { ...state, isBsLoading: false, bsError: action.error };
        case 'EXPORT_START':
            return { ...state, isExporting: true, error: null };
        case 'EXPORT_SUCCESS':
            return { ...state, isExporting: false };
        case 'EXPORT_ERROR':
            return { ...state, isExporting: false, error: action.error };
        case 'SECTION_LOAD_START':
            return { ...state, isSectionLoading: true, sectionError: null };
        case 'SECTION_LOAD_SUCCESS': {
            // Only merge section data if we still have reportData (guard against stale responses)
            if (!state.reportData) return { ...state, isSectionLoading: false };
            const newSections = new Set(state.loadedSections);
            newSections.add(action.section);
            return {
                ...state,
                isSectionLoading: false,
                loadedSections: newSections,
                reportData: { ...state.reportData, ...action.data },
                prevYearData: action.prevData && state.prevYearData
                    ? { ...state.prevYearData, ...action.prevData }
                    : state.prevYearData,
            };
        }
        case 'SECTION_LOAD_ERROR':
            return { ...state, isSectionLoading: false, sectionError: action.error };
        case 'SET_PROVEEDORES_CECO': {
            // Remove the proveedores section from loaded so it refetches with the new ceco
            const sections = new Set(state.loadedSections);
            sections.delete('analysis_proveedores');
            return { ...state, proveedoresCeco: action.ceco, loadedSections: sections };
        }
    }
}

// ─── Context interface ─────────────────────────────────────────

interface IReportContext {
    companies: CompanyMap;
    selectedCompany: string;
    setSelectedCompany: (c: string) => void;
    selectedYear: number;
    setSelectedYear: (y: number) => void;
    granularity: Granularity;
    setGranularity: (g: Granularity) => void;
    periodRange: PeriodRange;
    setPeriodRange: (r: PeriodRange) => void;
    intercompanyFilter: 'all' | 'only_ic' | 'ex_ic' | 'expanded';
    setIntercompanyFilter: (v: 'all' | 'only_ic' | 'ex_ic' | 'expanded') => void;
    reportData: ReportData | null;
    prevYearData: ReportData | null;
    currentView: View;
    setCurrentView: (v: View) => void;
    isLoading: boolean;
    error: string | null;
    companiesError: string | null;
    loadData: (force?: boolean) => Promise<void>;
    exportFile: (type: 'excel' | 'pdf' | 'all') => Promise<void>;
    isExporting: boolean;
    isBsLoading: boolean;
    bsError: string | null;
    /** Whether a P&L detail section is currently loading */
    isSectionLoading: boolean;
    sectionError: string | null;
    /** Which P&L detail sections have been loaded */
    loadedSections: Set<string>;
    /** Computed display columns for current granularity/range/variant */
    getDisplayColumns: (variant: 'pl' | 'bs') => DisplayColumn[];
    /** Selected CECO for Analisis de Proveedores */
    proveedoresCeco: string;
    setProveedoresCeco: (ceco: string) => void;
    /** Trailing 12M month sources (for drill-down year resolution) */
    trailingMonthSources: MonthSource[];
    /** Get merged rows for trailing 12M mode */
    getMergedRows: (key: keyof ReportData, labelKey: string, variant: 'pl' | 'bs') => ReportRow[];
    getMergedDetailRows: (key: keyof ReportData, labelKeys: string[]) => ReportRow[];
}

const ReportContext = createContext<IReportContext | null>(null);

export function ReportProvider({ children }: { children: React.ReactNode }) {
    const [state, dispatch] = useReducer(reportReducer, initialState);

    // Load companies on mount, default to NEXTNET
    useEffect(() => {
        api.get<CompanyMap>(API_CONFIG.ENDPOINTS.COMPANIES).then(data => {
            const keys = Object.keys(data);
            const defaultCompany = keys.includes(DEFAULT_COMPANY) ? DEFAULT_COMPANY : (keys[0] ?? '');
            dispatch({ type: 'SET_COMPANIES', companies: data, defaultCompany });
        }).catch((err) => {
            console.error(err);
            dispatch({ type: 'SET_COMPANIES_ERROR', error: 'No se pudieron cargar las empresas. Verifique su conexion.' });
        });
    }, []);

    // ─── BS fetch (separate, on-demand) ────────────────────────
    const bsAbortRef = useRef<AbortController | null>(null);

    const fetchBsData = useCallback(async (force = false, signal?: AbortSignal) => {
        if (!state.selectedCompany) return;
        dispatch({ type: 'BS_LOAD_START' });
        try {
            const bsPromise = api.post<BSReportData>(API_CONFIG.ENDPOINTS.DATA_LOAD_BS, {
                company: state.selectedCompany,
                year: state.selectedYear,
                force_refresh: force,
            }, { signal });

            let prevBsPromise: Promise<BSReportData> | null = null;
            if (state.periodRange === 'trailing12') {
                prevBsPromise = api.post<BSReportData>(API_CONFIG.ENDPOINTS.DATA_LOAD_BS, {
                    company: state.selectedCompany,
                    year: state.selectedYear - 1,
                    force_refresh: force,
                }, { signal });
            }

            const [bsData, prevBsData] = await Promise.all([bsPromise, prevBsPromise]);
            dispatch({ type: 'BS_LOAD_SUCCESS', data: bsData, prevYearData: prevBsData });
        } catch (err: unknown) {
            if (err instanceof DOMException && err.name === 'AbortError') return;
            dispatch({ type: 'BS_LOAD_ERROR', error: err instanceof Error ? err.message : 'Error al cargar Balance General' });
        }
    }, [state.selectedCompany, state.selectedYear, state.periodRange]);

    // ─── P&L fetch (primary, fast path) ──────────────────────
    const loadData = useCallback(async (force = false, signal?: AbortSignal) => {
        if (!state.selectedCompany) return;
        // Abort any in-flight section request before resetting state
        if (sectionAbortRef.current) { sectionAbortRef.current.abort(); sectionAbortRef.current = null; }
        dispatch({ type: 'LOAD_START' });
        try {
            const plPromise = api.post<PLReportData>(API_CONFIG.ENDPOINTS.DATA_LOAD_PL, {
                company: state.selectedCompany,
                year: state.selectedYear,
                force_refresh: force,
            }, { signal });

            let prevPlPromise: Promise<PLReportData> | null = null;
            if (state.periodRange === 'trailing12') {
                prevPlPromise = api.post<PLReportData>(API_CONFIG.ENDPOINTS.DATA_LOAD_PL, {
                    company: state.selectedCompany,
                    year: state.selectedYear - 1,
                    force_refresh: force,
                }, { signal });
            }

            const [plData, prevPlData] = await Promise.all([plPromise, prevPlPromise]);
            dispatch({ type: 'LOAD_PL_SUCCESS', data: plData, prevYearData: prevPlData });
        } catch (err: unknown) {
            if (err instanceof DOMException && err.name === 'AbortError') return;
            dispatch({ type: 'LOAD_ERROR', error: err instanceof Error ? err.message : 'Error al cargar datos' });
        }
    }, [state.selectedCompany, state.selectedYear, state.periodRange]);

    // Auto-load P&L when company, year, or periodRange changes (debounced + cancellable)
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const abortRef = useRef<AbortController | null>(null);

    useEffect(() => {
        if (!state.selectedCompany || Object.keys(state.companies).length === 0) return;

        if (debounceRef.current) clearTimeout(debounceRef.current);
        if (abortRef.current) abortRef.current.abort();
        if (bsAbortRef.current) bsAbortRef.current.abort();

        debounceRef.current = setTimeout(() => {
            const controller = new AbortController();
            abortRef.current = controller;
            loadData(false, controller.signal);
        }, 300);

        return () => {
            if (debounceRef.current) clearTimeout(debounceRef.current);
            if (abortRef.current) abortRef.current.abort();
            if (bsAbortRef.current) bsAbortRef.current.abort();
        };
    }, [state.selectedCompany, state.companies, loadData]);

    // Trigger BS fetch when user switches to any BS view and BS data isn't loaded yet
    useEffect(() => {
        if (
            isBsView(state.currentView) &&
            state.reportData &&
            state.reportData.bs_summary.length === 0 &&
            !state.isBsLoading &&
            !state.bsError
        ) {
            if (bsAbortRef.current) bsAbortRef.current.abort();
            const controller = new AbortController();
            bsAbortRef.current = controller;
            fetchBsData(false, controller.signal);
        }
    }, [state.currentView, state.reportData, state.isBsLoading, state.bsError, fetchBsData]);

    // ─── P&L section fetch (on-demand detail loading) ──────────
    // Use refs for values needed inside the fetch to avoid recreating the
    // callback (which would cause the effect to re-fire and abort itself).
    const sectionAbortRef = useRef<AbortController | null>(null);
    const companyRef = useRef(state.selectedCompany);
    const yearRef = useRef(state.selectedYear);
    const periodRef = useRef(state.periodRange);
    companyRef.current = state.selectedCompany;
    yearRef.current = state.selectedYear;
    periodRef.current = state.periodRange;
    const proveedoresCecoRef = useRef(state.proveedoresCeco);
    proveedoresCecoRef.current = state.proveedoresCeco;

    const fetchSection = useCallback(async (section: string) => {
        const company = companyRef.current;
        const year = yearRef.current;
        const period = periodRef.current;
        if (!company) return;

        // Abort any previous section request (allows switching sections mid-flight)
        if (sectionAbortRef.current) sectionAbortRef.current.abort();
        const controller = new AbortController();
        sectionAbortRef.current = controller;

        // Build extra params for specific sections
        const extra: Record<string, string> = {};
        if (section === 'analysis_proveedores') {
            extra.ceco = proveedoresCecoRef.current;
        }

        dispatch({ type: 'SECTION_LOAD_START' });
        try {
            const dataPromise = api.post<PLSectionData>(API_CONFIG.ENDPOINTS.DATA_LOAD_PL_SECTION, {
                company, year, section, ...extra,
            }, { signal: controller.signal });

            let prevDataPromise: Promise<PLSectionData> | null = null;
            if (period === 'trailing12') {
                prevDataPromise = api.post<PLSectionData>(API_CONFIG.ENDPOINTS.DATA_LOAD_PL_SECTION, {
                    company, year: year - 1, section, ...extra,
                }, { signal: controller.signal });
            }

            const [data, prevData] = await Promise.all([dataPromise, prevDataPromise]);
            if (controller.signal.aborted) return; // double-check after await
            dispatch({ type: 'SECTION_LOAD_SUCCESS', section, data, prevData });
        } catch (err: unknown) {
            if (err instanceof DOMException && err.name === 'AbortError') return;
            dispatch({ type: 'SECTION_LOAD_ERROR', error: err instanceof Error ? err.message : 'Error al cargar seccion' });
        }
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);

    // Trigger section fetch when user navigates to a P&L detail view
    // Also refetch proveedores when the selected CECO changes
    useEffect(() => {
        const section = VIEW_TO_SECTION[state.currentView];
        if (
            section &&
            state.reportData &&
            !state.loadedSections.has(section)
        ) {
            fetchSection(section);
        }
    }, [state.currentView, state.reportData, state.loadedSections, state.proveedoresCeco, fetchSection]);

    const exportFile = useCallback(async (type: 'excel' | 'pdf' | 'all') => {
        if (!state.selectedCompany) return;
        dispatch({ type: 'EXPORT_START' });

        const endpointMap = {
            excel: API_CONFIG.ENDPOINTS.EXPORT_EXCEL,
            pdf: API_CONFIG.ENDPOINTS.EXPORT_PDF,
            all: API_CONFIG.ENDPOINTS.EXPORT_ALL,
        };

        try {
            const result = await api.post<Record<string, string>>(endpointMap[type], {
                company: state.selectedCompany,
                year: state.selectedYear,
            });

            for (const [key, filename] of Object.entries(result)) {
                if (typeof filename !== 'string' || !filename.trim()) {
                    console.warn(`Skipping invalid export filename for key "${key}"`);
                    continue;
                }
                if (filename.includes('/') || filename.includes('\\')) {
                    console.warn(`Skipping suspicious filename: ${filename}`);
                    continue;
                }
                const url = `${API_CONFIG.ENDPOINTS.EXPORT_DOWNLOAD}/${encodeURIComponent(filename)}`;
                window.open(url, '_blank');
            }
            dispatch({ type: 'EXPORT_SUCCESS' });
        } catch (err: unknown) {
            dispatch({ type: 'EXPORT_ERROR', error: err instanceof Error ? err.message : 'Error al exportar' });
        }
    }, [state.selectedCompany, state.selectedYear]);

    const trailingMonthSources = useMemo(
        () => getTrailing12MonthSources(state.selectedYear),
        [state.selectedYear],
    );

    const getDisplayColumns = useCallback(
        (variant: 'pl' | 'bs') => buildDisplayColumns(state.granularity, state.periodRange, state.selectedYear, variant),
        [state.granularity, state.periodRange, state.selectedYear],
    );

    const getMergedRows = useCallback(
        (key: keyof ReportData, labelKey: string, variant: 'pl' | 'bs'): ReportRow[] => {
            if (!state.reportData) return [];

            // Expanded IC mode: build interleaved rows from all three variants
            if (key === 'pl_summary' && state.intercompanyFilter === 'expanded') {
                const allRows = (state.reportData['pl_summary'] as ReportRow[] | undefined) ?? [];
                const exIcRows = (state.reportData['pl_summary_ex_ic'] as ReportRow[] | undefined) ?? [];
                const onlyIcRows = (state.reportData['pl_summary_only_ic'] as ReportRow[] | undefined) ?? [];
                const expanded = buildExpandedPLRows(allRows, exIcRows, onlyIcRows);
                if (state.periodRange === 'ytd') return expanded;
                const prevAll = (state.prevYearData?.['pl_summary'] as ReportRow[] | undefined) ?? [];
                const prevExIc = (state.prevYearData?.['pl_summary_ex_ic'] as ReportRow[] | undefined) ?? [];
                const prevOnlyIc = (state.prevYearData?.['pl_summary_only_ic'] as ReportRow[] | undefined) ?? [];
                const prevExpanded = buildExpandedPLRows(prevAll, prevExIc, prevOnlyIc);
                return mergeTrailingRows(expanded, prevExpanded, labelKey, trailingMonthSources, state.selectedYear);
            }

            // When intercompany filter is active, swap pl_summary for the filtered variant
            let effectiveKey = key;
            if (key === 'pl_summary' && state.intercompanyFilter === 'ex_ic') effectiveKey = 'pl_summary_ex_ic';
            if (key === 'pl_summary' && state.intercompanyFilter === 'only_ic') effectiveKey = 'pl_summary_only_ic';
            const currentRows = (state.reportData[effectiveKey] as ReportRow[] | undefined) ?? [];
            if (state.periodRange === 'ytd') return currentRows;
            const prevRows = (state.prevYearData?.[effectiveKey] as ReportRow[] | undefined) ?? [];
            if (variant === 'bs') {
                return mergeTrailingBSRows(currentRows, prevRows, labelKey, trailingMonthSources, state.selectedYear);
            }
            return mergeTrailingRows(currentRows, prevRows, labelKey, trailingMonthSources, state.selectedYear);
        },
        [state.reportData, state.prevYearData, state.periodRange, trailingMonthSources, state.selectedYear, state.intercompanyFilter],
    );

    const getMergedDetailRows = useCallback(
        (key: keyof ReportData, labelKeys: string[]): ReportRow[] => {
            if (!state.reportData) return [];

            // Apply IC filter: swap key suffix for ex_ic / only_ic.
            // "expanded" falls back to "all" (no suffix) in detail views.
            let effectiveKey = key;
            if (state.intercompanyFilter === 'ex_ic') {
                const icKey = `${String(key)}_ex_ic` as keyof ReportData;
                if (icKey in state.reportData) effectiveKey = icKey;
            } else if (state.intercompanyFilter === 'only_ic') {
                const icKey = `${String(key)}_only_ic` as keyof ReportData;
                if (icKey in state.reportData) effectiveKey = icKey;
            }

            const currentRows = (state.reportData[effectiveKey] as ReportRow[] | undefined) ?? [];
            if (state.periodRange === 'ytd') return currentRows;
            const prevRows = (state.prevYearData?.[effectiveKey] as ReportRow[] | undefined) ?? [];
            return mergeTrailingDetailRows(currentRows, prevRows, labelKeys, trailingMonthSources, state.selectedYear);
        },
        [state.reportData, state.prevYearData, state.periodRange, trailingMonthSources, state.selectedYear, state.intercompanyFilter],
    );

    return (
        <ReportContext.Provider value={{
            companies: state.companies,
            selectedCompany: state.selectedCompany,
            setSelectedCompany: (c) => dispatch({ type: 'SET_COMPANY', company: c }),
            selectedYear: state.selectedYear,
            setSelectedYear: (y) => dispatch({ type: 'SET_YEAR', year: y }),
            granularity: state.granularity,
            setGranularity: (g) => dispatch({ type: 'SET_GRANULARITY', granularity: g }),
            periodRange: state.periodRange,
            setPeriodRange: (r) => dispatch({ type: 'SET_PERIOD_RANGE', periodRange: r }),
            intercompanyFilter: state.intercompanyFilter,
            setIntercompanyFilter: (v) => dispatch({ type: 'SET_INTERCOMPANY_FILTER', filter: v }),
            proveedoresCeco: state.proveedoresCeco,
            setProveedoresCeco: (ceco) => dispatch({ type: 'SET_PROVEEDORES_CECO', ceco }),
            reportData: state.reportData,
            prevYearData: state.prevYearData,
            currentView: state.currentView,
            setCurrentView: (v) => dispatch({ type: 'SET_VIEW', view: v }),
            isLoading: state.isLoading,
            error: state.error,
            companiesError: state.companiesError,
            loadData, exportFile,
            isExporting: state.isExporting,
            isBsLoading: state.isBsLoading,
            bsError: state.bsError,
            isSectionLoading: state.isSectionLoading,
            sectionError: state.sectionError,
            loadedSections: state.loadedSections,
            getDisplayColumns,
            trailingMonthSources,
            getMergedRows,
            getMergedDetailRows,
        }}>
            {children}
        </ReportContext.Provider>
    );
}

export const useReport = (): IReportContext => {
    const context = useContext(ReportContext);
    if (!context) {
        throw new Error('useReport must be used within a ReportProvider');
    }
    return context;
};
