import type { ReportRow, DisplayColumn } from '@/types';

// ── Bold row sets (used by FinancialTable + Excel export) ────────────

export const BOLD_ROWS_PL = new Set([
    'INGRESOS TOTALES', 'UTILIDAD BRUTA', 'UTILIDAD OPERATIVA',
    'UTILIDAD ANTES DE IMPUESTO A LA RENTA', 'UTILIDAD NETA',
]);

export const BOLD_ROWS_BS = new Set([
    'TOTAL ACTIVO CORRIENTE', 'TOTAL ACTIVO NO CORRIENTE', 'TOTAL ACTIVO',
    'TOTAL PASIVO CORRIENTE', 'TOTAL PASIVO NO CORRIENTE', 'TOTAL PASIVO',
    'TOTAL PATRIMONIO', 'TOTAL PASIVO Y PATRIMONIO',
]);

// ── Cell value computation ───────────────────────────────────────────

export function getCellValue(row: ReportRow, col: DisplayColumn): number | null {
    if (col.useLastOnly) {
        // BS quarterly: use only the last month (end-of-quarter balance)
        const lastMonth = col.sourceMonths[col.sourceMonths.length - 1];
        return (row[lastMonth] as number | null) ?? null;
    }
    // P&L or monthly: sum all source months
    let sum = 0;
    let allNull = true;
    for (const m of col.sourceMonths) {
        const v = row[m] as number | null;
        if (v !== null && v !== undefined) {
            sum += v;
            allNull = false;
        }
    }
    return allNull ? null : sum;
}

// ── Total column computation ─────────────────────────────────────────

/** Summary table total (P&L: precomputed or sum; BS: last column value) */
export function getSummaryTotal(row: ReportRow, columns: DisplayColumn[], variant: 'pl' | 'bs'): number | null {
    if (variant === 'bs') {
        // BS total = last column's value (last month/quarter balance)
        const lastCol = columns[columns.length - 1];
        return getCellValue(row, lastCol);
    }
    // P&L total: check if row has a precomputed TOTAL, otherwise sum columns
    const precomputed = row['TOTAL'] as number | null;
    if (precomputed !== null && precomputed !== undefined) return precomputed;
    let sum = 0;
    let allNull = true;
    for (const col of columns) {
        const v = getCellValue(row, col);
        if (v !== null) { sum += v; allNull = false; }
    }
    return allNull ? null : sum;
}

/** Detail table total (precomputed TOTAL first, then sum) */
export function getDetailTotal(row: ReportRow, columns: DisplayColumn[]): number | null {
    const precomputed = row['TOTAL'] as number | null;
    if (precomputed !== null && precomputed !== undefined) return precomputed;
    let sum = 0;
    let allNull = true;
    for (const col of columns) {
        const v = getCellValue(row, col);
        if (v !== null) { sum += v; allNull = false; }
    }
    return allNull ? null : sum;
}
