import { useMemo } from 'react';
import type { ReportRow, DisplayColumn } from '@/types';
import { formatNumber } from '@/utils/format';
import { getCellValue, getSummaryTotal, BOLD_ROWS_PL, BOLD_ROWS_BS } from '@/utils/cellValue';

interface FinancialTableProps {
    rows: ReportRow[];
    columns: DisplayColumn[];
    labelKey: string;
    showTotal?: boolean;
    variant: 'pl' | 'bs';
}

/** Resolve a cell's CSS classes based on its value and row type */
function cellClass(val: number | null | undefined, isBold: boolean): string {
    if (val === null || val === undefined) return 'cell-normal';
    if (val === 0) return 'cell-zero';
    if (val < 0) return 'cell-neg';
    return isBold ? 'cell-bold' : 'cell-normal';
}

export default function FinancialTable({ rows, columns, labelKey, showTotal = false, variant }: FinancialTableProps) {
    const boldSet = variant === 'pl' ? BOLD_ROWS_PL : BOLD_ROWS_BS;

    const headerCols = useMemo(() => {
        const cols = columns.map(c => c.header);
        if (showTotal) cols.push('TOTAL');
        return cols;
    }, [columns, showTotal]);

    return (
        <div className="table-card overflow-x-auto">
            <table className="min-w-full text-xs">
                <thead>
                    <tr className="thead-row">
                        <th scope="col" className="thead-cell sticky-col bg-surface-alt text-left min-w-[360px]">
                            PARTIDA
                        </th>
                        {columns.map(col => (
                            <th scope="col" key={col.header} className="thead-cell text-right min-w-[90px]">
                                {col.header}
                            </th>
                        ))}
                        {showTotal && (
                            <th scope="col" className="thead-cell text-right min-w-[90px] cell-total-col">
                                TOTAL
                            </th>
                        )}
                    </tr>
                </thead>
                <tbody>
                    {rows.map((row, idx) => {
                        const label = row[labelKey] as string;
                        const isEmpty = !label || label.trim() === '';
                        const isBold = boldSet.has(label);
                        const isSection = variant === 'bs' && label && !isBold && columns.length > 0 && getCellValue(row, columns[0]) === null;

                        if (isEmpty) {
                            return (
                                <tr key={idx} className="h-1.5">
                                    <td colSpan={headerCols.length + 1} className="bg-surface-alt/50"></td>
                                </tr>
                            );
                        }

                        return (
                            <tr
                                key={idx}
                                className={`row-base
                                    ${isBold ? 'bg-surface-alt hover:bg-surface-alt' : ''}
                                    ${isSection ? 'bg-surface-alt' : ''}`}
                            >
                                <td className={`sticky-col px-4 py-2 whitespace-nowrap
                                    ${isBold
                                        ? 'font-bold text-txt bg-surface-alt'
                                        : isSection
                                            ? 'font-semibold text-txt-secondary bg-surface-alt'
                                            : 'text-txt-secondary bg-surface'}`}>
                                    {label}
                                </td>
                                {columns.map(col => {
                                    const val = getCellValue(row, col);
                                    return (
                                        <td key={col.header} className={`cell-base ${cellClass(val, isBold)}`}>
                                            {formatNumber(val)}
                                        </td>
                                    );
                                })}
                                {showTotal && (() => {
                                    const total = getSummaryTotal(row, columns, variant);
                                    return (
                                        <td className={`cell-base cell-total-col ${cellClass(total, true)}`}>
                                            {formatNumber(total)}
                                        </td>
                                    );
                                })()}
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}
