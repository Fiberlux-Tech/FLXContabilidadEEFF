/**
 * View registry — single source of truth for all dashboard views.
 *
 * Adding a new view:
 *   1. Add an entry here (id, title, navLabel, category).
 *   2. Add table config in viewConfigs.ts (if it's a note view).
 *   3. Add render logic in MainContent.tsx (only if it needs a custom component).
 *
 * The View type, sidebar navigation arrays, and title map are all derived
 * from this registry — no other file needs manual updates for metadata.
 */

export type ViewCategory = 'pl' | 'bs' | 'analysis' | 'uploads';

export interface ViewEntry {
    id: string;
    title: string;
    navLabel: string;
    category: ViewCategory;
}

const VIEW_REGISTRY = [
    // ── Estado de Resultados ────────────────────────────────────
    { id: 'pl',                     title: 'Estado de Resultados',                navLabel: 'Resumen',                     category: 'pl' },
    { id: 'ingresos',               title: 'Ingresos',                            navLabel: 'Ingresos',                    category: 'pl' },
    { id: 'costo',                  title: 'Costo de Operaciones',                navLabel: 'Costo de Operaciones',        category: 'pl' },
    { id: 'gasto_venta',            title: 'Gastos de Ventas',                    navLabel: 'Gastos de Ventas',            category: 'pl' },
    { id: 'gasto_admin',            title: 'Gastos de Administracion',            navLabel: 'Gastos de Administracion',    category: 'pl' },
    { id: 'otros_egresos',          title: 'Otros Egresos',                       navLabel: 'Otros Egresos',               category: 'pl' },
    { id: 'dya',                    title: 'Depreciacion y Amortizacion',         navLabel: 'Depreciacion y Amortizacion', category: 'pl' },
    { id: 'resultado_financiero',   title: 'Resultado Financiero',                navLabel: 'Resultado Financiero',        category: 'pl' },

    // ── Balance General ─────────────────────────────────────────
    { id: 'bs',                     title: 'Balance General',                     navLabel: 'Resumen',                     category: 'bs' },
    { id: 'bs_efectivo',            title: 'Efectivo y Equivalentes',             navLabel: 'Efectivo y Equivalentes',     category: 'bs' },
    { id: 'bs_cxc_comerciales',     title: 'Cuentas por Cobrar Comerciales',      navLabel: 'CxC Comerciales',             category: 'bs' },
    { id: 'bs_cxc_otras',           title: 'Otras Cuentas por Cobrar',            navLabel: 'Otras CxC',                  category: 'bs' },
    { id: 'bs_cxc_relacionadas',    title: 'Cuentas por Cobrar Relacionadas',     navLabel: 'CxC Relacionadas',            category: 'bs' },
    { id: 'bs_ppe',                 title: 'Propiedad, Planta, Equipo e Intangibles', navLabel: 'PPE e Intangibles',       category: 'bs' },
    { id: 'bs_otros_activos',       title: 'Otros Activos',                       navLabel: 'Otros Activos',               category: 'bs' },
    { id: 'bs_cxp_comerciales',     title: 'Cuentas por Pagar Comerciales',       navLabel: 'CxP Comerciales',             category: 'bs' },
    { id: 'bs_cxp_otras',           title: 'Otras Cuentas por Pagar',             navLabel: 'Otras CxP',                  category: 'bs' },
    { id: 'bs_cxp_relacionadas',    title: 'Cuentas por Pagar Relacionadas',      navLabel: 'CxP Relacionadas',            category: 'bs' },
    { id: 'bs_provisiones',         title: 'Provisiones por Beneficios a Empleados', navLabel: 'Provisiones',              category: 'bs' },
    { id: 'bs_tributos',            title: 'Tributos por Pagar',                  navLabel: 'Tributos',                   category: 'bs' },

    // ── Analisis ────────────────────────────────────────────────
    { id: 'analysis_pl_finanzas',   title: 'P&L - Finanzas',                     navLabel: 'P&L - Finanzas',              category: 'analysis' },
    { id: 'analysis_planilla',      title: 'Analisis de Planilla',               navLabel: 'Analisis de Planilla',        category: 'analysis' },
    { id: 'analysis_proveedores',   title: 'Analisis de Proveedores',            navLabel: 'Analisis de Proveedores',     category: 'analysis' },

    // ── Carga de Datos ─────────────────────────────────────────
    { id: 'upload_planilla',        title: 'Cargar Planilla',                    navLabel: 'Cargar Planilla',             category: 'uploads' },
] as const satisfies readonly ViewEntry[];

// ── Derived types ───────────────────────────────────────────────────────

/** Union of all valid view id strings. */
export type View = (typeof VIEW_REGISTRY)[number]['id'];

/** All view IDs as a runtime array. */
export const ALL_VIEW_IDS: readonly View[] = VIEW_REGISTRY.map(v => v.id);

// ── Derived lookups ─────────────────────────────────────────────────────

/** Map view id → display title (for TopBar / headers). */
export const VIEW_TITLE_MAP: Record<View, string> =
    Object.fromEntries(VIEW_REGISTRY.map(v => [v.id, v.title])) as Record<View, string>;

/** Sidebar nav items per category, preserving registry order. */
export const PL_NAV_ITEMS = VIEW_REGISTRY.filter(v => v.category === 'pl').map(v => ({ view: v.id as View, label: v.navLabel }));
export const BS_NAV_ITEMS = VIEW_REGISTRY.filter(v => v.category === 'bs').map(v => ({ view: v.id as View, label: v.navLabel }));
export const ANALYSIS_NAV_ITEMS = VIEW_REGISTRY.filter(v => v.category === 'analysis').map(v => ({ view: v.id as View, label: v.navLabel }));
export const UPLOADS_NAV_ITEMS = VIEW_REGISTRY.filter(v => v.category === 'uploads').map(v => ({ view: v.id as View, label: v.navLabel }));

// ── Category helpers ────────────────────────────────────────────────────

const _BS_IDS = new Set(VIEW_REGISTRY.filter(v => v.category === 'bs').map(v => v.id));
const _ANALYSIS_IDS = new Set(VIEW_REGISTRY.filter(v => v.category === 'analysis').map(v => v.id));
const _UPLOADS_IDS = new Set(VIEW_REGISTRY.filter(v => v.category === 'uploads').map(v => v.id));

export function isBsView(view: View): boolean {
    return _BS_IDS.has(view);
}

export function isAnalysisView(view: View): boolean {
    return _ANALYSIS_IDS.has(view);
}

export function isUploadsView(view: View): boolean {
    return _UPLOADS_IDS.has(view);
}
