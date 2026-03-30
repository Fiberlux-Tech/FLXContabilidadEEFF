import { createContext, useContext, useReducer, useCallback, useEffect, useMemo, useRef } from 'react';
import { api } from '@/lib/api';
import { API_CONFIG } from '@/config';
import type { ReportData, CompanyMap, Granularity, PeriodRange, DisplayColumn, MonthSource, ReportRow } from '@/types';

export type View = 'pl' | 'bs' | 'ingresos' | 'costo' | 'gasto_venta' | 'gasto_admin' | 'dya' | 'resultado_financiero';

const ALL_MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'] as const;
const QUARTER_MONTHS: [string, string, string][] = [
    ['JAN', 'FEB', 'MAR'],
    ['APR', 'MAY', 'JUN'],
    ['JUL', 'AUG', 'SEP'],
    ['OCT', 'NOV', 'DEC'],
];
const QUARTER_LABELS = ['Q1', 'Q2', 'Q3', 'Q4'];
const DEFAULT_COMPANY = 'NEXTNET';

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
}

type ReportAction =
    | { type: 'SET_COMPANIES'; companies: CompanyMap; defaultCompany: string }
    | { type: 'SET_COMPANIES_ERROR'; error: string }
    | { type: 'SET_COMPANY'; company: string }
    | { type: 'SET_YEAR'; year: number }
    | { type: 'SET_GRANULARITY'; granularity: Granularity }
    | { type: 'SET_PERIOD_RANGE'; periodRange: PeriodRange }
    | { type: 'SET_VIEW'; view: View }
    | { type: 'LOAD_START' }
    | { type: 'LOAD_SUCCESS'; data: ReportData; prevYearData: ReportData | null }
    | { type: 'LOAD_ERROR'; error: string }
    | { type: 'EXPORT_START' }
    | { type: 'EXPORT_SUCCESS' }
    | { type: 'EXPORT_ERROR'; error: string };

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
        case 'LOAD_START':
            return { ...state, isLoading: true, error: null };
        case 'LOAD_SUCCESS':
            return { ...state, isLoading: false, reportData: action.data, prevYearData: action.prevYearData };
        case 'LOAD_ERROR':
            return { ...state, isLoading: false, error: action.error, reportData: null, prevYearData: null };
        case 'EXPORT_START':
            return { ...state, isExporting: true, error: null };
        case 'EXPORT_SUCCESS':
            return { ...state, isExporting: false };
        case 'EXPORT_ERROR':
            return { ...state, isExporting: false, error: action.error };
    }
}

// ─── Column computation helpers ────────────────────────────────

function getTrailing12MonthSources(currentYear: number): MonthSource[] {
    const now = new Date();
    // Use current calendar month as the end of trailing window
    const endMonth = now.getFullYear() === currentYear ? now.getMonth() : 11; // 0-indexed
    const sources: MonthSource[] = [];
    for (let i = 11; i >= 0; i--) {
        const monthIdx = (endMonth - i + 12) % 12;
        const year = (endMonth - i < 0) ? currentYear - 1 : currentYear;
        sources.push({ month: ALL_MONTHS[monthIdx], year });
    }
    return sources;
}

function buildDisplayColumns(
    granularity: Granularity,
    periodRange: PeriodRange,
    selectedYear: number,
    variant: 'pl' | 'bs',
): DisplayColumn[] {
    if (periodRange === 'ytd') {
        // Current year: all 12 months
        if (granularity === 'monthly') {
            return ALL_MONTHS.map(m => ({
                header: m,
                sourceMonths: [m],
            }));
        }
        // Quarterly YTD
        return QUARTER_MONTHS.map((months, qi) => ({
            header: `${QUARTER_LABELS[qi]} ${selectedYear}`,
            sourceMonths: months,
            useLastOnly: variant === 'bs',
        }));
    }

    // Trailing 12M
    const sources = getTrailing12MonthSources(selectedYear);

    if (granularity === 'monthly') {
        return sources.map(s => ({
            header: `${s.month}-${String(s.year).slice(2)}`,
            sourceMonths: [s.month],
        }));
    }

    // Quarterly trailing 12M: group the 12 sources into 4 quarters
    const cols: DisplayColumn[] = [];
    for (let q = 0; q < 4; q++) {
        const qSources = sources.slice(q * 3, q * 3 + 3);
        const lastSource = qSources[qSources.length - 1];
        const lastMonthIdx = ALL_MONTHS.indexOf(lastSource.month);
        const qi = Math.floor(lastMonthIdx / 3);
        cols.push({
            header: `${QUARTER_LABELS[qi]} ${lastSource.year}`,
            sourceMonths: qSources.map(s => s.month),
            useLastOnly: variant === 'bs',
        });
    }
    return cols;
}

