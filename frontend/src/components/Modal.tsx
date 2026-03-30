import { useEffect } from 'react';
import { createPortal } from 'react-dom';

interface ModalProps {
    isOpen: boolean;
    onClose: () => void;
    title: string;
    headerActions?: React.ReactNode;
    children: React.ReactNode;
}

export default function Modal({ isOpen, onClose, title, headerActions, children }: ModalProps) {
    useEffect(() => {
        if (!isOpen) return;
        const prev = document.body.style.overflow;
        document.body.style.overflow = 'hidden';
        return () => { document.body.style.overflow = prev; };
    }, [isOpen]);

    useEffect(() => {
        if (!isOpen) return;
        const handler = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose();
        };
        document.addEventListener('keydown', handler);
        return () => document.removeEventListener('keydown', handler);
    }, [isOpen, onClose]);

    if (!isOpen) return null;

    return createPortal(
        <>
            {/* Backdrop */}
            <div
                className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm transition-opacity"
                onClick={onClose}
            />

            {/* Centering wrapper */}
            <div className="fixed inset-0 z-50 flex items-start justify-center pt-[5vh] pointer-events-none">
                {/* Panel */}
                <div
                    className="pointer-events-auto flex flex-col bg-white rounded-2xl shadow-2xl
                               max-w-[90vw] max-h-[85vh] border border-gray-200/50"
                    onClick={e => e.stopPropagation()}
                >
                    {/* Header */}
                    <div className="flex items-center justify-between px-5 py-3.5 border-b border-gray-100 shrink-0">
                        <h2 className="text-sm font-semibold text-gray-700 truncate">{title}</h2>
                        <div className="flex items-center gap-2 shrink-0 ml-4">
                            {headerActions}
                            <button
                                onClick={onClose}
                                className="p-1.5 text-gray-400 hover:text-gray-600 rounded-lg hover:bg-gray-100 transition-colors"
                                aria-label="Cerrar"
                            >
                                <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                            </button>
                        </div>
                    </div>

                    {/* Body */}
                    <div className="overflow-auto p-4">
                        {children}
                    </div>
                </div>
            </div>
        </>,
        document.body,
    );
}
