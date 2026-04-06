import { useState, useRef, useEffect } from 'react';
import { useReport } from '@/contexts/ReportContext';
import { VIEW_TITLE_MAP } from '@/config/viewConfigs';
import { isBsView } from '@/config/viewRegistry';
import { useViewExport } from './useViewExport';

/* ── tiny hook: close on outside click ── */
function useClickOutside(ref: React.RefObject<HTMLElement | null>, onClose: () => void) {
    useEffect(() => {
        function handler(e: MouseEvent) {
            if (ref.current && !ref.current.contains(e.target as Node)) onClose();
        }
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, [ref, onClose]);
}

/* ── inline toggle (used inside the dropdown) ── */
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

/* ── Display settings dropdown ── */
function DisplayDropdown() {
    const {
        granularity, setGranularity,
        periodRange, setPeriodRange,
        selectedYear, setSelectedYear,
        trailingMonthSources,
    } = useReport();

    const [open, setOpen] = useState(false);
    const ref = useRef<HTMLDivElement>(null);
    useClickOutside(ref, () => setOpen(false));

    const currentYear = new Date().getFullYear();
    const START_YEAR = 2025;
    const years = Array.from({ length: currentYear - START_YEAR + 1 }, (_, i) => currentYear - i);

    const trailingLabel = trailingMonthSources.length > 0
        ? `${trailingMonthSources[0].month} ${trailingMonthSources[0].year} — ${trailingMonthSources[trailingMonthSources.length - 1].month} ${trailingMonthSources[trailingMonthSources.length - 1].year}`
        : '';

    // Chip label summarising current settings
    const granLabel = granularity === 'monthly' ? 'Mensual' : 'Trimestral';
    const periodLabel = periodRange === 'ytd' ? selectedYear : 'Ult 12M';
    const chipLabel = `${granLabel} · ${periodLabel}`;

    return (
        <div className="relative" ref={ref}>
            <button
                onClick={() => setOpen(o => !o)}
                className="dropdown-chip"
            >
                <svg className="w-3.5 h-3.5 text-txt-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
                        d="M10.5 6h9.75M10.5 6a1.5 1.5 0 11-3 0m3 0a1.5 1.5 0 10-3 0M3.75 6H7.5m3 12h9.75m-9.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-3.75 0H7.5m9-6h3.75m-3.75 0a1.5 1.5 0 01-3 0m3 0a1.5 1.5 0 00-3 0m-9.75 0h9.75" />
                </svg>
                {chipLabel}
                <svg className={`w-3 h-3 text-txt-muted transition-transform ${open ? 'rotate-180' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                </svg>
            </button>

            {open && (
                <div className="dropdown-panel w-64">
                    {/* Granularity */}
                    <div>
                        <label className="dropdown-section-label">Vista</label>
                        <ToggleGroup
                            value={granularity}
                            options={[
                                { value: 'monthly', label: 'Mensual' },
                                { value: 'quarterly', label: 'Trimestral' },
                            ]}
                            onChange={v => setGranularity(v as 'monthly' | 'quarterly')}
                        />
                    </div>

                    <div className="h-px bg-border my-2" />

                    {/* Period */}
                    <div>
                        <label className="dropdown-section-label">Periodo</label>
                        <ToggleGroup
                            value={periodRange}
                            options={[
                                { value: 'ytd', label: 'Ano Actual' },
                                { value: 'trailing12', label: 'Ultimos 12M' },
                            ]}
                            onChange={v => setPeriodRange(v as 'ytd' | 'trailing12')}
                        />
                    </div>

                    <div className="h-px bg-border my-2" />

                    {/* Year / Range */}
                    {periodRange === 'ytd' ? (
                        <div>
                            <label className="dropdown-section-label">Ano</label>
                            <select
                                value={selectedYear}
                                onChange={e => setSelectedYear(Number(e.target.value))}
                                className="select-base w-full"
                            >
                                {years.map(y => (
                                    <option key={y} value={y}>{y}</option>
                                ))}
                            </select>
                        </div>
                    ) : (
                        <div>
                            <label className="dropdown-section-label">Rango</label>
                            <div className="px-3 py-1.5 text-[13px] text-txt-secondary bg-surface-alt border border-border rounded-md font-medium">
                                {trailingLabel}
                            </div>
                        </div>
                    )}
                </div>
            )}
        </div>
    );
}

/* ═══════════════════════════════════════════════════════════
   TopBar — compact header with dropdown menus
   ═══════════════════════════════════════════════════════════ */
export default function TopBar() {
    const {
        companies, selectedCompany, setSelectedCompany,
        selectedYear,
        intercompanyFilter, setIntercompanyFilter,
        currentView,
        loadData, isLoading,
        periodRange,
        trailingMonthSources,
    } = useReport();

    const { handleExport, canExport } = useViewExport();

    const companyKeys = Object.keys(companies);
    const companyName = selectedCompany && companies[selectedCompany]
        ? companies[selectedCompany].legal_name
        : selectedCompany;

    const title = VIEW_TITLE_MAP[currentView] ?? currentView;

    const trailingLabel = trailingMonthSources.length > 0
        ? `${trailingMonthSources[0].month} ${trailingMonthSources[0].year} — ${trailingMonthSources[trailingMonthSources.length - 1].month} ${trailingMonthSources[trailingMonthSources.length - 1].year}`
        : '';

    const subtitle = periodRange === 'ytd'
        ? `${companyName} — ${selectedYear}`
        : `${companyName} — ${trailingLabel}`;

    return (
        <header className="bg-surface border-b border-border px-8 py-3 sticky top-0 z-30">
            <div className="flex items-center justify-between">
                {/* Left: View title + subtitle */}
                <div className="min-w-0 mr-6">
                    <h2 className="text-xl font-bold text-txt tracking-tight truncate">{title}</h2>
                    <p className="text-xs text-txt-muted mt-0.5 truncate">{subtitle}</p>
                </div>

                {/* Right: Controls */}
                <div className="flex items-center gap-2 shrink-0">
                    {/* Company */}
                    <select
                        value={selectedCompany}
                        onChange={e => setSelectedCompany(e.target.value)}
                        className="select-base"
                    >
                        <option value="">Empresa...</option>
                        {companyKeys.map(key => (
                            <option key={key} value={key}>{key}</option>
                        ))}
                    </select>

                    {/* Display settings dropdown */}
                    <DisplayDropdown />

                    {/* Intercompany filter — P&L views only */}
                    {!isBsView(currentView) && (
                        <select
                            value={intercompanyFilter}
                            onChange={e => setIntercompanyFilter(e.target.value as 'all' | 'only_ic' | 'ex_ic')}
                            className="select-base"
                        >
                            <option value="all">Todos</option>
                            <option value="only_ic">Solo IC</option>
                            <option value="ex_ic">Sin IC</option>
                        </select>
                    )}

                    <div className="w-px h-6 bg-border" />

                    {/* Refresh */}
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

                    {/* Excel — icon-only green button */}
                    <button
                        onClick={handleExport}
                        disabled={!canExport}
                        className="btn-export-excel"
                        title="Exportar a Excel"
                    >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
                                d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                    </button>
                </div>
            </div>
        </header>
    );
}
