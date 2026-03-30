import { useMemo } from 'react';
import { useReport } from '@/contexts/ReportContext';
import FinancialTable from '@/features/dashboard/FinancialTable';
import PLNoteView from '@/features/dashboard/PLNoteView';
import type { ReportData, TableConfig, ReportRow, DisplayColumn } from '@/types';
import { VIEW_TABLE_CONFIGS, ALL_MONTHS, isAllZeroTable, type NoteView } from '@/config/viewConfigs';

export default function MainContent() {
    const {
        reportData, currentView, isLoading, error,
        getDisplayColumns, periodRange, getMergedRows, getMergedDetailRows,
    } = useReport();

    // Compute display columns for both variants
    const plColumns = useMemo(() => getDisplayColumns('pl'), [getDisplayColumns]);
    const bsColumns = useMemo(() => getDisplayColumns('bs'), [getDisplayColumns]);

    if (isLoading) {
        return (
            <div className="flex-1 flex items-center justify-center">
                <div className="text-center">
                    <div className="animate-spin rounded-full h-10 w-10 border-b-2 border-blue-600 mx-auto mb-4"></div>
                    <p className="text-gray-500">Cargando datos...</p>
                </div>
            </div>
        );
    }

    if (error) {
        return (
            <div className="flex-1 p-8">
                <div className="bg-red-50 border border-red-200 rounded-lg p-6 text-red-700">
                    <p className="font-medium">Error</p>
                    <p className="text-sm mt-1">{error}</p>
                </div>
            </div>
        );
    }

    if (!reportData) {
        return (
            <div className="flex-1 flex items-center justify-center">
                <div className="text-center text-gray-400">
                    <svg className="w-16 h-16 mx-auto mb-4 opacity-50" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <p className="text-lg">Seleccione una empresa para comenzar</p>
                </div>
            </div>
        );
    }

    const renderView = () => {
        const noteConfig = VIEW_TABLE_CONFIGS[currentView as NoteView];
        if (noteConfig) {
            // Build tables, applying trailing merge if needed
            let tables = noteConfig.tables(reportData);

            if (periodRange === 'trailing12') {
                // Merge each table's rows with prev year data
                tables = tables.map(t => {
                    const dataKey = getDataKeyForTable(t, reportData);
                    if (dataKey) {
                        return { ...t, rows: getMergedDetailRows(dataKey, t.labelKeys) };
                    }
                    return t;
                });
            }

            // Filter out all-zero tables
            tables = tables.filter(t => !isAllZeroTable(t.rows, ALL_MONTHS));

            if (tables.length === 0) {
                return (
                    <div className="text-center py-12 text-gray-400">
                        <p className="text-sm">Sin datos para mostrar en esta vista</p>
                    </div>
                );
            }

            return <PLNoteView tables={tables} columns={plColumns} year={reportData.year} />;
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
        <main className="flex-1 p-6 overflow-auto">
            <div className="max-w-[1400px] mx-auto">
                {renderView()}
            </div>
        </main>
    );
}

/** Map a TableConfig back to the ReportData key so we can fetch merged rows */
function getDataKeyForTable(table: TableConfig, data: ReportData): keyof ReportData | null {
    // Match by checking if table.rows reference is the same as a known key
    const mapping: [keyof ReportData, ReportRow[]][] = [
        ['ingresos_ordinarios', data.ingresos_ordinarios],
        ['ingresos_proyectos', data.ingresos_proyectos],
        ['costo', data.costo],
        ['gasto_venta', data.gasto_venta],
        ['gasto_admin', data.gasto_admin],
        ['dya_costo', data.dya_costo],
        ['dya_gasto', data.dya_gasto],
        ['resultado_financiero_ingresos', data.resultado_financiero_ingresos],
        ['resultado_financiero_gastos', data.resultado_financiero_gastos],
    ];
    for (const [key, rows] of mapping) {
        if (table.rows === rows) return key;
    }
    return null;
}
