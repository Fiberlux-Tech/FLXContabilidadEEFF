import { useCallback } from 'react';
import { useReport } from '@/contexts/ReportContext';
import { VIEW_TITLE_MAP, VIEW_TABLE_CONFIGS, ALL_MONTHS, isAllZeroTable, type NoteView } from '@/config/viewConfigs';
import { exportToExcel, type ExportSheet, type SummarySheetDef, type DetailSheetDef } from '@/utils/exportExcel';

import { getDataKeyForTable } from '@/utils/dataKeyMapping';

export function useViewExport(): { handleExport: () => void; canExport: boolean } {
    const {
        currentView, reportData, selectedCompany, selectedYear,
        getDisplayColumns, getMergedRows, getMergedDetailRows,
        periodRange, isLoading,
    } = useReport();

    const canExport = !!reportData && !isLoading;

    const handleExport = useCallback(() => {
        if (!reportData) return;

        const sheets: ExportSheet[] = [];
        const viewTitle = VIEW_TITLE_MAP[currentView] ?? currentView;

        if (currentView === 'pl') {
            const rows = getMergedRows('pl_summary', 'PARTIDA_PL', 'pl');
            const sheet: SummarySheetDef = {
                kind: 'summary',
                sheetName: viewTitle,
                rows,
                columns: getDisplayColumns('pl'),
                labelKey: 'PARTIDA_PL',
                showTotal: true,
                variant: 'pl',
            };
            sheets.push(sheet);
        } else if (currentView === 'bs') {
            const rows = getMergedRows('bs_summary', 'PARTIDA_BS', 'bs');
            const sheet: SummarySheetDef = {
                kind: 'summary',
                sheetName: viewTitle,
                rows,
                columns: getDisplayColumns('bs'),
                labelKey: 'PARTIDA_BS',
                showTotal: false,
                variant: 'bs',
            };
            sheets.push(sheet);
        } else if (currentView === 'analysis_planilla') {
            const planillaKeys = ['PARTIDA_PL', 'CENTRO_COSTO', 'DESC_CECO', 'CUENTA_CONTABLE', 'DESCRIPCION'];
            const planillaRows = getMergedDetailRows('planilla_by_cuenta', planillaKeys);
            const sheet: DetailSheetDef = {
                kind: 'detail',
                sheetName: viewTitle,
                rows: planillaRows,
                columns: getDisplayColumns('pl'),
                headerLabels: ['Partida', 'Centro Costo', 'Desc. CECO', 'Cuenta', 'Descripción'],
                labelKeys: planillaKeys,
                year: selectedYear,
            };
            sheets.push(sheet);
        } else {
            // Note views
            const noteConfig = VIEW_TABLE_CONFIGS[currentView as NoteView];
            if (noteConfig) {
                let tables = noteConfig.tables(reportData);

                // Apply trailing 12M merge if active
                if (periodRange === 'trailing12') {
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

                for (const t of tables) {
                    const sheet: DetailSheetDef = {
                        kind: 'detail',
                        sheetName: t.title,
                        rows: t.rows,
                        columns: getDisplayColumns('pl'),
                        headerLabels: t.headerLabels,
                        labelKeys: t.labelKeys,
                        year: selectedYear,
                    };
                    sheets.push(sheet);
                }
            }
        }

        if (sheets.length === 0) return;

        const safeName = viewTitle.replace(/\s+/g, '_');
        const filename = `${safeName}_${selectedCompany}_${selectedYear}.xlsx`;

        exportToExcel({ sheets, filename });
    }, [
        reportData, currentView, selectedCompany, selectedYear,
        getDisplayColumns, getMergedRows, getMergedDetailRows, periodRange,
    ]);

    return { handleExport, canExport };
}
