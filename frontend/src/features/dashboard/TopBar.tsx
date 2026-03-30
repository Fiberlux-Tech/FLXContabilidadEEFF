import { useReport } from '@/contexts/ReportContext';
import { VIEW_TITLE_MAP } from '@/config/viewConfigs';
import { useViewExport } from './useViewExport';

function ToggleGroup({ value, options, onChange }: {
    value: string;
    options: { value: string; label: string }[];
    onChange: (value: string) => void;
}) {
    return (
        <div className="inline-flex rounded-lg overflow-hidden border border-gray-200 shadow-sm">
            {options.map(opt => (
                <button
                    key={opt.value}
                    onClick={() => onChange(opt.value)}
                    className={`px-3 py-1.5 text-xs font-medium transition-all
                        ${value === opt.value
                            ? 'bg-accent text-white shadow-inner'
                            : 'bg-white text-gray-500 hover:bg-gray-50 hover:text-gray-700'}`}
                >
                    {opt.label}
                </button>
            ))}
        </div>
    );
}

function IconButton({ onClick, disabled, title, children, className = '' }: {
    onClick: () => void;
    disabled: boolean;
    title: string;
    children: React.ReactNode;
    className?: string;
}) {
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            title={title}
            className={`p-1.5 rounded-lg border border-gray-200 text-gray-400
                       hover:bg-gray-50 hover:text-gray-600 hover:border-gray-300
                       disabled:text-gray-300 disabled:cursor-not-allowed disabled:hover:bg-white disabled:hover:border-gray-200
                       transition-colors shadow-sm ${className}`}
        >
            {children}
        </button>
    );
}

export default function TopBar() {
    const {
        companies, selectedCompany, setSelectedCompany,
        selectedYear, setSelectedYear,
        granularity, setGranularity,
        periodRange, setPeriodRange,
        currentView,
        loadData, isLoading,
        trailingMonthSources,
    } = useReport();

    const { handleExport, canExport } = useViewExport();

    const companyKeys = Object.keys(companies);
    const currentYear = new Date().getFullYear();
    const START_YEAR = 2025;
    const years = Array.from({ length: currentYear - START_YEAR + 1 }, (_, i) => currentYear - i);

    const companyName = selectedCompany && companies[selectedCompany]
        ? companies[selectedCompany].legal_name
        : selectedCompany;

    const title = VIEW_TITLE_MAP[currentView] ?? currentView;

    // Build trailing range label from sources
    const trailingLabel = trailingMonthSources.length > 0
        ? `${trailingMonthSources[0].month} ${trailingMonthSources[0].year} \u2014 ${trailingMonthSources[trailingMonthSources.length - 1].month} ${trailingMonthSources[trailingMonthSources.length - 1].year}`
        : '';

    const subtitle = periodRange === 'ytd'
        ? `${companyName} \u2014 ${selectedYear}`
        : `${companyName} \u2014 ${trailingLabel}`;

    return (
        <header className="bg-white border-b border-gray-200 px-6 py-3 shadow-sm">
            <div className="flex items-center justify-between">
                {/* Left: View title */}
                <div>
                    <h2 className="text-lg font-bold text-gray-800">{title}</h2>
                    <p className="text-xs text-gray-400 mt-0.5">{subtitle}</p>
                </div>

                {/* Right: Filters */}
                <div className="flex items-center gap-4">
                    {/* Company */}
                    <div>
                        <label className="block text-2xs uppercase tracking-wider text-gray-400 mb-1 font-medium">Empresa</label>
                        <select
                            value={selectedCompany}
                            onChange={e => setSelectedCompany(e.target.value)}
                            className="bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-gray-700 shadow-sm
                                       focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent transition-colors"
                        >
                            <option value="">Seleccionar...</option>
                            {companyKeys.map(key => (
                                <option key={key} value={key}>{key}</option>
                            ))}
                        </select>
                    </div>

                    <div className="h-8 w-px bg-gray-200" />

                    {/* Granularity */}
                    <div>
                        <label className="block text-2xs uppercase tracking-wider text-gray-400 mb-1 font-medium">Vista</label>
                        <ToggleGroup
                            value={granularity}
                            options={[
                                { value: 'monthly', label: 'Mensual' },
                                { value: 'quarterly', label: 'Trimestral' },
                            ]}
                            onChange={v => setGranularity(v as 'monthly' | 'quarterly')}
                        />
                    </div>

                    {/* Period Range */}
                    <div>
                        <label className="block text-2xs uppercase tracking-wider text-gray-400 mb-1 font-medium">Periodo</label>
                        <ToggleGroup
                            value={periodRange}
                            options={[
                                { value: 'ytd', label: 'Ano Actual' },
                                { value: 'trailing12', label: 'Ultimos 12M' },
                            ]}
                            onChange={v => setPeriodRange(v as 'ytd' | 'trailing12')}
                        />
                    </div>

                    {/* Year (only for YTD) */}
                    {periodRange === 'ytd' ? (
                        <div>
                            <label className="block text-2xs uppercase tracking-wider text-gray-400 mb-1 font-medium">Ano</label>
                            <select
                                value={selectedYear}
                                onChange={e => setSelectedYear(Number(e.target.value))}
                                className="bg-white border border-gray-200 rounded-lg px-3 py-1.5 text-sm text-gray-700 shadow-sm
                                           focus:outline-none focus:ring-2 focus:ring-accent/30 focus:border-accent transition-colors"
                            >
                                {years.map(y => (
                                    <option key={y} value={y}>{y}</option>
                                ))}
                            </select>
                        </div>
                    ) : (
                        <div>
                            <label className="block text-2xs uppercase tracking-wider text-gray-400 mb-1 font-medium">Rango</label>
                            <div className="px-3 py-1.5 text-sm text-gray-600 bg-gray-50 border border-gray-200 rounded-lg shadow-sm font-medium">
                                {trailingLabel}
                            </div>
                        </div>
                    )}

                    <div className="flex items-center gap-1.5 pt-4">
                        {/* Refresh button */}
                        <IconButton
                            onClick={() => loadData(true)}
                            disabled={!selectedCompany || isLoading}
                            title="Recargar datos"
                        >
                            <svg
                                className={`w-4 h-4 ${isLoading ? 'animate-spin' : ''}`}
                                fill="none" stroke="currentColor" viewBox="0 0 24 24"
                            >
                                <path
                                    strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                    d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                                />
                            </svg>
                        </IconButton>

                        {/* Export current view to Excel */}
                        <IconButton
                            onClick={handleExport}
                            disabled={!canExport}
                            title="Exportar vista actual a Excel"
                        >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path
                                    strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                    d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                                />
                            </svg>
                        </IconButton>
                    </div>
                </div>
            </div>
        </header>
    );
}
