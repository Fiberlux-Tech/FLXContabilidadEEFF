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
  pl_summary: ReportRow[];
  bs_summary: ReportRow[];
  ingresos_ordinarios: ReportRow[];
  ingresos_proyectos: ReportRow[];
  costo: ReportRow[];
  gasto_venta: ReportRow[];
  gasto_admin: ReportRow[];
  dya_costo: ReportRow[];
  dya_gasto: ReportRow[];
  resultado_financiero_ingresos: ReportRow[];
  resultado_financiero_gastos: ReportRow[];
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
  months: string[];
}

/** Response from /api/data/load-pl (everything except bs_summary) */
export type PLReportData = Omit<ReportData, 'bs_summary'>;

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
  months: string[];
}

export type Granularity = 'monthly' | 'quarterly';
export type PeriodRange = 'ytd' | 'trailing12';

/** A display column: the header shown in the table + the source month keys to aggregate */
export interface DisplayColumn {
  header: string;
  /** For monthly: single month key (e.g. "JAN"). For quarterly: 3 month keys (e.g. ["JAN","FEB","MAR"]) */
  sourceMonths: string[];
  /** For quarterly BS: only use the last month (end-of-quarter balance), not sum */
  useLastOnly?: boolean;
}

/** Metadata about which year each source month belongs to (for trailing 12M drill-down) */
export interface MonthSource {
  month: string;   // e.g. "APR"
  year: number;    // e.g. 2025
}
