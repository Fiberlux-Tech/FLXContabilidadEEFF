export const ALL_MONTHS = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN', 'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC'] as const;
export type Month = typeof ALL_MONTHS[number];

export interface User {
  id: number;
  username: string;
  display_name: string;
}

export interface CompanyMeta {
  legal_name: string;
  ruc: string;
}

export type CompanyMap = Record<string, CompanyMeta>;

export interface ReportRow {
  [key: string]: string | number | null;
}

export interface CellSelection {
  partida: string;
  month: string | null;
  filterCol: string | null;
  filterVal: string | null;
  label: string;
}

export interface TableConfig {
  title: string;
  rows: ReportRow[];
  labelKeys: string[];
  headerLabels: string[];
  partida: string;
  filterCol: string;
}

export interface ReportData {
  // Always present (from load-pl summary)
  pl_summary: ReportRow[];
  pl_summary_ex_ic: ReportRow[];
  pl_summary_only_ic: ReportRow[];
  bs_summary: ReportRow[];
  company: string;
  year: number;
  months: Month[];
  // P&L detail sections (lazy-loaded on demand via /api/data/pl-section)
  ingresos_ordinarios?: ReportRow[];
  ingresos_ordinarios_ex_ic?: ReportRow[];
  ingresos_ordinarios_only_ic?: ReportRow[];
  ingresos_proyectos?: ReportRow[];
  ingresos_proyectos_ex_ic?: ReportRow[];
  ingresos_proyectos_only_ic?: ReportRow[];
  costo?: ReportRow[];
  costo_ex_ic?: ReportRow[];
  costo_only_ic?: ReportRow[];
  costo_by_cuenta?: ReportRow[];
  costo_by_cuenta_ex_ic?: ReportRow[];
  costo_by_cuenta_only_ic?: ReportRow[];
  gasto_venta?: ReportRow[];
  gasto_venta_ex_ic?: ReportRow[];
  gasto_venta_only_ic?: ReportRow[];
  gasto_venta_by_cuenta?: ReportRow[];
  gasto_venta_by_cuenta_ex_ic?: ReportRow[];
  gasto_venta_by_cuenta_only_ic?: ReportRow[];
  gasto_admin?: ReportRow[];
  gasto_admin_ex_ic?: ReportRow[];
  gasto_admin_only_ic?: ReportRow[];
  gasto_admin_by_cuenta?: ReportRow[];
  gasto_admin_by_cuenta_ex_ic?: ReportRow[];
  gasto_admin_by_cuenta_only_ic?: ReportRow[];
  dya_costo?: ReportRow[];
  dya_costo_ex_ic?: ReportRow[];
  dya_costo_only_ic?: ReportRow[];
  dya_costo_by_cuenta?: ReportRow[];
  dya_costo_by_cuenta_ex_ic?: ReportRow[];
  dya_costo_by_cuenta_only_ic?: ReportRow[];
  dya_gasto?: ReportRow[];
  dya_gasto_ex_ic?: ReportRow[];
  dya_gasto_only_ic?: ReportRow[];
  dya_gasto_by_cuenta?: ReportRow[];
  dya_gasto_by_cuenta_ex_ic?: ReportRow[];
  dya_gasto_by_cuenta_only_ic?: ReportRow[];
  otros_ingresos?: ReportRow[];
  otros_ingresos_ex_ic?: ReportRow[];
  otros_ingresos_only_ic?: ReportRow[];
  otros_egresos?: ReportRow[];
  otros_egresos_ex_ic?: ReportRow[];
  otros_egresos_only_ic?: ReportRow[];
  otros_egresos_by_cuenta?: ReportRow[];
  otros_egresos_by_cuenta_ex_ic?: ReportRow[];
  otros_egresos_by_cuenta_only_ic?: ReportRow[];
  resultado_financiero_ingresos?: ReportRow[];
  resultado_financiero_ingresos_ex_ic?: ReportRow[];
  resultado_financiero_ingresos_only_ic?: ReportRow[];
  resultado_financiero_gastos?: ReportRow[];
  resultado_financiero_gastos_ex_ic?: ReportRow[];
  resultado_financiero_gastos_only_ic?: ReportRow[];
  otros_ingresos_by_cuenta?: ReportRow[];
  otros_ingresos_by_cuenta_ex_ic?: ReportRow[];
  otros_ingresos_by_cuenta_only_ic?: ReportRow[];
  participacion_by_cuenta?: ReportRow[];
  participacion_by_cuenta_ex_ic?: ReportRow[];
  participacion_by_cuenta_only_ic?: ReportRow[];
  provision_by_cuenta?: ReportRow[];
  provision_by_cuenta_ex_ic?: ReportRow[];
  provision_by_cuenta_only_ic?: ReportRow[];
  planilla_by_cuenta?: ReportRow[];
  planilla_by_cuenta_ex_ic?: ReportRow[];
  planilla_by_cuenta_only_ic?: ReportRow[];
  revenue_by_cuenta?: ReportRow[];
  revenue_by_cuenta_ex_ic?: ReportRow[];
  revenue_by_cuenta_only_ic?: ReportRow[];
  proveedores_transporte?: ReportRow[];
  proveedores_cecos?: ReportRow[];
  // Proxy Flujo de Caja
  flujo_ingresos_ord_by_cuenta?: ReportRow[];
  flujo_ingresos_ord_by_cuenta_ex_ic?: ReportRow[];
  flujo_ingresos_ord_by_cuenta_only_ic?: ReportRow[];
  flujo_ingresos_proy_by_cuenta?: ReportRow[];
  flujo_ingresos_proy_by_cuenta_ex_ic?: ReportRow[];
  flujo_ingresos_proy_by_cuenta_only_ic?: ReportRow[];
  flujo_costo_by_cuenta?: ReportRow[];
  flujo_costo_by_cuenta_ex_ic?: ReportRow[];
  flujo_costo_by_cuenta_only_ic?: ReportRow[];
  flujo_gasto_venta_by_cuenta?: ReportRow[];
  flujo_gasto_venta_by_cuenta_ex_ic?: ReportRow[];
  flujo_gasto_venta_by_cuenta_only_ic?: ReportRow[];
  flujo_gasto_admin_by_cuenta?: ReportRow[];
  flujo_gasto_admin_by_cuenta_ex_ic?: ReportRow[];
  flujo_gasto_admin_by_cuenta_only_ic?: ReportRow[];
  flujo_participacion_by_cuenta?: ReportRow[];
  flujo_participacion_by_cuenta_ex_ic?: ReportRow[];
  flujo_participacion_by_cuenta_only_ic?: ReportRow[];
  flujo_otros_ingresos_by_cuenta?: ReportRow[];
  flujo_otros_ingresos_by_cuenta_ex_ic?: ReportRow[];
  flujo_otros_ingresos_by_cuenta_only_ic?: ReportRow[];
  flujo_otros_egresos_by_cuenta?: ReportRow[];
  flujo_otros_egresos_by_cuenta_ex_ic?: ReportRow[];
  flujo_otros_egresos_by_cuenta_only_ic?: ReportRow[];
  // BS note detail tables (lazy-loaded via /api/data/load-bs)
  bs_efectivo?: ReportRow[];
  bs_cxc_comerciales?: ReportRow[];
  bs_cxc_comerciales_nit_top20?: ReportRow[];
  bs_cxc_otras?: ReportRow[];
  bs_cxc_otras_nit_top20?: ReportRow[];
  bs_cxc_relacionadas?: ReportRow[];
  bs_ppe?: ReportRow[];
  bs_ppe_depreciacion?: ReportRow[];
  bs_intangible?: ReportRow[];
  bs_intangible_amortizacion?: ReportRow[];
  bs_otros_activos?: ReportRow[];
  bs_cxp_comerciales?: ReportRow[];
  bs_cxp_comerciales_nit_top20?: ReportRow[];
  bs_cxp_otras?: ReportRow[];
  bs_cxp_otras_nit_top20?: ReportRow[];
  bs_cxp_relacionadas?: ReportRow[];
  bs_provisiones?: ReportRow[];
  bs_tributos?: ReportRow[];
}

