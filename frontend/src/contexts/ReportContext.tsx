import { createContext, useContext, useState, useCallback, useEffect } from 'react';
import { api } from '@/lib/api';
import { API_CONFIG } from '@/config';
import type { ReportData, CompanyMap } from '@/types';

export type View = 'pl' | 'bs' | 'ingresos' | 'costo' | 'gasto_venta' | 'gasto_admin' | 'dya' | 'resultado_financiero';

interface IReportContext {
    companies: CompanyMap;
    selectedCompany: string;
    setSelectedCompany: (c: string) => void;
    selectedYear: number;
    setSelectedYear: (y: number) => void;
    reportData: ReportData | null;
    currentView: View;
    setCurrentView: (v: View) => void;
    isLoading: boolean;
    error: string | null;
    companiesError: string | null;
    loadData: (force?: boolean) => Promise<void>;
    exportFile: (type: 'excel' | 'pdf' | 'all') => Promise<void>;
    isExporting: boolean;
}

const ReportContext = createContext<IReportContext | null>(null);

export function ReportProvider({ children }: { children: React.ReactNode }) {
    const [companies, setCompanies] = useState<CompanyMap>({});
    const [companiesError, setCompaniesError] = useState<string | null>(null);
    const [selectedCompany, setSelectedCompany] = useState('');
    const [selectedYear, setSelectedYear] = useState(new Date().getFullYear());

    useEffect(() => {
        api.get<CompanyMap>(API_CONFIG.ENDPOINTS.COMPANIES).then(data => {
            setCompanies(data);
            const keys = Object.keys(data);
            if (keys.length > 0) {
                setSelectedCompany(keys[0]);
            }
        }).catch((err) => {
            console.error(err);
            setCompaniesError('No se pudieron cargar las empresas. Verifique su conexion.');
        });
    }, []);
    const [reportData, setReportData] = useState<ReportData | null>(null);
    const [currentView, setCurrentView] = useState<View>('pl');
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isExporting, setIsExporting] = useState(false);

    const loadData = useCallback(async (force = false) => {
        if (!selectedCompany) return;
        setIsLoading(true);
        setError(null);
        try {
            const data = await api.post<ReportData>(API_CONFIG.ENDPOINTS.DATA_LOAD, {
                company: selectedCompany,
                year: selectedYear,
                force_refresh: force,
            });
            setReportData(data);
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : 'Error al cargar datos');
            setReportData(null);
        } finally {
            setIsLoading(false);
        }
    }, [selectedCompany, selectedYear]);

    const exportFile = useCallback(async (type: 'excel' | 'pdf' | 'all') => {
        if (!selectedCompany) return;
        setIsExporting(true);
        setError(null);

        const endpointMap = {
            excel: API_CONFIG.ENDPOINTS.EXPORT_EXCEL,
            pdf: API_CONFIG.ENDPOINTS.EXPORT_PDF,
            all: API_CONFIG.ENDPOINTS.EXPORT_ALL,
        };

        try {
            const result = await api.post<Record<string, string>>(endpointMap[type], {
                company: selectedCompany,
                year: selectedYear,
            });

            // Trigger downloads for returned files
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
        } catch (err: unknown) {
            setError(err instanceof Error ? err.message : 'Error al exportar');
        } finally {
            setIsExporting(false);
        }
    }, [selectedCompany, selectedYear]);

    return (
        <ReportContext.Provider value={{
            companies,
            selectedCompany, setSelectedCompany,
            selectedYear, setSelectedYear,
            reportData,
            currentView, setCurrentView,
            isLoading, error, companiesError,
            loadData, exportFile, isExporting,
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
