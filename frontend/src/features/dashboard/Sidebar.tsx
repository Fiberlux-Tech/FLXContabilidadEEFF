import { useState } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useReport } from '@/contexts/ReportContext';
import { isBsView, isAnalysisView, PL_NAV_ITEMS, BS_NAV_ITEMS, ANALYSIS_NAV_ITEMS } from '@/config/viewRegistry';
import type { View } from '@/config/viewRegistry';
import ExportButton from '@/components/ExportButton';

function NavButton({ view, label, currentView, onClick }: {
    view: View;
    label: string;
    currentView: View;
    onClick: (view: View) => void;
}) {
    const isActive = currentView === view;
    return (
        <button
            onClick={() => onClick(view)}
            className={`nav-item-base pl-10 pr-3 py-1.5
                ${isActive ? 'nav-item-active' : 'nav-item-inactive'}`}
        >
            {isActive && <span className="nav-indicator" />}
            {label}
        </button>
    );
}



export default function Sidebar() {
    const { user, logout } = useAuth();
    const {
        currentView, setCurrentView,
        reportData, exportFile, isExporting,
    } = useReport();

    const isBs = isBsView(currentView);
    const isAnalysis = isAnalysisView(currentView);
    const [plOpen, setPlOpen] = useState(true);
    const [bsOpen, setBsOpen] = useState(isBs);
    const [analysisOpen, setAnalysisOpen] = useState(isAnalysis);

    // Auto-expand the section containing the active view
    const handleViewClick = (view: View) => {
        if (isAnalysisView(view)) setAnalysisOpen(true);
        else if (isBsView(view)) setBsOpen(true);
        else setPlOpen(true);
        setCurrentView(view);
    };

    return (
        <aside className="w-[280px] bg-nav border-r border-nav-border flex flex-col min-h-screen shrink-0 overflow-y-auto">
            {/* Header */}
            <div className="px-5 pt-5 pb-4">
                <h1 className="text-lg font-bold text-txt tracking-tight">FLX Contabilidad</h1>
                <p className="text-[11px] text-txt-muted mt-0.5 font-medium">Estados Financieros</p>
            </div>

            {/* Navigation */}
            <nav className="flex-1 px-2">
                {/* Estado de Resultados section */}
                <div className="mb-1">
                    <button
                        onClick={() => setPlOpen(o => !o)}
                        className="w-full flex items-center justify-between px-3 py-[7px] text-[13px] font-semibold text-nav-text hover:bg-nav-hover rounded-md transition-colors"
                    >
                        <span className="flex items-center gap-2.5">
                            <svg className="w-4 h-4 shrink-0 text-txt-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                            </svg>
                            Estado de Resultados
                        </span>
                        <svg className={`w-4 h-4 shrink-0 text-txt-muted transition-transform ${plOpen ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                    </button>
                    {plOpen && (
                        <div className="space-y-0.5">
                            {PL_NAV_ITEMS.map(item => (
                                <NavButton
                                    key={item.view}
                                    view={item.view}
                                    label={item.label}
                                    currentView={currentView}
                                    onClick={handleViewClick}
                                />
                            ))}
                        </div>
                    )}
                </div>

                {/* Divider */}
                <div className="h-px bg-nav-border mx-3 my-2" />

                {/* Balance General section */}
                <div className="mb-1">
                    <button
                        onClick={() => setBsOpen(o => !o)}
                        className="w-full flex items-center justify-between px-3 py-[7px] text-[13px] font-semibold text-nav-text hover:bg-nav-hover rounded-md transition-colors"
                    >
                        <span className="flex items-center gap-2.5">
                            <svg className="w-4 h-4 shrink-0 text-txt-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3" />
                            </svg>
                            Balance General
                        </span>
                        <svg className={`w-4 h-4 shrink-0 text-txt-muted transition-transform ${bsOpen ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                    </button>
                    {bsOpen && (
                        <div className="space-y-0.5">
                            {BS_NAV_ITEMS.map(item => (
                                <NavButton
                                    key={item.view}
                                    view={item.view}
                                    label={item.label}
                                    currentView={currentView}
                                    onClick={handleViewClick}
                                />
                            ))}
                        </div>
                    )}
                </div>

                {/* Divider */}
                <div className="h-px bg-nav-border mx-3 my-2" />

                {/* Analysis section */}
                <div className="mb-1">
                    <button
                        onClick={() => setAnalysisOpen(o => !o)}
                        className="w-full flex items-center justify-between px-3 py-[7px] text-[13px] font-semibold text-nav-text hover:bg-nav-hover rounded-md transition-colors"
                    >
                        <span className="flex items-center gap-2.5">
                            <svg className="w-4 h-4 shrink-0 text-txt-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
                            </svg>
                            Analisis de Finanzas
                        </span>
                        <svg className={`w-4 h-4 shrink-0 text-txt-muted transition-transform ${analysisOpen ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                        </svg>
                    </button>
                    {analysisOpen && (
                        <div className="space-y-0.5">
                            {ANALYSIS_NAV_ITEMS.map(item => (
                                <NavButton
                                    key={item.view}
                                    view={item.view}
                                    label={item.label}
                                    currentView={currentView}
                                    onClick={handleViewClick}
                                />
                            ))}
                        </div>
                    )}
                </div>
            </nav>

            {/* Export */}
            {reportData && (
                <div className="px-2 py-3 space-y-0.5">
                    <p className="text-[10px] uppercase font-semibold text-txt-muted px-3 pb-1" style={{ letterSpacing: '1px' }}>
                        Exportar
                    </p>
                    <ExportButton variant="excel" onClick={() => exportFile('excel')} disabled={isExporting} />
                    <ExportButton variant="pdf" onClick={() => exportFile('pdf')} disabled={isExporting} />
                    <ExportButton
                        variant="all"
                        onClick={() => exportFile('all')}
                        disabled={isExporting}
                        label={isExporting ? 'Generando...' : undefined}
                    />
                </div>
            )}

            {/* User */}
            <div className="px-4 py-3 border-t border-nav-border">
                <div className="flex items-center justify-between">
                    <div className="flex items-center gap-2.5 min-w-0">
                        <div className="w-7 h-7 rounded-full bg-accent text-white flex items-center justify-center text-[11px] font-semibold shrink-0">
                            {user?.display_name?.charAt(0).toUpperCase() ?? 'U'}
                        </div>
                        <div className="min-w-0">
                            <p className="text-[13px] font-medium text-txt truncate">{user?.display_name}</p>
                            <p className="text-[11px] text-txt-muted truncate">{user?.username}</p>
                        </div>
                    </div>
                    <button
                        onClick={logout}
                        className="p-1.5 rounded-md text-txt-muted hover:text-txt-secondary hover:bg-nav-hover transition-colors shrink-0"
                        title="Cerrar Sesion"
                        aria-label="Cerrar Sesion"
                    >
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                        </svg>
                    </button>
                </div>
            </div>
        </aside>
    );
}
