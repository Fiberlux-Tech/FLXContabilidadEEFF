import { useReport } from '@/contexts/ReportContext';
import Sidebar from './Sidebar';
import TopBar from './TopBar';
import MainContent from './MainContent';

export default function DashboardShell() {
    const { companiesError } = useReport();

    if (companiesError) {
        return (
            <div className="flex items-center justify-center min-h-screen bg-slate-50">
                <div className="bg-white p-6 rounded-lg shadow text-center">
                    <p className="text-red-600 font-medium">{companiesError}</p>
                    <button
                        onClick={() => window.location.reload()}
                        className="mt-4 px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                    >
                        Reintentar
                    </button>
                </div>
            </div>
        );
    }

    return (
        <div className="flex min-h-screen bg-slate-50">
            <Sidebar />
            <div className="flex-1 flex flex-col min-h-screen">
                <TopBar />
                <MainContent />
            </div>
        </div>
    );
}
