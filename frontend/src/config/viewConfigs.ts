import type { View } from '@/contexts/ReportContext';
import type { ReportData, TableConfig, ReportRow } from '@/types';

// ── View title map ───────────────────────────────────────────────────

export const VIEW_TITLE_MAP: Record<View, string> = {
    pl: 'Estado de Resultados',
    bs: 'Balance General',
    ingresos: 'Ingresos',
    costo: 'Costo de Operaciones',
    gasto_venta: 'Gastos de Ventas',
    gasto_admin: 'Gastos de Administracion',
    dya: 'Depreciacion y Amortizacion',
    resultado_financiero: 'Resultado Financiero',
    bs_efectivo: 'Efectivo y Equivalentes',
    bs_cxc_comerciales: 'Cuentas por Cobrar Comerciales',
    bs_cxc_otras: 'Otras Cuentas por Cobrar',
};

// ── Note view table configs ──────────────────────────────────────────

export type NoteView = 'ingresos' | 'costo' | 'gasto_venta' | 'gasto_admin' | 'dya' | 'resultado_financiero'
    | 'bs_efectivo' | 'bs_cxc_comerciales' | 'bs_cxc_otras';

export interface NoteViewConfig {
    tables: (d: ReportData) => TableConfig[];
    labelKeys: string[];
}

export const VIEW_TABLE_CONFIGS: Record<NoteView, NoteViewConfig> = {
    ingresos: {
        tables: (d) => [
            { title: 'Ingresos Ordinarios', rows: d.ingresos_ordinarios, labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'INGRESOS ORDINARIOS', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Ingresos de Proyectos', rows: d.ingresos_proyectos, labelKeys: ['NIT', 'RAZON_SOCIAL'], headerLabels: ['NIT', 'Razon Social'], partida: 'INGRESOS PROYECTOS', filterCol: 'NIT' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    costo: {
        tables: (d) => [
            { title: 'Costo de Operaciones', rows: d.costo, labelKeys: ['CENTRO_COSTO', 'DESC_CECO'], headerLabels: ['CC', 'Centro de Costo'], partida: 'COSTO', filterCol: 'CENTRO_COSTO' },
        ],
        labelKeys: ['CENTRO_COSTO', 'DESC_CECO'],
    },
    gasto_venta: {
        tables: (d) => [
            { title: 'Gastos de Ventas', rows: d.gasto_venta, labelKeys: ['CENTRO_COSTO', 'DESC_CECO'], headerLabels: ['CC', 'Centro de Costo'], partida: 'GASTO VENTA', filterCol: 'CENTRO_COSTO' },
        ],
        labelKeys: ['CENTRO_COSTO', 'DESC_CECO'],
    },
    gasto_admin: {
        tables: (d) => [
            { title: 'Gastos de Administracion', rows: d.gasto_admin, labelKeys: ['CENTRO_COSTO', 'DESC_CECO'], headerLabels: ['CC', 'Centro de Costo'], partida: 'GASTO ADMIN', filterCol: 'CENTRO_COSTO' },
        ],
        labelKeys: ['CENTRO_COSTO', 'DESC_CECO'],
    },
    dya: {
        tables: (d) => [
            { title: 'Depreciacion y Amortizacion (Costo)', rows: d.dya_costo, labelKeys: ['CENTRO_COSTO', 'DESC_CECO'], headerLabels: ['CC', 'Centro de Costo'], partida: 'D&A - COSTO', filterCol: 'CENTRO_COSTO' },
            { title: 'Depreciacion y Amortizacion (Gasto)', rows: d.dya_gasto, labelKeys: ['CENTRO_COSTO', 'DESC_CECO'], headerLabels: ['CC', 'Centro de Costo'], partida: 'D&A - GASTO', filterCol: 'CENTRO_COSTO' },
        ],
        labelKeys: ['CENTRO_COSTO', 'DESC_CECO'],
    },
    resultado_financiero: {
        tables: (d) => [
            { title: 'Ingresos Financieros', rows: d.resultado_financiero_ingresos, labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'RESULTADO FINANCIERO', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Gastos Financieros', rows: d.resultado_financiero_gastos, labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'RESULTADO FINANCIERO', filterCol: 'CUENTA_CONTABLE' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },

    // ── BS note views ───────────────────────────────────────────────────
    bs_efectivo: {
        tables: (d) => [
            { title: 'Efectivo y Equivalentes de Efectivo', rows: d.bs_efectivo ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Efectivo y equivalentes de efectivo', filterCol: 'CUENTA_CONTABLE' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    bs_cxc_comerciales: {
        tables: (d) => [
            { title: 'Cuentas por Cobrar Comerciales', rows: d.bs_cxc_comerciales ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Cuentas por cobrar comerciales (neto)', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Top 20 por NIT', rows: d.bs_cxc_comerciales_nit_top20 ?? [], labelKeys: ['NIT', 'RAZON_SOCIAL'], headerLabels: ['NIT', 'Razon Social'], partida: 'Cuentas por cobrar comerciales (neto)', filterCol: 'NIT' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    bs_cxc_otras: {
        tables: (d) => [
            { title: 'Otras Cuentas por Cobrar', rows: d.bs_cxc_otras ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Otras cuentas por cobrar (neto)', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Top 20 por NIT', rows: d.bs_cxc_otras_nit_top20 ?? [], labelKeys: ['NIT', 'RAZON_SOCIAL'], headerLabels: ['NIT', 'Razon Social'], partida: 'Otras cuentas por cobrar (neto)', filterCol: 'NIT' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
};

// ── Helpers ──────────────────────────────────────────────────────────

export const ALL_MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'];

/** Check if a table has all-zero/null values (should be hidden) */
export function isAllZeroTable(rows: ReportRow[], months: string[]): boolean {
    if (rows.length === 0) return true;
    for (const row of rows) {
        for (const m of months) {
            const v = row[m] as number | null;
            if (v !== null && v !== undefined && v !== 0) return false;
        }
        const total = row['TOTAL'] as number | null;
        if (total !== null && total !== undefined && total !== 0) return false;
    }
    return true;
}
