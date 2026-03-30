import { AuthProvider, useAuth } from '@/contexts/AuthContext';
import { ReportProvider } from '@/contexts/ReportContext';
import AuthPage from '@/features/auth/AuthPage';
import DashboardShell from '@/features/dashboard/DashboardShell';

function AppContent() {
    const { user, isAuthLoading, login } = useAuth();

    if (isAuthLoading) {
        return (
            <div className="min-h-screen bg-surface-alt flex items-center justify-center">
                <h1 className="text-2xl text-txt-secondary">Cargando...</h1>
            </div>
        );
    }

    if (!user) {
        return <AuthPage onLogin={login} />;
    }

    return (
        <ReportProvider>
            <DashboardShell />
        </ReportProvider>
    );
}

export default function App() {
    return (
        <AuthProvider>
            <AppContent />
        </AuthProvider>
    );
}