// ─── Data merge helpers for trailing 12M ───────────────────────

function mergeTrailingRows(
    currentRows: ReportRow[],
    prevRows: ReportRow[],
    labelKey: string,
    monthSources: MonthSource[],
    currentYear: number,
): ReportRow[] {
    // Build a lookup of prev year rows by label
    const prevLookup = new Map<string, ReportRow>();
    for (const row of prevRows) {
        const label = row[labelKey] as string;
        if (label) prevLookup.set(label, row);
    }

    return currentRows.map(row => {
        const label = row[labelKey] as string;
        if (!label || label.trim() === '') return { ...row }; // spacer row

        const prevRow = prevLookup.get(label);
        const merged: ReportRow = { [labelKey]: label };

        // For each trailing month, pick from correct year's data
        let total = 0;
        for (const src of monthSources) {
            const sourceRow = src.year === currentYear ? row : prevRow;
            const val = sourceRow ? (sourceRow[src.month] as number | null) ?? 0 : 0;
            // Store with a tagged key so we can retrieve by position
            merged[src.month] = val;
            total += val;
        }
        merged['TOTAL'] = total;
        return merged;
    });
}

function mergeTrailingDetailRows(
    currentRows: ReportRow[],
    prevRows: ReportRow[],
    labelKeys: string[],
    monthSources: MonthSource[],
    currentYear: number,
): ReportRow[] {
    const isTotalRow = (row: ReportRow) => labelKeys.some(k => row[k] === 'TOTAL');
    const makeKey = (row: ReportRow) => labelKeys.map(k => String(row[k] ?? '')).join('|||');

    // Separate TOTAL rows from data rows
    const currentData = currentRows.filter(r => !isTotalRow(r));
    const prevData = prevRows.filter(r => !isTotalRow(r));

    const prevLookup = new Map<string, ReportRow>();
    for (const row of prevData) {
        prevLookup.set(makeKey(row), row);
    }

    // Merge data rows (excluding TOTAL)
    const seenKeys = new Set<string>();
    const dataRows: ReportRow[] = [];

    for (const row of currentData) {
        const key = makeKey(row);
        seenKeys.add(key);
        dataRows.push(mergeOneDetailRow(row, prevLookup.get(key), labelKeys, monthSources, currentYear));
    }
    for (const row of prevData) {
        const key = makeKey(row);
        if (!seenKeys.has(key)) {
            dataRows.push(mergeOneDetailRow(undefined, row, labelKeys, monthSources, currentYear));
        }
    }

    // Re-sort data rows by TOTAL descending (matching backend behavior)
    dataRows.sort((a, b) => {
        const ta = (a['TOTAL'] as number) ?? 0;
        const tb = (b['TOTAL'] as number) ?? 0;
        return Math.abs(tb) - Math.abs(ta);
    });

    // Rebuild TOTAL row by summing all month columns from merged data rows
    const monthKeys = monthSources.map(s => s.month);
    const totalRow: ReportRow = {};
    for (const k of labelKeys) totalRow[k] = 'TOTAL';
    let grandTotal = 0;
    for (const m of monthKeys) {
        let colSum = 0;
        for (const row of dataRows) {
            colSum += (row[m] as number) ?? 0;
        }
        totalRow[m] = colSum;
        grandTotal += colSum;
    }
    totalRow['TOTAL'] = grandTotal;

    // Append TOTAL row at the end
    return [...dataRows, totalRow];
}

function mergeOneDetailRow(
    currentRow: ReportRow | undefined,
    prevRow: ReportRow | undefined,
    labelKeys: string[],
    monthSources: MonthSource[],
    currentYear: number,
): ReportRow {
    const base = currentRow ?? prevRow!;
    const merged: ReportRow = {};
    for (const k of labelKeys) merged[k] = base[k];

    let total = 0;
    for (const src of monthSources) {
        const sourceRow = src.year === currentYear ? currentRow : prevRow;
        const val = sourceRow ? (sourceRow[src.month] as number | null) ?? 0 : 0;
        merged[src.month] = val;
        total += val;
    }
    merged['TOTAL'] = total;
    return merged;
}

// ─── Trailing 12M BS merge: no summing, just pick each month's balance ─────

