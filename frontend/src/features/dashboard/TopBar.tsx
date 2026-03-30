import { useReport } from '@/contexts/ReportContext';
import { VIEW_TITLE_MAP } from '@/config/viewConfigs';
import { useViewExport } from './useViewExport';

function ToggleGroup({ value, options, onChange }: {
    value: string;
    options: { value: string; label: string }[];
    onChange: (value: string) => void;
}) {
    return (
        <div className="flex rounded-md overflow-hidden border border-gray-300">
            {options.map(opt => (
                <button
                    key={opt.value}
                    onClick={() => onChange(opt.value)}
                    className={`px-3 py-1.5 text-xs font-medium transition-colors
                        ${value === opt.value
                            ? 'bg-gray-800 text-white'
                            : 'bg-white text-gray-500 hover:bg-gray-50'}`}
                >
                    {opt.label}
                </button>
            ))}
        </div>
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
        ? `${trailingMonthSources[0].month} ${trailingMonthSources[0].year} — ${trailingMonthSources[trailingMonthSources.length - 1].month} ${trailingMonthSources[trailingMonthSources.length - 1].year}`
        : '';

    const subtitle = periodRange === 'ytd'
        ? `${companyName} — ${selectedYear}`
        : `${companyName} — ${trailingLabel}`;

    return (
        <header className="bg-white border-b border-gray-200 px-6 py-3">
            <div className="flex items-center justify-between">
                {/* Left: View title */}
                <div>
                    <h2 className="text-lg font-bold text-gray-800">{title}</h2>
                    <p className="text-xs text-gray-400">{subtitle}</p>
                </div>

                {/* Right: Filters */}
                <div className="flex items-center gap-3">
                    {/* Company */}
                    <div>
                        <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Empresa</label>
                        <select
                            value={selectedCompany}
                            onChange={e => setSelectedCompany(e.target.value)}
                            className="bg-white border border-gray-300 rounded-md px-2.5 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
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
                        <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Vista</label>
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
                        <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Periodo</label>
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
                            <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Ano</label>
                            <select
                                value={selectedYear}
                                onChange={e => setSelectedYear(Number(e.target.value))}
                                className="bg-white border border-gray-300 rounded-md px-2.5 py-1.5 text-sm text-gray-700 focus:outline-none focus:ring-1 focus:ring-blue-500 focus:border-blue-500"
                            >
                                {years.map(y => (
                                    <option key={y} value={y}>{y}</option>
                                ))}
                            </select>
                        </div>
                    ) : (
                        <div>
                            <label className="block text-[10px] uppercase tracking-wider text-gray-400 mb-0.5">Rango</label>
                            <div className="px-2.5 py-1.5 text-sm text-gray-700 bg-gray-50 border border-gray-200 rounded-md">
                                {trailingLabel}
                            </div>
                        </div>
                    )}

                    {/* Refresh button */}
                    <button
                        onClick={() => loadData(true)}
                        disabled={!selectedCompany || isLoading}
                        title="Recargar datos"
                        className="p-1.5 rounded-md border border-gray-300 text-gray-500
                                   hover:bg-gray-50 hover:text-gray-700
                                   disabled:text-gray-300 disabled:cursor-not-allowed
                                   transition-colors"
                    >
                        <svg
                            className={`w-5 h-5 ${isLoading ? 'animate-spin' : ''}`}
                            fill="none" stroke="currentColor" viewBox="0 0 24 24"
                        >
                            <path
                                strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15"
                            />
                        </svg>
                    </button>

                    {/* Export current view to Excel */}
                    <button
                        onClick={handleExport}
                        disabled={!canExport}
                        title="Exportar vista actual a Excel"
                        className="p-1.5 rounded-md border border-gray-300 text-gray-500
                                   hover:bg-gray-50 hover:text-gray-700
                                   disabled:text-gray-300 disabled:cursor-not-allowed
                                   transition-colors"
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path
                                strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                            />
                        </svg>
                    </button>
                </div>
            </div>
        </header>
    );
}
