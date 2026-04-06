import { useRef, useState } from 'react';
import { api } from '@/lib/api';

interface UploadResult {
    saved: number;
}

export default function UploadPlanilla() {
    const fileInputRef = useRef<HTMLInputElement>(null);
    const [status, setStatus] = useState<'idle' | 'uploading' | 'success' | 'error'>('idle');
    const [message, setMessage] = useState('');

    const handleClick = () => {
        fileInputRef.current?.click();
    };

    const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
        const file = e.target.files?.[0];
        if (!file) return;

        setStatus('uploading');
        setMessage('');

        const formData = new FormData();
        formData.append('file', file);

        try {
            const result = await api.postForm<UploadResult>(
                '/api/admin/headcount/upload',
                formData,
            );
            setStatus('success');
            setMessage(`${result.saved} registros de empleados guardados`);
        } catch (err) {
            setStatus('error');
            setMessage(err instanceof Error ? err.message : 'Error al cargar archivo');
        }

        // Reset file input so same file can be re-uploaded
        if (fileInputRef.current) fileInputRef.current.value = '';
    };

    return (
        <div className="flex-1 flex items-center justify-center p-8">
            <div className="max-w-md w-full text-center">
                <div className="border-2 border-dashed border-border rounded-lg p-10 hover:border-accent transition-colors">
                    <svg className="w-12 h-12 mx-auto mb-4 text-txt-muted" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                    </svg>

                    <h2 className="text-lg font-semibold text-txt mb-2">Cargar Planilla</h2>
                    <p className="text-sm text-txt-muted mb-6">
                        Sube el archivo CSV de empleados para calcular el headcount por centro de costo.
                    </p>
                    <p className="text-xs text-txt-faint mb-6">
                        Columnas esperadas: Año-Mes, EMPRESA, EMPLEADO, NOMBRE, CENTRO DE COSTO, COD CENTRO DE COSTO
                    </p>

                    <input
                        ref={fileInputRef}
                        type="file"
                        accept=".csv,.txt"
                        onChange={handleFileChange}
                        className="hidden"
                    />

                    <button
                        onClick={handleClick}
                        disabled={status === 'uploading'}
                        className="px-6 py-2.5 bg-accent text-white text-sm font-medium rounded-md
                            hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed transition-colors"
                    >
                        {status === 'uploading' ? 'Cargando...' : 'Seleccionar Archivo'}
                    </button>
                </div>

                {/* Status message */}
                {status === 'success' && (
                    <div className="mt-4 p-3 bg-green-50 border border-green-200 rounded-md">
                        <p className="text-sm text-positive">{message}</p>
                    </div>
                )}
                {status === 'error' && (
                    <div className="mt-4 p-3 bg-accent-light border border-accent/30 rounded-md">
                        <p className="text-sm text-negative">{message}</p>
                    </div>
                )}
            </div>
        </div>
    );
}
