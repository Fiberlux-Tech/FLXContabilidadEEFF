import { useReport } from '@/contexts/ReportContext';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import MainContent from './MainContent';

export default function DashboardShell() {
    const { companiesError } = useReport();

    if (companiesError) {
        return (
            <div className="flex items-center justify-center min-h-screen bg-gray-50">
                <div className="bg-white p-8 rounded-2xl shadow-lg text-center max-w-sm border border-gray-100">
                    <div className="w-12 h-12 rounded-full bg-red-50 flex items-center justify-center mx-auto mb-4">
                        <svg className="w-6 h-6 text-negative" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    </div>
                    <p className="text-negative font-medium mb-1">Error de conexion</p>
                    <p className="text-sm text-gray-500 mb-4">{companiesError}</p>
                    <button
                        onClick={() => window.location.reload()}
                        className="px-5 py-2 bg-accent text-white rounded-lg hover:bg-blue-600 transition-colors text-sm font-medium shadow-sm"
                    >
                        Reintentar
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="flex min-h-screen bg-gray-50">
            <Sidebar />
            <div className="flex-1 flex flex-col min-h-screen">
                <TopBar />
                <MainContent />
            </div>
        </div>
    );
}