function mergeTrailingBSRows(
    currentRows: ReportRow[],
    prevRows: ReportRow[],
    labelKey: string,
    monthSources: MonthSource[],
    currentYear: number,
): ReportRow[] {
    const prevLookup = new Map<string, ReportRow>();
    for (const row of prevRows) {
        const label = row[labelKey] as string;
        if (label) prevLookup.set(label, row);
    }

    return currentRows.map(row => {
        const label = row[labelKey] as string;
        if (!label || label.trim() === '') return { ...row };

        const prevRow = prevLookup.get(label);
        const merged: ReportRow = { [labelKey]: label };

        // Each month's value is the balance at end of that month — no summing for TOTAL
        let lastVal = 0;
        for (const src of monthSources) {
            const sourceRow = src.year === currentYear ? row : prevRow;
            const val = sourceRow ? (sourceRow[src.month] as number | null) ?? 0 : 0;
            merged[src.month] = val;
            lastVal = val;
        }
        // BS TOTAL = last month's balance (not sum)
        merged['TOTAL'] = lastVal;
        return merged;
    });
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
    /** Computed display columns for current granularity/range/variant */
    getDisplayColumns: (variant: 'pl' | 'bs') => DisplayColumn[];
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

    const loadData = useCallback(async (force = false, signal?: AbortSignal) => {
        if (!state.selectedCompany) return;
        dispatch({ type: 'LOAD_START' });
        try {
            // Always fetch current year
            const dataPromise = api.post<ReportData>(API_CONFIG.ENDPOINTS.DATA_LOAD, {
                company: state.selectedCompany,
                year: state.selectedYear,
                force_refresh: force,
            }, { signal });

            // For trailing 12M, also fetch previous year
            let prevPromise: Promise<ReportData> | null = null;
            if (state.periodRange === 'trailing12') {
                prevPromise = api.post<ReportData>(API_CONFIG.ENDPOINTS.DATA_LOAD, {
                    company: state.selectedCompany,
                    year: state.selectedYear - 1,
                    force_refresh: force,
                }, { signal });
            }

            const [data, prevData] = await Promise.all([
                dataPromise,
                prevPromise,
            ]);

            dispatch({ type: 'LOAD_SUCCESS', data, prevYearData: prevData });
        } catch (err: unknown) {
            if (err instanceof DOMException && err.name === 'AbortError') return;
            dispatch({ type: 'LOAD_ERROR', error: err instanceof Error ? err.message : 'Error al cargar datos' });
        }
    }, [state.selectedCompany, state.selectedYear, state.periodRange]);

    // Auto-load data when company, year, or periodRange changes (debounced + cancellable)
    const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const abortRef = useRef<AbortController | null>(null);

    useEffect(() => {
        if (!state.selectedCompany || Object.keys(state.companies).length === 0) return;

        if (debounceRef.current) clearTimeout(debounceRef.current);
        if (abortRef.current) abortRef.current.abort();

        debounceRef.current = setTimeout(() => {
            const controller = new AbortController();
            abortRef.current = controller;
            loadData(false, controller.signal);
        }, 300);

        return () => {
            if (debounceRef.current) clearTimeout(debounceRef.current);
            if (abortRef.current) abortRef.current.abort();
        };
    }, [state.selectedCompany, state.companies, loadData]);

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
            const currentRows = state.reportData[key] as ReportRow[];
            if (state.periodRange === 'ytd') return currentRows;
            const prevRows = (state.prevYearData?.[key] as ReportRow[]) ?? [];
            if (variant === 'bs') {
                return mergeTrailingBSRows(currentRows, prevRows, labelKey, trailingMonthSources, state.selectedYear);
            }
            return mergeTrailingRows(currentRows, prevRows, labelKey, trailingMonthSources, state.selectedYear);
        },
        [state.reportData, state.prevYearData, state.periodRange, trailingMonthSources, state.selectedYear],
    );

    const getMergedDetailRows = useCallback(
        (key: keyof ReportData, labelKeys: string[]): ReportRow[] => {
            if (!state.reportData) return [];
            const currentRows = state.reportData[key] as ReportRow[];
            if (state.periodRange === 'ytd') return currentRows;
            const prevRows = (state.prevYearData?.[key] as ReportRow[]) ?? [];
            return mergeTrailingDetailRows(currentRows, prevRows, labelKeys, trailingMonthSources, state.selectedYear);
        },
        [state.reportData, state.prevYearData, state.periodRange, trailingMonthSources, state.selectedYear],
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
            reportData: state.reportData,
            prevYearData: state.prevYearData,
            currentView: state.currentView,
            setCurrentView: (v) => dispatch({ type: 'SET_VIEW', view: v }),
            isLoading: state.isLoading,
            error: state.error,
            companiesError: state.companiesError,
            loadData, exportFile,
            isExporting: state.isExporting,
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
