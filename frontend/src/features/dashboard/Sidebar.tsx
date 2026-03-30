import { useAuth } from '@/contexts/AuthContext';
import { useReport, type View } from '@/contexts/ReportContext';

function NavButton({ view, label, currentView, onClick }: {
    view: View;
    label: string;
    currentView: View;
    onClick: (view: View) => void;
}) {
    return (
        <button
            onClick={() => onClick(view)}
            className={`w-full flex items-center pl-10 pr-3 py-1.5 text-sm rounded-md transition-colors text-left
                ${currentView === view ? 'bg-gray-800 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800/50'}`}
        >
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
            className="w-full flex items-center px-3 py-1.5 text-sm rounded-md text-gray-300 hover:text-white hover:bg-gray-800/50 transition-colors disabled:opacity-50"
        >
            <svg className="w-4 h-4 mr-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={svgPath} />
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
        <aside className="w-56 bg-gray-900 text-white flex flex-col min-h-screen shrink-0">
            {/* Header */}
            <div className="p-5 border-b border-gray-700">
                <h1 className="text-lg font-bold tracking-wide">FLX Contabilidad</h1>
                <p className="text-xs text-gray-400 mt-1">Estados Financieros</p>
            </div>

            {/* Navigation */}
            <nav className="flex-1 p-4 space-y-1">
                <p className="text-[10px] uppercase tracking-wider text-gray-500 mb-2">Reportes</p>

                {/* Estado de Resultados section */}
                <div className="mb-2">
                    <div className="flex items-center px-3 py-1.5 text-xs font-semibold uppercase tracking-wider text-gray-400">
                        <svg className="w-4 h-4 mr-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                        </svg>
                        Estado de Resultados
                    </div>
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

                {/* Balance General */}
                <button
                    onClick={() => setCurrentView('bs')}
                    className={`w-full flex items-center px-3 py-2 text-sm rounded-md transition-colors text-left
                        ${currentView === 'bs' ? 'bg-gray-800 text-white' : 'text-gray-400 hover:text-white hover:bg-gray-800/50'}`}
                >
                    <svg className="w-4 h-4 mr-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M3 6l3 1m0 0l-3 9a5.002 5.002 0 006.001 0M6 7l3 9M6 7l6-2m6 2l3-1m-3 1l-3 9a5.002 5.002 0 006.001 0M18 7l3 9m-3-9l-6-2m0-2v2m0 16V5m0 16H9m3 0h3" />
                    </svg>
                    Balance General
                </button>
            </nav>

            {/* Export */}
            {reportData && (
                <div className="p-4 border-t border-gray-700 space-y-2">
                    <p className="text-[10px] uppercase tracking-wider text-gray-500 mb-1">Exportar</p>
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
            <div className="p-4 border-t border-gray-700">
                <div className="flex items-center justify-between">
                    <div>
                        <p className="text-sm font-medium">{user?.display_name}</p>
                        <p className="text-xs text-gray-400">{user?.username}</p>
                    </div>
                    <button
                        onClick={logout}
                        className="text-xs text-gray-400 hover:text-white transition-colors"
                        title="Cerrar Sesion"
                        aria-label="Cerrar Sesion"
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
                        </svg>
                    </button>
                </div>
            </div>
        </aside>
    );
}
