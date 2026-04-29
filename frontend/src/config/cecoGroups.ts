import type { ReportRow } from '@/types';

// ── CUENTA_CONTABLE grouping by 2-digit prefix ──────────────────────

export const CUENTA_PREFIX_LABELS: Record<string, string> = {
    '61': 'Variacion de Inventario',
    '62': 'Gasto de Personal',
    '63': 'Servicios prestados por Terceros',
    '64': 'Gastos por Tributos',
    '65': 'Otros Gastos de Gestion',
    '67': 'Gastos Financieros',
    '68': 'Deterioro de Activos',
};

export const KNOWN_PREFIXES = Object.keys(CUENTA_PREFIX_LABELS);

export const FILTER_OPTIONS: { value: string; label: string }[] = [
    { value: 'all', label: 'Todas' },
    ...KNOWN_PREFIXES.map(p => ({ value: p, label: `${p}: ${CUENTA_PREFIX_LABELS[p]}` })),
];

export function getCuentaPrefix(cuenta: string): string | null {
    const prefix = cuenta.substring(0, 2);
    return KNOWN_PREFIXES.includes(prefix) ? prefix : null;
}

export function getCuentaPrefixAny(cuenta: string | null | undefined): string {
    return String(cuenta ?? '').substring(0, 2) || '—';
}

// ── Cuenta category structures ───────────────────────────────────────

export interface CuentaCategory {
    prefix: string;
    label: string;
    data: ReportRow;
    cuentaRows: ReportRow[];
}

export interface UngroupedCuenta {
    prefix: null;
    row: ReportRow;
}

export type CuentaEntry = CuentaCategory | UngroupedCuenta;