/** Response from /api/data/load-pl (summary only — detail sections loaded separately) */
export type PLReportData = Pick<ReportData, 'pl_summary' | 'pl_summary_ex_ic' | 'pl_summary_only_ic' | 'company' | 'year' | 'months'>;

/** Response from /api/data/pl-section (partial detail data) */
export type PLSectionData = Partial<ReportData>;

/** Response from /api/data/load-bs */
export interface BSReportData {
  bs_summary: ReportRow[];
  // BS note detail tables
  bs_efectivo: ReportRow[];
  bs_cxc_comerciales: ReportRow[];
  bs_cxc_comerciales_nit_top20: ReportRow[];
  bs_cxc_otras: ReportRow[];
  bs_cxc_otras_nit_top20: ReportRow[];
  bs_cxc_relacionadas: ReportRow[];
  bs_ppe: ReportRow[];
  bs_ppe_depreciacion: ReportRow[];
  bs_intangible: ReportRow[];
  bs_intangible_amortizacion: ReportRow[];
  bs_otros_activos: ReportRow[];
  bs_cxp_comerciales: ReportRow[];
  bs_cxp_comerciales_nit_top20: ReportRow[];
  bs_cxp_otras: ReportRow[];
  bs_cxp_otras_nit_top20: ReportRow[];
  bs_cxp_relacionadas: ReportRow[];
  bs_provisiones: ReportRow[];
  bs_tributos: ReportRow[];
  company: string;
  year: number;
  months: Month[];
}

export type Granularity = 'monthly' | 'quarterly';
export type PeriodRange = 'ytd' | 'trailing12';

/** A display column: the header shown in the table + the source month keys to aggregate */
export interface DisplayColumn {
  header: string;
  /** For monthly: single month key (e.g. "JAN"). For quarterly: 3 month keys (e.g. ["JAN","FEB","MAR"]) */
  sourceMonths: Month[];
  /** For quarterly BS: only use the last month (end-of-quarter balance), not sum */
  useLastOnly?: boolean;
}

/** Metadata about which year each source month belongs to (for trailing 12M drill-down) */
export interface MonthSource {
  month: Month;
  year: number;
}
