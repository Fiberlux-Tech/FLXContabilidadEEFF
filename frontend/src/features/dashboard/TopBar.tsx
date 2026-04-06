import { useReport } from '@/contexts/ReportContext';
import { VIEW_TITLE_MAP } from '@/config/viewConfigs';
import { isBsView } from '@/config/viewRegistry';
import { useViewExport } from './useViewExport';
import ExportButton from '@/components/ExportButton';

function ToggleGroup({ value, options, onChange }: {
    value: string;
    options: { value: string; label: string }[];
    onChange: (value: string) => void;
}) {
    return (
        <div className="toggle-group">
            {options.map(opt => (
                <button
                    key={opt.value}
                    onClick={() => onChange(opt.value)}
                    className={`toggle-btn ${value === opt.value ? 'toggle-active' : 'toggle-inactive'}`}
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
        excludeIntercompany, setExcludeIntercompany,
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
        <header className="bg-surface border-b border-border px-8 py-3.5 sticky top-0 z-30">
            <div className="flex items-center justify-between">
                {/* Left: View title */}
                <div>
                    <h2 className="text-xl font-bold text-txt tracking-tight">{title}</h2>
                    <p className="text-xs text-txt-muted mt-0.5">{subtitle}</p>
                </div>

                {/* Right: Filters */}
                <div className="flex items-end gap-4">
                    {/* Company */}
                    <div>
                        <label className="filter-label">Empresa</label>
                        <select
                            value={selectedCompany}
                            onChange={e => setSelectedCompany(e.target.value)}
                            className="select-base"
                        >
                            <option value="">Seleccionar...</option>
                            {companyKeys.map(key => (
                                <option key={key} value={key}>{key}</option>
                            ))}
                        </select>
                    </div>

                    <div className="w-px h-8 bg-border self-end mb-0.5" />

                    {/* Granularity */}
                    <div>
                        <label className="filter-label">Vista</label>
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
                        <label className="filter-label">Periodo</label>
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
                            <label className="filter-label">Ano</label>
                            <select
                                value={selectedYear}
                                onChange={e => setSelectedYear(Number(e.target.value))}
                                className="select-base"
                            >
                                {years.map(y => (
                                    <option key={y} value={y}>{y}</option>
                                ))}
                            </select>
                        </div>
                    ) : (
                        <div>
                            <label className="filter-label">Rango</label>
                            <div className="px-3 py-1.5 text-[13px] text-txt-secondary bg-surface-alt border border-border rounded-md font-medium">
                                {trailingLabel}
                            </div>
                        </div>
                    )}

                    {/* Intercompany toggle — only on P&L views */}
                    {!isBsView(currentView) && (
                        <>
                            <div className="w-px h-8 bg-border self-end mb-0.5" />
                            <div>
                                <label className="filter-label">Intercompany</label>
                                <ToggleGroup
                                    value={excludeIntercompany ? 'off' : 'on'}
                                    options={[
                                        { value: 'on', label: 'On' },
                                        { value: 'off', label: 'Off' },
                                    ]}
                                    onChange={v => setExcludeIntercompany(v === 'off')}
                                />
                            </div>
                        </>
                    )}

                    <div className="flex items-center gap-1.5">
                        {/* Refresh button */}
                        <button
                            onClick={() => loadData(true)}
                            disabled={!selectedCompany || isLoading}
                            className="btn-icon"
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
                        </button>

                        {/* Export current view to Excel */}
                        <ExportButton variant="excel" onClick={handleExport} disabled={!canExport} />
                    </div>
                </div>
            </div>
        </header>
    );
}
