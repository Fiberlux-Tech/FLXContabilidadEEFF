import { useState } from 'react';
import { UI_LABELS } from '@/config';

interface AuthPageProps {
  onLogin: (username: string, password: string) => Promise<void>;
}

export default function AuthPage({ onLogin }: AuthPageProps) {
    const [username, setUsername] = useState('');
    const [password, setPassword] = useState('');
    const [error, setError] = useState<string | null>(null);
    const [isLoading, setIsLoading] = useState(false);

    const handleSubmit = async (e: React.FormEvent) => {
        e.preventDefault();
        setError(null);
        setIsLoading(true);
        try {
            await onLogin(username, password);
        } catch (err: any) {
            setError(err.message);
        }
        setIsLoading(false);
    };

    return (
        <div className="min-h-screen bg-surface-alt flex items-center justify-center">
            <div className="bg-surface p-10 rounded-[14px] w-full max-w-md border border-border"
                 style={{ boxShadow: '0 4px 12px rgba(0,0,0,0.06)' }}>
                <h2 className="text-3xl font-bold text-center text-txt mb-8">
                    {UI_LABELS.WELCOME_BACK}
                </h2>
                {error && (
                    <div className="bg-accent-light border border-accent/30 text-accent px-4 py-3 rounded-md mb-6 text-sm" role="alert">
                        {error}
                    </div>
                )}
                <form onSubmit={handleSubmit} className="space-y-6">
                    <div>
                        <label className="block text-sm font-medium text-txt-secondary" htmlFor="username">
                            {UI_LABELS.USUARIO}
                        </label>
                        <input
                            id="username"
                            type="text"
                            value={username}
                            onChange={(e) => setUsername(e.target.value)}
                            required
                            className="mt-1 block w-full px-4 py-3 border border-border rounded-md
                                       focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
                        />
                    </div>
                    <div>
                        <label className="block text-sm font-medium text-txt-secondary" htmlFor="password">
                            {UI_LABELS.CONTRASENA}
                        </label>
                        <input
                            id="password"
                            type="password"
                            value={password}
                            onChange={(e) => setPassword(e.target.value)}
                            required
                            className="mt-1 block w-full px-4 py-3 border border-border rounded-md
                                       focus:outline-none focus:ring-2 focus:ring-accent/20 focus:border-accent transition-colors"
                        />
                    </div>
                    <button
                        type="submit"
                        disabled={isLoading}
                        className="w-full py-3 px-4 border border-transparent rounded-md text-sm font-medium
                                   text-white bg-accent hover:bg-accent-hover
                                   focus:outline-none focus:ring-2 focus:ring-offset-2 focus:ring-accent
                                   disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                        {isLoading ? UI_LABELS.PROCESSING : UI_LABELS.LOGIN}
                    </button>
                </form>
            </div>
        </div>
    );
}
