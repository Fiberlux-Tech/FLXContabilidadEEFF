import { useMemo } from 'react';
import { useReport, isBsView } from '@/contexts/ReportContext';
import FinancialTable from '@/features/dashboard/FinancialTable';
import ExpandableFinancialTable from '@/features/dashboard/ExpandableFinancialTable';
import PlanillaTable from '@/features/dashboard/PlanillaTable';
import ProveedoresTable from '@/features/dashboard/ProveedoresTable';
import PLNoteView from '@/features/dashboard/PLNoteView';
import { useHeadcount } from '@/features/dashboard/useHeadcount';
import UploadPlanilla from '@/features/dashboard/UploadPlanilla';
import type { ReportData, TableConfig, ReportRow } from '@/types';
import { VIEW_TABLE_CONFIGS, ALL_MONTHS, isAllZeroTable, type NoteView } from '@/config/viewConfigs';
import { getDataKeyForTable } from '@/utils/dataKeyMapping';

export default function MainContent() {
    const {
        reportData, currentView, isLoading, error,
        getDisplayColumns, periodRange, getMergedRows, getMergedDetailRows,
        isBsLoading, bsError, selectedCompany, selectedYear,
    } = useReport();

    const { headcount: headcountMap } = useHeadcount(selectedCompany, selectedYear);

    // Compute display columns for both variants
    const plColumns = useMemo(() => getDisplayColumns('pl'), [getDisplayColumns]);
    const bsColumns = useMemo(() => getDisplayColumns('bs'), [getDisplayColumns]);

    // Upload views don't need report data — render before loading/error checks
    if (currentView === 'upload_planilla') {
        return <UploadPlanilla />;
    }

    if (isLoading) {
        return (
            <div className="flex-1 flex items-center justify-center">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-8 w-8 border-2 border-accent border-t-transparent mx-auto mb-4"></div>
                    <p className="text-sm text-txt-muted">Cargando datos...</p>
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex-1 flex items-center justify-center p-8">
                <div className="bg-accent-light border border-border rounded-[10px] p-6 text-center max-w-md">
                    <div className="w-10 h-10 rounded-full bg-accent-light flex items-center justify-center mx-auto mb-3">
                        <svg className="w-5 h-5 text-negative" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
                        </svg>
                    </div>
                    <p className="font-medium text-negative mb-1">Error</p>
                    <p className="text-sm text-txt-secondary">{error}</p>
                </div>
            </div>
        );
    }

    if (!reportData) {
        return (
            <div className="flex-1 flex items-center justify-center">
                <div className="text-center text-txt-faint">
                    <svg className="w-16 h-16 mx-auto mb-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <p className="text-lg font-medium text-txt-muted">Seleccione una empresa para comenzar</p>
                    <p className="text-sm text-txt-faint mt-1">Los datos se cargaran automaticamente</p>
                </div>
            </div>
        );
    }

    const renderView = () => {
        // BS views need BS data loaded first
        if (isBsView(currentView)) {
            if (isBsLoading || reportData.bs_summary.length === 0) {
                return (
                    <div className="flex-1 flex items-center justify-center py-16">
                        <div className="text-center">
                            <div className="animate-spin rounded-full h-8 w-8 border-2 border-accent border-t-transparent mx-auto mb-4"></div>
                            <p className="text-sm text-txt-muted">Cargando Balance General...</p>
                        </div>
                    </div>
                );
            }
            if (bsError) {
                return (
                    <div className="flex-1 flex items-center justify-center p-8">
                        <div className="bg-accent-light border border-border rounded-[10px] p-6 text-center max-w-md">
                            <p className="font-medium text-negative mb-1">Error</p>
                            <p className="text-sm text-txt-secondary">{bsError}</p>
                        </div>
                    </div>
                );
            }
        }

        // Note views (P&L and BS)
        const noteConfig = VIEW_TABLE_CONFIGS[currentView as NoteView];
        if (noteConfig) {
            const isBs = isBsView(currentView);
            const columns = isBs ? bsColumns : plColumns;

            // Build tables, applying trailing merge if needed
            let tables = noteConfig.tables(reportData);

            if (periodRange === 'trailing12') {
                tables = tables.map(t => {
                    const dataKey = getDataKeyForTable(t, reportData);
                    if (dataKey) {
                        return { ...t, rows: isBs
                            ? getMergedRows(dataKey, t.labelKeys[t.labelKeys.length - 1], 'bs')
                            : getMergedDetailRows(dataKey, t.labelKeys) };
                    }
                    return t;
                });
            }

            // Filter out all-zero tables
            tables = tables.filter(t => !isAllZeroTable(t.rows, ALL_MONTHS));

            if (tables.length === 0) {
                return (
                    <div className="text-center py-16 text-txt-muted">
                        <p className="text-sm">Sin datos para mostrar en esta vista</p>
                    </div>
                );
            }

            return <PLNoteView tables={tables} columns={columns} year={reportData.year} />;
        }

        if (currentView === 'analysis_pl_finanzas') {
            const rows = getMergedRows('pl_summary', 'PARTIDA_PL', 'pl');
            const cuentaKeys = ['CUENTA_CONTABLE', 'DESCRIPCION'];
            const cecoKeys = ['CENTRO_COSTO', 'DESC_CECO', 'CUENTA_CONTABLE', 'DESCRIPCION'];
            return (
                <ExpandableFinancialTable
                    rows={rows}
                    columns={plColumns}
                    costoByCuenta={getMergedDetailRows('costo_by_cuenta', cecoKeys)}
                    gastoVentaByCuenta={getMergedDetailRows('gasto_venta_by_cuenta', cuentaKeys)}
                    gastoAdminByCuenta={getMergedDetailRows('gasto_admin_by_cuenta', cuentaKeys)}
                    dyaCostoByCuenta={getMergedDetailRows('dya_costo_by_cuenta', cuentaKeys)}
                    dyaGastoByCuenta={getMergedDetailRows('dya_gasto_by_cuenta', cuentaKeys)}
                    otrosIngresosByCuenta={getMergedDetailRows('otros_ingresos_by_cuenta', cuentaKeys)}
                    otrosEgresosByCuenta={getMergedDetailRows('otros_egresos_by_cuenta', cuentaKeys)}
                    participacionByCuenta={getMergedDetailRows('participacion_by_cuenta', cuentaKeys)}
                    provisionByCuenta={getMergedDetailRows('provision_by_cuenta', cuentaKeys)}
                />
            );
        }

        if (currentView === 'analysis_planilla') {
            const planillaKeys = ['PARTIDA_PL', 'CENTRO_COSTO', 'DESC_CECO', 'CUENTA_CONTABLE', 'DESCRIPCION'];
            const planillaRows = getMergedDetailRows('planilla_by_cuenta', planillaKeys);
            const plSummaryRows = getMergedRows('pl_summary', 'PARTIDA_PL', 'pl');
            const revenueRow = plSummaryRows.find(r => r['PARTIDA_PL'] === 'INGRESOS ORDINARIOS') ?? null;
            return <PlanillaTable rows={planillaRows} columns={plColumns} revenueRow={revenueRow} headcountMap={headcountMap} />;
        }

        if (currentView === 'analysis_proveedores') {
            const proveedoresKeys = ['NIT', 'RAZON_SOCIAL'];
            const proveedoresRows = getMergedDetailRows('proveedores_transporte', proveedoresKeys) ?? [];
            return <ProveedoresTable rows={proveedoresRows} columns={plColumns} />;
        }

        if (currentView === 'pl') {
            const rows = getMergedRows('pl_summary', 'PARTIDA_PL', 'pl');
            return (
                <FinancialTable
                    rows={rows}
                    columns={plColumns}
                    labelKey="PARTIDA_PL"
                    showTotal
                    variant="pl"
                />
            );
        }

        if (currentView === 'bs') {
            const rows = getMergedRows('bs_summary', 'PARTIDA_BS', 'bs');
            return (
                <FinancialTable
                    rows={rows}
                    columns={bsColumns}
                    labelKey="PARTIDA_BS"
                    showTotal={false}
                    variant="bs"
                />
            );
        }

        return null;
    };

    return (
        <main className="flex-1 px-8 py-6 overflow-auto">
            {renderView()}
        </main>
    );
}

