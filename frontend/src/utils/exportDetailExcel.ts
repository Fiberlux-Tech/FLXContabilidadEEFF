import XLSX from 'xlsx-js-style';
import type { ReportRow } from '@/types';

const NUM_FMT = '#,##0;-#,##0;"-"';

const HEADER_STYLE: XLSX.CellStyle = {
    font: { bold: true, color: { rgb: 'FFFFFF' }, sz: 10 },
    fill: { fgColor: { rgb: '1F2937' } },
    alignment: { horizontal: 'center' },
};

const HEADER_LABEL_STYLE: XLSX.CellStyle = {
    ...HEADER_STYLE,
    alignment: { horizontal: 'left' },
};

const NUM_STYLE: XLSX.CellStyle = {
    font: { sz: 10 },
    numFmt: NUM_FMT,
    alignment: { horizontal: 'right' },
};

const TEXT_STYLE: XLSX.CellStyle = {
    font: { sz: 10 },
};

const COLS: { key: string; header: string; width: number }[] = [
    { key: 'ASIENTO',         header: 'Asiento',        width: 12 },
    { key: 'CUENTA_CONTABLE', header: 'Cuenta',         width: 18 },
    { key: 'DESCRIPCION',     header: 'Descripcion',    width: 40 },
    { key: 'NIT',             header: 'NIT',            width: 14 },
    { key: 'RAZON_SOCIAL',    header: 'Razon Social',   width: 35 },
    { key: 'CENTRO_COSTO',    header: 'Centro Costo',   width: 14 },
    { key: 'DESC_CECO',       header: 'Desc. CECO',     width: 30 },
    { key: 'FECHA',           header: 'Fecha',          width: 12 },
    { key: 'SALDO',           header: 'Saldo',          width: 16 },
];

export function exportDetailToExcel(
    rows: ReportRow[],
    label: string,
    company: string,
    year: number,
): void {
    const ws_data: XLSX.CellObject[][] = [];

    // Header row
    ws_data.push(
        COLS.map(col => ({
            v: col.header,
            t: 's' as const,
            s: col.key === 'SALDO' ? HEADER_STYLE : HEADER_LABEL_STYLE,
        })),
    );

    // Data rows
    for (const row of rows) {
        ws_data.push(
            COLS.map(col => {
                if (col.key === 'SALDO') {
                    const val = typeof row[col.key] === 'number' ? row[col.key] as number : 0;
                    return { v: val, t: 'n' as const, s: NUM_STYLE };
                }
                return { v: String(row[col.key] ?? ''), t: 's' as const, s: TEXT_STYLE };
            }),
        );
    }

    const ws = XLSX.utils.aoa_to_sheet(ws_data);
    ws['!cols'] = COLS.map(col => ({ wch: col.width }));

    const wb = XLSX.utils.book_new();
    XLSX.utils.book_append_sheet(wb, ws, 'Detalle');

    const safeLabel = label.replace(/[\\/:*?"<>|]/g, '_').slice(0, 60);
    XLSX.writeFile(wb, `Detalle_${safeLabel}_${company}_${year}.xlsx`);
}
