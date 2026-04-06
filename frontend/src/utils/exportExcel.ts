import XLSX from 'xlsx-js-style';
import type { ReportRow, DisplayColumn } from '@/types';
import { getCellValue, getSummaryTotal, getDetailTotal, BOLD_ROWS_PL, BOLD_ROWS_BS } from '@/utils/cellValue';

// ── Sheet definition types ───────────────────────────────────────────

export interface SummarySheetDef {
    kind: 'summary';
    sheetName: string;
    rows: ReportRow[];
    columns: DisplayColumn[];
    labelKey: string;
    showTotal: boolean;
    variant: 'pl' | 'bs';
}

export interface DetailSheetDef {
    kind: 'detail';
    sheetName: string;
    rows: ReportRow[];
    columns: DisplayColumn[];
    headerLabels: string[];
    labelKeys: string[];
    year: number;
}

export interface PlanillaExportRow {
    label: string;
    level: 0 | 1 | 2;             // 0=partida, 1=ceco, 2=cuenta
    values: Record<string, number>; // month keys + TOTAL
}

export interface PlanillaSheetDef {
    kind: 'planilla';
    sheetName: string;
    flatRows: PlanillaExportRow[];
    columns: DisplayColumn[];
    year: number;
    /** Override number format (default: standard accounting #,##0;-#,##0;"-") */
    numFmt?: string;
}

export type ExportSheet = SummarySheetDef | DetailSheetDef | PlanillaSheetDef;

export interface ExportOptions {
    sheets: ExportSheet[];
    filename: string;
}

// ── Styles ───────────────────────────────────────────────────────────

import { NUM_FMT, HEADER_STYLE, HEADER_LABEL_STYLE, NUM_STYLE, TEXT_STYLE as LABEL_STYLE } from '@/utils/excelStyles';

const BOLD_NUM_STYLE: XLSX.CellStyle = {
    font: { bold: true, sz: 10 },
    numFmt: NUM_FMT,
    alignment: { horizontal: 'right' },
};

const BOLD_LABEL_STYLE: XLSX.CellStyle = {
    font: { bold: true, sz: 10 },
    fill: { fgColor: { rgb: 'F9FAFB' } },
};

// Planilla hierarchy styles
const PL_L0_LABEL: XLSX.CellStyle = { font: { bold: true, sz: 10 }, fill: { fgColor: { rgb: 'F0F0EE' } } };
const PL_L0_NUM: XLSX.CellStyle = { font: { bold: true, sz: 10 }, fill: { fgColor: { rgb: 'F0F0EE' } }, numFmt: NUM_FMT, alignment: { horizontal: 'right' } };
const PL_L1_LABEL: XLSX.CellStyle = { font: { sz: 10 } };
const PL_L1_NUM: XLSX.CellStyle = { font: { sz: 10 }, numFmt: NUM_FMT, alignment: { horizontal: 'right' } };
const PL_L2_LABEL: XLSX.CellStyle = { font: { sz: 9, color: { rgb: '666666' } } };
const PL_L2_NUM: XLSX.CellStyle = { font: { sz: 9, color: { rgb: '666666' } }, numFmt: NUM_FMT, alignment: { horizontal: 'right' } };

// ── Helpers ──────────────────────────────────────────────────────────

function safeSheetName(name: string): string {
    // Excel limits sheet names to 31 chars, no special chars: [ ] : * ? / \
    return name.replace(/[[\]:*?/\\]/g, '').slice(0, 31);
}

function cellRef(r: number, c: number): string {
    return XLSX.utils.encode_cell({ r, c });
}

// ── Summary sheet builder ────────────────────────────────────────────

