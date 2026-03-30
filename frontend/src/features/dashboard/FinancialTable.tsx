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

export default function FinancialTable({ rows, columns, labelKey, showTotal = false, variant }: FinancialTableProps) {
    const boldSet = variant === 'pl' ? BOLD_ROWS_PL : BOLD_ROWS_BS;

    const headerCols = useMemo(() => {
        const cols = columns.map(c => c.header);
        if (showTotal) cols.push('TOTAL');
        return cols;
    }, [columns, showTotal]);

    return (
        <div className="overflow-x-auto border border-gray-200 rounded-xl shadow-sm">
            <table className="min-w-full text-xs">
                <thead>
                    <tr className="bg-thead text-white">
                        <th scope="col" className="sticky left-0 bg-thead z-10 px-4 py-2.5 text-left font-semibold min-w-[220px] sticky-col-shadow">
                            PARTIDA
                        </th>
                        {headerCols.map(col => (
                            <th scope="col" key={col} className="px-3 py-2.5 text-right font-semibold whitespace-nowrap min-w-[85px]">
                                {col}
                            </th>
                        ))}
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
                                    <td colSpan={headerCols.length + 1} className="bg-gray-50/50"></td>
                                </tr>
                            );
                        }

                        return (
                            <tr
                                key={idx}
                                className={`border-b border-gray-100 transition-colors
                                    ${isBold
                                        ? 'bg-blue-50/40 hover:bg-blue-50/70'
                                        : isSection
                                            ? 'bg-gray-50 hover:bg-gray-100/70'
                                            : 'hover:bg-gray-50/70'}`}
                            >
                                <td className={`sticky left-0 z-10 px-4 py-1.5 whitespace-nowrap sticky-col-shadow
                                    ${isBold
                                        ? 'font-bold text-gray-900 bg-blue-50/40'
                                        : isSection
                                            ? 'font-semibold text-gray-600 bg-gray-50'
                                            : 'text-gray-700 bg-white'}`}>
                                    {label}
                                </td>
                                {columns.map(col => {
                                    const val = getCellValue(row, col);
                                    const isNeg = val !== null && val !== undefined && val < 0;
                                    return (
                                        <td key={col.header} className={`px-3 py-1.5 text-right whitespace-nowrap font-mono
                                            ${isBold ? 'font-bold' : ''}
                                            ${isNeg ? 'text-negative' : 'text-gray-800'}`}>
                                            {formatNumber(val)}
                                        </td>
                                    );
                                })}
                                {showTotal && (() => {
                                    const total = getSummaryTotal(row, columns, variant);
                                    const isNeg = total !== null && total !== undefined && total < 0;
                                    return (
                                        <td className={`px-3 py-1.5 text-right whitespace-nowrap font-mono font-bold
                                            ${isNeg ? 'text-negative' : 'text-gray-800'}`}>
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
