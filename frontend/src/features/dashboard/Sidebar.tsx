import { useAuth } from '@/contexts/AuthContext';
import { useReport, type View } from '@/contexts/ReportContext';

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
            className={`w-full flex items-center pl-10 pr-3 py-1.5 text-sm rounded-md transition-colors text-left relative
                ${isActive
                    ? 'bg-accent/15 text-accent font-medium'
                    : 'text-nav-muted hover:text-white hover:bg-nav-hover'}`}
        >
            {isActive && (
                <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 bg-accent rounded-r" />
            )}
            {label}
        </button>
    );
}

const PL_SUB_ITEMS = [
    { view: 'pl', label: 'Resumen' },
    { view: 'ingresos', label: 'Ingresos' },
    { view: 'costo', label: 'Costo de Operaciones' },
    { view: 'gasto_venta', label: 'Gastos de Ventas' },
    { view: 'gasto_admin', label: 'Gastos de Administracion' },
    { view: 'dya', label: 'Depreciacion y Amortizacion' },
    { view: 'resultado_financiero', label: 'Resultado Financiero' },
] as const;

function ExportButton({ onClick, disabled, svgPath, label }: {
    onClick: () => void;
    disabled: boolean;
    svgPath: string;
    label: string;
}) {
    return (
        <button
            onClick={onClick}
            disabled={disabled}
            aria-label={`Exportar ${label}`}
            className="w-full flex items-center px-3 py-1.5 text-sm rounded-md text-nav-muted hover:text-white hover:bg-nav-hover transition-colors disabled:opacity-40 disabled:cursor-not-allowed"
        >
            <svg className="w-4 h-4 mr-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d={svgPath} />
            </svg>
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

    return (
        <aside className="w-56 bg-nav text-white flex flex-col min-h-screen shrink-0">
            {/* Header */}
            <div className="px-5 py-5 border-b border-nav-border">
                <h1 className="text-lg font-bold tracking-wide">FLX Contabilidad</h1>
                <p className="text-2xs text-nav-muted mt-1">Estados Financieros</p>
            </div>

            {/* Navigation */}
            <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
                <p className="text-2xs uppercase tracking-wider text-nav-muted/60 mb-2 px-3">Reportes</p>

                {/* Estado de Resultados section */}
                <div className="mb-3">
                    <div className="flex items-center px-3 py-1.5 text-2xs font-semibold uppercase tracking-wider text-nav-muted">
                        <svg className="w-4 h-4 mr-3 shrink-0 text-nav-muted/70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                        </svg>
                        Estado de Resultados
                    </div>
                    <div className="space-y-0.5">
                        {PL_SUB_ITEMS.map(item => (
                            <NavButton
                                key={item.view}
                                view={item.view}
                                label={item.label}
                                currentView={currentView}
                                onClick={setCurrentView}
                            />
                        ))}
                    </div>
                </div>

                {/* Balance General */}
                <button
                    onClick={() => setCurrentView('bs')}
                    className={`w-full flex items-center px-3 py-2 text-sm rounded-md transition-colors text-left relative
                        ${currentView === 'bs'
                            ? 'bg-accent/15 text-accent font-medium'
                            : 'text-nav-muted hover:text-white hover:bg-nav-hover'}`}
                >
                    {currentView === 'bs' && (
                        <span className="absolute left-0 top-1/2 -translate-y-1/2 w-0.5 h-4 bg-accent rounded-r" />
                    )}
                    <svg className="w-4 h-4 mr-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3" />
                    </svg>
                    Balance General
                </button>
            </nav>

            {/* Export */}
            {reportData && (
                <div className="px-4 py-3 border-t border-nav-border space-y-1">
                    <p className="text-2xs uppercase tracking-wider text-nav-muted/60 mb-1 px-3">Exportar</p>
                    <ExportButton
                        onClick={() => exportFile('excel')}
                        disabled={isExporting}
                        svgPath="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
                        label="Excel"
                    />
                    <ExportButton
                        onClick={() => exportFile('pdf')}
                        disabled={isExporting}
                        svgPath="M7 21h10a2 2 0 002-2V9.414a1 1 0 00-.293-.707l-5.414-5.414A1 1 0 0012.586 3H7a2 2 0 00-2 2v14a2 2 0 002 2z"
                        label="PDF"
                    />
                    <ExportButton
                        onClick={() => exportFile('all')}
                        disabled={isExporting}
                        svgPath="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                        label={isExporting ? 'Generando...' : 'Todo'}
                    />
                </div>
            )}

            {/* User */}
            <div className="px-4 py-3 border-t border-nav-border">
                <div className="flex items-center justify-between">
                    <div className="min-w-0">
                        <p className="text-sm font-medium truncate">{user?.display_name}</p>
                        <p className="text-2xs text-nav-muted truncate">{user?.username}</p>
                    </div>
                    <button
                        onClick={logout}
                        className="p-1.5 rounded-md text-nav-muted hover:text-white hover:bg-nav-hover transition-colors shrink-0"
                        title="Cerrar Sesion"
                        aria-label="Cerrar Sesion"
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                        </svg>
                    </button>
                </div>
            </div>
        </aside>
    );
}
