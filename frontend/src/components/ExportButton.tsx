const DOWNLOAD_ICON = "M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z";

const VARIANTS = {
    excel: {
        bg: 'bg-[#058527]',
        hover: 'hover:bg-[#046d20]',
        chipColor: 'text-[#058527]',
        label: 'Excel',
    },
    pdf: {
        bg: 'bg-accent',
        hover: 'hover:bg-accent-hover',
        chipColor: 'text-accent',
        label: 'PDF',
    },
    all: {
        bg: 'bg-[#404040]',
        hover: 'hover:bg-[#333333]',
        chipColor: 'text-txt-secondary',
        label: 'Todo',
    },
} as const;

type Variant = keyof typeof VARIANTS;

interface ExportButtonProps {
    variant: Variant;
    onClick: () => void;
    disabled?: boolean;
    /** Override the default label */
    label?: string;
    /** "default" = filled inline button, "chip" = outlined chip */
    size?: 'default' | 'chip';
}

export default function ExportButton({ variant, onClick, disabled, label, size = 'default' }: ExportButtonProps) {
    const v = VARIANTS[variant];

    if (size === 'chip') {
        return (
            <button
                onClick={onClick}
                disabled={disabled}
                title={`Exportar ${v.label}`}
                className={`export-chip ${v.chipColor}
                            disabled:opacity-40 disabled:cursor-not-allowed`}
            >
                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={DOWNLOAD_ICON} />
                </svg>
                {label ?? v.label}
            </button>
        );
    }

    return (
        <button
            onClick={onClick}
            disabled={disabled}
            title={`Exportar ${v.label}`}
            className={`inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium
                        text-white rounded-md transition-colors
                        disabled:opacity-40 disabled:cursor-not-allowed
                        ${v.bg} ${disabled ? '' : v.hover}`}
        >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d={DOWNLOAD_ICON} />
            </svg>
            {label ?? v.label}
        </button>
    );
}