function buildSummarySheet(def: SummarySheetDef): XLSX.WorkSheet {
    const { rows, columns, labelKey, showTotal, variant } = def;
    const boldSet = variant === 'pl' ? BOLD_ROWS_PL : BOLD_ROWS_BS;
    const dataCols = columns.length + (showTotal ? 1 : 0);
    const totalCols = 1 + dataCols; // label + data

    const ws: XLSX.WorkSheet = {};
    let r = 0;

    // Header row
    ws[cellRef(r, 0)] = { v: 'PARTIDA', t: 's', s: HEADER_LABEL_STYLE };
    columns.forEach((col, ci) => {
        ws[cellRef(r, 1 + ci)] = { v: col.header, t: 's', s: HEADER_STYLE };
    });
    if (showTotal) {
        ws[cellRef(r, 1 + columns.length)] = { v: 'TOTAL', t: 's', s: HEADER_STYLE };
    }
    r++;

    // Data rows
    for (const row of rows) {
        const label = row[labelKey] as string;
        const isEmpty = !label || label.trim() === '';

        if (isEmpty) {
            // Spacer row — leave blank
            r++;
            continue;
        }

        const isBold = boldSet.has(label);
        const lblStyle = isBold ? BOLD_LABEL_STYLE : LABEL_STYLE;
        const numStyle = isBold ? BOLD_NUM_STYLE : NUM_STYLE;

        ws[cellRef(r, 0)] = { v: label, t: 's', s: lblStyle };

        columns.forEach((col, ci) => {
            const val = getCellValue(row, col);
            if (val !== null && val !== undefined) {
                ws[cellRef(r, 1 + ci)] = { v: val, t: 'n', s: numStyle };
            } else {
                ws[cellRef(r, 1 + ci)] = { v: '', t: 's', s: numStyle };
            }
        });

        if (showTotal) {
            const total = getSummaryTotal(row, columns, variant);
            if (total !== null && total !== undefined) {
                ws[cellRef(r, 1 + columns.length)] = { v: total, t: 'n', s: BOLD_NUM_STYLE };
            } else {
                ws[cellRef(r, 1 + columns.length)] = { v: '', t: 's', s: BOLD_NUM_STYLE };
            }
        }

        r++;
    }

    // Set range and column widths
    ws['!ref'] = XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: r - 1, c: totalCols - 1 } });
    ws['!cols'] = [{ wch: 40 }, ...Array(dataCols).fill({ wch: 14 })];

    return ws;
}

// ── Detail sheet builder ─────────────────────────────────────────────

function buildDetailSheet(def: DetailSheetDef): XLSX.WorkSheet {
    const { rows, columns, headerLabels, labelKeys, year } = def;
    const dataCols = columns.length + 1; // +1 for year total
    const totalCols = headerLabels.length + dataCols;

    const ws: XLSX.WorkSheet = {};
    let r = 0;

    // Header row
    headerLabels.forEach((hl, ci) => {
        ws[cellRef(r, ci)] = { v: hl, t: 's', s: HEADER_LABEL_STYLE };
    });
    columns.forEach((col, ci) => {
        ws[cellRef(r, headerLabels.length + ci)] = { v: col.header, t: 's', s: HEADER_STYLE };
    });
    ws[cellRef(r, headerLabels.length + columns.length)] = { v: String(year), t: 's', s: HEADER_STYLE };
    r++;

    // Data rows
    for (const row of rows) {
        const isTotal = labelKeys.some(k => row[k] === 'TOTAL');
        const numStyle = isTotal ? BOLD_NUM_STYLE : NUM_STYLE;
        const lblStyle = isTotal ? BOLD_LABEL_STYLE : LABEL_STYLE;

        // Label columns
        labelKeys.forEach((key, ci) => {
            ws[cellRef(r, ci)] = { v: String(row[key] ?? ''), t: 's', s: lblStyle };
        });

        // Data columns
        columns.forEach((col, ci) => {
            const val = getCellValue(row, col);
            if (val !== null && val !== undefined) {
                ws[cellRef(r, headerLabels.length + ci)] = { v: val, t: 'n', s: numStyle };
            } else {
                ws[cellRef(r, headerLabels.length + ci)] = { v: '', t: 's', s: numStyle };
            }
        });

        // Year total
        const total = getDetailTotal(row, columns);
        if (total !== null && total !== undefined) {
            ws[cellRef(r, headerLabels.length + columns.length)] = { v: total, t: 'n', s: BOLD_NUM_STYLE };
        } else {
            ws[cellRef(r, headerLabels.length + columns.length)] = { v: '', t: 's', s: BOLD_NUM_STYLE };
        }

        r++;
    }

    ws['!ref'] = XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: r - 1, c: totalCols - 1 } });
    ws['!cols'] = [
        ...headerLabels.map((_, i) => ({ wch: i === 0 ? 16 : 30 })),
        ...Array(dataCols).fill({ wch: 14 }),
    ];

    return ws;
}

