import { useMemo } from 'react';
import type { ReportRow, DisplayColumn } from '@/types';
import { formatNumber } from '@/utils/format';
import { getCellValue, getDetailTotal } from '@/utils/cellValue';
import { negClass } from '@/utils/classHelpers';

// ── Types ───────────────────────────────────────────────────────────

interface ProveedoresTableProps {
    rows: ReportRow[];
    columns: DisplayColumn[];
}

// ── Component ───────────────────────────────────────────────────────

export default function ProveedoresTable({ rows, columns }: ProveedoresTableProps) {
    const { totalRow, detailRows } = useMemo(() => {
        const total = rows.find(r => r['RAZON_SOCIAL'] === 'TOTAL') ?? null;
        const detail = rows.filter(r => r['RAZON_SOCIAL'] !== 'TOTAL');
        return { totalRow: total, detailRows: detail };
    }, [rows]);

    if (!totalRow && detailRows.length === 0) {
        return (
            <div className="text-center py-16 text-txt-muted">
                <p className="text-sm">Sin datos de proveedores de transporte</p>
            </div>
        );
    }

    const provColStyle: React.CSSProperties = {
        width: '280px',
        maxWidth: '280px',
        overflow: 'hidden',
        textOverflow: 'ellipsis',
        whiteSpace: 'nowrap',
    };

    return (
        <table className="rpt-table" style={{ tableLayout: 'fixed' }}>
            <thead>
                <tr>
                    <th className="text-left" style={provColStyle}>NIT / Proveedor</th>
                    {columns.map(col => (
                        <th key={col.header}>{col.header}</th>
                    ))}
                    <th className="rpt-col-total">Total</th>
                </tr>
            </thead>
            <tbody>
                {/* Total row at top */}
                {totalRow && (
                    <tr className="rpt-row-total">
                        <td style={provColStyle}>COSTO DE TRANSPORTE</td>
                        {columns.map(col => {
                            const val = getCellValue(totalRow, col);
                            return (
                                <td key={col.header} className={negClass(val)}>
                                    {formatNumber(val)}
                                </td>
                            );
                        })}
                        <td className={negClass(getDetailTotal(totalRow, columns))}>
                            {formatNumber(getDetailTotal(totalRow, columns))}
                        </td>
                    </tr>
                )}

                {/* NIT detail rows */}
                {detailRows.map((row, idx) => {
                    const nit = String(row['NIT'] ?? '');
                    const razon = String(row['RAZON_SOCIAL'] ?? '');
                    const label = nit ? `${nit} - ${razon}` : razon;
                    const total = getDetailTotal(row, columns);
                    return (
                        <tr key={idx} className="rpt-row-data">
                            <td style={provColStyle} title={label}>{label}</td>
                            {columns.map(col => {
                                const val = getCellValue(row, col);
                                return (
                                    <td key={col.header} className={negClass(val)}>
                                        {formatNumber(val)}
                                    </td>
                                );
                            })}
                            <td className={negClass(total)} style={{ fontWeight: 600 }}>
                                {formatNumber(total)}
                            </td>
                        </tr>
                    );
                })}
            </tbody>
        </table>
    );
}
