import { Component, type ReactNode, type ErrorInfo } from 'react';

interface Props { children: ReactNode; }
interface State { hasError: boolean; error: Error | null; }

export class ErrorBoundary extends Component<Props, State> {
    state: State = { hasError: false, error: null };

    static getDerivedStateFromError(error: Error): State {
        return { hasError: true, error };
    }

    componentDidCatch(error: Error, info: ErrorInfo) {
        console.error('ErrorBoundary caught:', error, info);
    }

    render() {
        if (this.state.hasError) {
            return (
                <div className="flex items-center justify-center min-h-screen bg-surface-alt">
                    <div className="bg-surface p-8 rounded-[14px] border border-border max-w-md text-center">
                        <h1 className="text-xl font-bold text-negative mb-2">
                            Error inesperado
                        </h1>
                        <p className="text-txt-secondary mb-4">
                            {this.state.error?.message || 'Ocurrio un error.'}
                        </p>
                        <button
                            onClick={() => window.location.reload()}
                            className="px-4 py-2 bg-accent text-white rounded-md hover:bg-accent-hover transition-colors"
                        >
                            Recargar pagina
                        </button>
                    </div>
                </div>
            );
        }
        return this.props.children;
    }
}
