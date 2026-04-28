import { useState, type ReactNode } from 'react';
import { useAuth } from '@/contexts/AuthContext';
import { useReport } from '@/contexts/ReportContext';
import {
    isBsView, isAnalysisView, isAdminView,
    PL_NAV_ITEMS, BS_NAV_ITEMS, ANALYSIS_NAV_ITEMS, ADMIN_NAV_ITEMS,
} from '@/config/viewRegistry';
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

interface NavSectionProps {
    label: string;
    icon: ReactNode;
    items: readonly { view: View; label: string }[];
    isOpen: boolean;
    onToggle: () => void;
    currentView: View;
    onItemClick: (view: View) => void;
}

function NavSection({ label, icon, items, isOpen, onToggle, currentView, onItemClick }: NavSectionProps) {
    if (items.length === 0) return null;
    return (
        <div className="mb-1">
            <button
                onClick={onToggle}
                className="w-full flex items-center justify-between px-3 py-[7px] text-[13px] font-semibold text-nav-text hover:bg-nav-hover rounded-md transition-colors"
            >
                <span className="flex items-center gap-2.5">{icon}{label}</span>
                <svg className={`w-4 h-4 shrink-0 text-txt-muted transition-transform ${isOpen ? 'rotate-90' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
            </button>
            {isOpen && (
                <div className="space-y-0.5">
                    {items.map(item => (
                        <NavButton
                            key={item.view}
                            view={item.view}
                            label={item.label}
                            currentView={currentView}
                            onClick={onItemClick}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}

const ICON_PL = (
    <svg className="w-4 h-4 shrink-0 text-txt-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
    </svg>
);
const ICON_BS = (
    <svg className="w-4 h-4 shrink-0 text-txt-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3" />
    </svg>
);
const ICON_ANALYSIS = (
    <svg className="w-4 h-4 shrink-0 text-txt-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M7 12l3-3 3 3 4-4M8 21l4-4 4 4M3 4h18M4 4h16v12a1 1 0 01-1 1H5a1 1 0 01-1-1V4z" />
    </svg>
);
const ICON_ADMIN = (
    <svg className="w-4 h-4 shrink-0 text-txt-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 19.128a9.38 9.38 0 002.625.372 9.337 9.337 0 004.121-.952 4.125 4.125 0 00-7.533-2.493M15 19.128v-.003c0-1.113-.285-2.16-.786-3.07M15 19.128v.106A12.318 12.318 0 018.624 21c-2.331 0-4.512-.645-6.374-1.766l-.001-.109a6.375 6.375 0 0111.964-3.07M12 6.375a3.375 3.375 0 11-6.75 0 3.375 3.375 0 016.75 0zm8.25 2.25a2.625 2.625 0 11-5.25 0 2.625 2.625 0 015.25 0z" />
    </svg>
);

export default function Sidebar() {
    const { user, logout, canAccess } = useAuth();
    const {
        currentView, setCurrentView,
        reportData, exportFile, isExporting,
    } = useReport();

    const isBs = isBsView(currentView);
    const isAnalysis = isAnalysisView(currentView);
    const isAdmin = isAdminView(currentView);
    const [plOpen, setPlOpen] = useState(true);
    const [bsOpen, setBsOpen] = useState(isBs);
    const [analysisOpen, setAnalysisOpen] = useState(isAnalysis);
    const [adminOpen, setAdminOpen] = useState(isAdmin);

    // Auto-expand the section containing the active view
    const handleViewClick = (view: View) => {
        if (isAdminView(view)) setAdminOpen(true);
        else if (isAnalysisView(view)) setAnalysisOpen(true);
        else if (isBsView(view)) setBsOpen(true);
        else setPlOpen(true);
        setCurrentView(view);
    };

    // Filter nav items by current user's permissions. The Administración section
    // contains both upload_planilla (per-user grantable) and admin_users
    // (admin-only — canAccess enforces this even when admin_users is in the
    // user's grandfathered allowed_views list).
    const plItems = PL_NAV_ITEMS.filter(i => canAccess(i.view));
    const bsItems = BS_NAV_ITEMS.filter(i => canAccess(i.view));
    const analysisItems = ANALYSIS_NAV_ITEMS.filter(i => canAccess(i.view));
    const adminItems = ADMIN_NAV_ITEMS.filter(i => canAccess(i.view));

    // Render dividers only between visible sections
    const sections = [
        { items: plItems, node: (
            <NavSection
                label="Estado de Resultados" icon={ICON_PL} items={plItems}
                isOpen={plOpen} onToggle={() => setPlOpen(o => !o)}
                currentView={currentView} onItemClick={handleViewClick}
            />
        )},
        { items: bsItems, node: (
            <NavSection
                label="Balance General" icon={ICON_BS} items={bsItems}
                isOpen={bsOpen} onToggle={() => setBsOpen(o => !o)}
                currentView={currentView} onItemClick={handleViewClick}
            />
        )},
        { items: analysisItems, node: (
            <NavSection
                label="Reportes Variados" icon={ICON_ANALYSIS} items={analysisItems}
                isOpen={analysisOpen} onToggle={() => setAnalysisOpen(o => !o)}
                currentView={currentView} onItemClick={handleViewClick}
            />
        )},
        { items: adminItems, node: (
            <NavSection
                label="Administración" icon={ICON_ADMIN} items={adminItems}
                isOpen={adminOpen} onToggle={() => setAdminOpen(o => !o)}
                currentView={currentView} onItemClick={handleViewClick}
            />
        )},
    ].filter(s => s.items.length > 0);

    return (
        <aside className="w-[280px] bg-nav border-r border-nav-border flex flex-col min-h-screen shrink-0 overflow-y-auto">
            {/* Header */}
            <div className="px-5 pt-5 pb-4">
                <h1 className="text-lg font-bold text-txt tracking-tight">
                    {import.meta.env.VITE_APP_ENV === 'staging' ? 'TEST WEB' : 'FLX Contabilidad'}
                </h1>
                <p className="text-[11px] text-txt-muted mt-0.5 font-medium">Estados Financieros</p>
            </div>

            {/* Navigation */}
            <nav className="flex-1 px-2">
                {sections.map((section, idx) => (
                    <div key={idx}>
                        {section.node}
                        {idx < sections.length - 1 && (
                            <div className="h-px bg-nav-border mx-3 my-2" />
                        )}
                    </div>
                ))}
            </nav>

            {/* Export */}
            {reportData && (
                <div className="px-4 py-3 border-t border-nav-border">
                    <p className="text-[10px] uppercase font-semibold text-txt-muted mb-2" style={{ letterSpacing: '0.8px' }}>
                        Exportar
                    </p>
                    <div className="flex gap-1.5">
                        <ExportButton variant="excel" size="chip" onClick={() => exportFile('excel')} disabled={isExporting} />
                        <ExportButton variant="pdf" size="chip" onClick={() => exportFile('pdf')} disabled={isExporting} />
                        <ExportButton
                            variant="all"
                            size="chip"
                            onClick={() => exportFile('all')}
                            disabled={isExporting}
                            label={isExporting ? 'Generando...' : undefined}
                        />
                    </div>
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
