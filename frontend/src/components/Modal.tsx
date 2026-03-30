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
            <div className="fixed inset-0 z-50 bg-black/40" onClick={onClose} />

            {/* Panel */}
            <div
                className="fixed inset-4 z-50 flex flex-col bg-white rounded-xl shadow-2xl"
                onClick={e => e.stopPropagation()}
            >
                {/* Header */}
                <div className="flex items-center justify-between px-5 py-3 border-b border-gray-200 shrink-0">
                    <h2 className="text-base font-semibold text-gray-700 truncate">{title}</h2>
                    <div className="flex items-center gap-3 shrink-0">
                        {headerActions}
                        <button
                            onClick={onClose}
                            className="p-1 text-gray-400 hover:text-gray-600 rounded hover:bg-gray-100"
                            aria-label="Cerrar"
                        >
                            <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                        </button>
                    </div>
                </div>

                {/* Body */}
                <div className="flex-1 overflow-auto p-4 min-h-0">
                    {children}
                </div>
            </div>
        </>,
        document.body,
    );
}
