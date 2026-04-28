import { ALL_MONTHS } from '@/types';
import type { ReportData, TableConfig, ReportRow, Month } from '@/types';

export { VIEW_TITLE_MAP } from '@/config/viewRegistry';

// ── Note view table configs ──────────────────────────────────────────

export type NoteView = 'ingresos' | 'costo' | 'gasto_venta' | 'gasto_admin' | 'otros_egresos' | 'dya' | 'resultado_financiero' | 'diferencia_cambio'
    | 'bs_efectivo' | 'bs_cxc_comerciales' | 'bs_cxc_otras' | 'bs_cxc_relacionadas'
    | 'bs_ppe' | 'bs_otros_activos'
    | 'bs_cxp_comerciales' | 'bs_cxp_otras' | 'bs_cxp_relacionadas'
    | 'bs_provisiones' | 'bs_tributos';

export interface NoteViewConfig {
    tables: (d: ReportData) => TableConfig[];
    labelKeys: string[];
}

export const VIEW_TABLE_CONFIGS: Record<NoteView, NoteViewConfig> = {
    ingresos: {
        tables: (d) => [
            { title: 'Ingresos Ordinarios', rows: d.ingresos_ordinarios ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'INGRESOS ORDINARIOS', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Ingresos de Proyectos', rows: d.ingresos_proyectos ?? [], labelKeys: ['NIT', 'RAZON_SOCIAL'], headerLabels: ['NIT', 'Razon Social'], partida: 'INGRESOS PROYECTOS', filterCol: 'NIT' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    costo: {
        tables: (d) => [
            { title: 'Costo de Operaciones', rows: d.costo ?? [], labelKeys: ['CENTRO_COSTO', 'DESC_CECO'], headerLabels: ['CC', 'Centro de Costo'], partida: 'COSTO', filterCol: 'CENTRO_COSTO' },
        ],
        labelKeys: ['CENTRO_COSTO', 'DESC_CECO'],
    },
    gasto_venta: {
        tables: (d) => [
            { title: 'Gastos de Ventas', rows: d.gasto_venta ?? [], labelKeys: ['CENTRO_COSTO', 'DESC_CECO'], headerLabels: ['CC', 'Centro de Costo'], partida: 'GASTO VENTA', filterCol: 'CENTRO_COSTO' },
        ],
        labelKeys: ['CENTRO_COSTO', 'DESC_CECO'],
    },
    gasto_admin: {
        tables: (d) => [
            { title: 'Gastos de Administracion', rows: d.gasto_admin ?? [], labelKeys: ['CENTRO_COSTO', 'DESC_CECO'], headerLabels: ['CC', 'Centro de Costo'], partida: 'GASTO ADMIN', filterCol: 'CENTRO_COSTO' },
        ],
        labelKeys: ['CENTRO_COSTO', 'DESC_CECO'],
    },
    otros_egresos: {
        tables: (d) => [
            { title: 'Otros Ingresos', rows: d.otros_ingresos ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'OTROS INGRESOS', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Otros Egresos', rows: d.otros_egresos ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'OTROS EGRESOS', filterCol: 'CUENTA_CONTABLE' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    dya: {
        tables: (d) => [
            { title: 'Depreciacion y Amortizacion (Costo)', rows: d.dya_costo ?? [], labelKeys: ['CENTRO_COSTO', 'DESC_CECO'], headerLabels: ['CC', 'Centro de Costo'], partida: 'D&A - COSTO', filterCol: 'CENTRO_COSTO' },
            { title: 'Depreciacion y Amortizacion (Gasto)', rows: d.dya_gasto ?? [], labelKeys: ['CENTRO_COSTO', 'DESC_CECO'], headerLabels: ['CC', 'Centro de Costo'], partida: 'D&A - GASTO', filterCol: 'CENTRO_COSTO' },
        ],
        labelKeys: ['CENTRO_COSTO', 'DESC_CECO'],
    },
    resultado_financiero: {
        tables: (d) => [
            { title: 'Ingresos Financieros', rows: d.resultado_financiero_ingresos ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'RESULTADO FINANCIERO', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Gastos Financieros', rows: d.resultado_financiero_gastos ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'RESULTADO FINANCIERO', filterCol: 'CUENTA_CONTABLE' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    diferencia_cambio: {
        tables: (d) => [
            { title: 'Ingresos por Diferencia de Cambio', rows: d.diferencia_cambio_ingresos ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'DIFERENCIA DE CAMBIO', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Gastos por Diferencia de Cambio', rows: d.diferencia_cambio_gastos ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'DIFERENCIA DE CAMBIO', filterCol: 'CUENTA_CONTABLE' },
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
    bs_cxc_relacionadas: {
        tables: (d) => [
            { title: 'Cuentas por Cobrar Relacionadas', rows: d.bs_cxc_relacionadas ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Otras cuentas por cobrar relacionadas', filterCol: 'CUENTA_CONTABLE' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    bs_ppe: {
        tables: (d) => [
            { title: 'Propiedades, Planta y Equipo', rows: d.bs_ppe ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Propiedades, planta y equipo (neto)', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Depreciacion', rows: d.bs_ppe_depreciacion ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Propiedades, planta y equipo (neto)', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Intangible', rows: d.bs_intangible ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Intangible', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Amortizacion', rows: d.bs_intangible_amortizacion ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Intangible', filterCol: 'CUENTA_CONTABLE' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    bs_otros_activos: {
        tables: (d) => [
            { title: 'Otros Activos', rows: d.bs_otros_activos ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Otros Activos', filterCol: 'CUENTA_CONTABLE' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    bs_cxp_comerciales: {
        tables: (d) => [
            { title: 'Cuentas por Pagar Comerciales', rows: d.bs_cxp_comerciales ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Cuentas por pagar comerciales', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Top 20 por NIT', rows: d.bs_cxp_comerciales_nit_top20 ?? [], labelKeys: ['NIT', 'RAZON_SOCIAL'], headerLabels: ['NIT', 'Razon Social'], partida: 'Cuentas por pagar comerciales', filterCol: 'NIT' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    bs_cxp_otras: {
        tables: (d) => [
            { title: 'Otras Cuentas por Pagar', rows: d.bs_cxp_otras ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Otras cuentas por pagar', filterCol: 'CUENTA_CONTABLE' },
            { title: 'Top 20 por NIT', rows: d.bs_cxp_otras_nit_top20 ?? [], labelKeys: ['NIT', 'RAZON_SOCIAL'], headerLabels: ['NIT', 'Razon Social'], partida: 'Otras cuentas por pagar', filterCol: 'NIT' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    bs_cxp_relacionadas: {
        tables: (d) => [
            { title: 'Cuentas por Pagar Relacionadas', rows: d.bs_cxp_relacionadas ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Otras cuentas por Pagar Relacionadas', filterCol: 'CUENTA_CONTABLE' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    bs_provisiones: {
        tables: (d) => [
            { title: 'Provisiones por Beneficios a Empleados', rows: d.bs_provisiones ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Provisiones por beneficios a empleados', filterCol: 'CUENTA_CONTABLE' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
    bs_tributos: {
        tables: (d) => [
            { title: 'Tributos por Pagar', rows: d.bs_tributos ?? [], labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'], headerLabels: ['Cuenta', 'Descripcion'], partida: 'Tributos por Pagar', filterCol: 'CUENTA_CONTABLE' },
        ],
        labelKeys: ['CUENTA_CONTABLE', 'DESCRIPCION'],
    },
};

// ── Helpers ──────────────────────────────────────────────────────────

export { ALL_MONTHS };

/** Check if a table has all-zero/null values (should be hidden) */
export function isAllZeroTable(rows: ReportRow[], months: readonly Month[]): boolean {
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