// ── Planilla sheet builder ───────────────────────────────────────────

function buildPlanillaSheet(def: PlanillaSheetDef): XLSX.WorkSheet {
    const { flatRows, columns, year, numFmt: customFmt } = def;
    const dataCols = columns.length + 1; // +1 for year total
    const totalCols = 1 + dataCols;      // label + data

    // Build level-specific num styles, applying custom format if provided
    const mkNum = (base: XLSX.CellStyle): XLSX.CellStyle =>
        customFmt ? { ...base, numFmt: customFmt } : base;
    const l0Num = mkNum(PL_L0_NUM);
    const l1Num = mkNum(PL_L1_NUM);
    const l2Num = mkNum(PL_L2_NUM);

    const ws: XLSX.WorkSheet = {};
    let r = 0;

    // Header row
    ws[cellRef(r, 0)] = { v: 'Concepto', t: 's', s: HEADER_LABEL_STYLE };
    columns.forEach((col, ci) => {
        ws[cellRef(r, 1 + ci)] = { v: col.header, t: 's', s: HEADER_STYLE };
    });
    ws[cellRef(r, 1 + columns.length)] = { v: String(year), t: 's', s: HEADER_STYLE };
    r++;

    for (const row of flatRows) {
        const lblStyle = row.level === 0 ? PL_L0_LABEL : row.level === 1 ? PL_L1_LABEL : PL_L2_LABEL;
        const numStyle = row.level === 0 ? l0Num : row.level === 1 ? l1Num : l2Num;

        const indent = row.level === 1 ? '    ' : row.level === 2 ? '        ' : '';
        ws[cellRef(r, 0)] = { v: indent + row.label, t: 's', s: lblStyle };

        columns.forEach((col, ci) => {
            const val = getCellValue(row.values as unknown as ReportRow, col);
            if (val !== null && val !== undefined) {
                ws[cellRef(r, 1 + ci)] = { v: val, t: 'n', s: numStyle };
            } else {
                ws[cellRef(r, 1 + ci)] = { v: '', t: 's', s: numStyle };
            }
        });

        // Total column
        const total = row.values['TOTAL'] ?? null;
        if (total !== null && total !== undefined) {
            ws[cellRef(r, 1 + columns.length)] = { v: total, t: 'n', s: numStyle };
        } else {
            ws[cellRef(r, 1 + columns.length)] = { v: '', t: 's', s: numStyle };
        }

        r++;
    }

    ws['!ref'] = XLSX.utils.encode_range({ s: { r: 0, c: 0 }, e: { r: r - 1, c: totalCols - 1 } });
    ws['!cols'] = [{ wch: 45 }, ...Array(dataCols).fill({ wch: 14 })];

    return ws;
}

// ── Main export function ─────────────────────────────────────────────

export function exportToExcel({ sheets, filename }: ExportOptions): void {
    const wb = XLSX.utils.book_new();

    for (const sheet of sheets) {
        const ws = sheet.kind === 'summary'
            ? buildSummarySheet(sheet)
            : sheet.kind === 'planilla'
                ? buildPlanillaSheet(sheet)
                : buildDetailSheet(sheet);

        XLSX.utils.book_append_sheet(wb, ws, safeSheetName(sheet.sheetName));
    }

    XLSX.writeFile(wb, filename);
}
