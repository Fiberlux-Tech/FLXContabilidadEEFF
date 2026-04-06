import type { ReportData, ReportRow, TableConfig } from '@/types';

/** Map a TableConfig back to the ReportData key via reference equality */
export function getDataKeyForTable(table: TableConfig, data: ReportData): keyof ReportData | null {
    const mapping: [keyof ReportData, ReportRow[]][] = [
        // P&L notes
        ['ingresos_ordinarios', data.ingresos_ordinarios],
        ['ingresos_proyectos', data.ingresos_proyectos],
        ['costo', data.costo],
        ['costo_by_cuenta', data.costo_by_cuenta],
        ['gasto_venta', data.gasto_venta],
        ['gasto_venta_by_cuenta', data.gasto_venta_by_cuenta],
        ['gasto_admin', data.gasto_admin],
        ['gasto_admin_by_cuenta', data.gasto_admin_by_cuenta],
        ['dya_costo', data.dya_costo],
        ['dya_costo_by_cuenta', data.dya_costo_by_cuenta],
        ['dya_gasto', data.dya_gasto],
        ['dya_gasto_by_cuenta', data.dya_gasto_by_cuenta],
        ['otros_egresos', data.otros_egresos],
        ['otros_egresos_by_cuenta', data.otros_egresos_by_cuenta],
        ['planilla_by_cuenta', data.planilla_by_cuenta],
        ['resultado_financiero_ingresos', data.resultado_financiero_ingresos],
        ['resultado_financiero_gastos', data.resultado_financiero_gastos],
        ['otros_ingresos_by_cuenta', data.otros_ingresos_by_cuenta],
        ['participacion_by_cuenta', data.participacion_by_cuenta],
        ['provision_by_cuenta', data.provision_by_cuenta],
        // BS notes
        ['bs_efectivo', data.bs_efectivo],
        ['bs_cxc_comerciales', data.bs_cxc_comerciales],
        ['bs_cxc_comerciales_nit_top20', data.bs_cxc_comerciales_nit_top20],
        ['bs_cxc_otras', data.bs_cxc_otras],
        ['bs_cxc_otras_nit_top20', data.bs_cxc_otras_nit_top20],
        ['bs_cxc_relacionadas', data.bs_cxc_relacionadas],
        ['bs_ppe', data.bs_ppe],
        ['bs_ppe_depreciacion', data.bs_ppe_depreciacion],
        ['bs_intangible', data.bs_intangible],
        ['bs_intangible_amortizacion', data.bs_intangible_amortizacion],
        ['bs_otros_activos', data.bs_otros_activos],
        ['bs_cxp_comerciales', data.bs_cxp_comerciales],
        ['bs_cxp_comerciales_nit_top20', data.bs_cxp_comerciales_nit_top20],
        ['bs_cxp_otras', data.bs_cxp_otras],
        ['bs_cxp_otras_nit_top20', data.bs_cxp_otras_nit_top20],
        ['bs_cxp_relacionadas', data.bs_cxp_relacionadas],
        ['bs_provisiones', data.bs_provisiones],
        ['bs_tributos', data.bs_tributos],
    ];
    for (const [key, rows] of mapping) {
        if (table.rows === rows) return key;
    }
    return null;
}
