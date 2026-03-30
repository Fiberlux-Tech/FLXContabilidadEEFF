import type { CellSelection, DisplayColumn, ReportRow } from '@/types';
import { formatNumber } from '@/utils/format';
import { getCellValue, getDetailTotal } from '@/utils/cellValue';

interface DetailTableProps {
    title: string;
    rows: ReportRow[];
    labelKeys: string[];
    headerLabels: string[];
    columns: DisplayColumn[];
    year: number;
    partida: string;
    filterCol: string;
    selection: CellSelection | null;
    onCellClick: (sel: CellSelection) => void;
}

export default function DetailTable({ title, rows, labelKeys, headerLabels, columns, year, partida, filterCol, selection, onCellClick }: DetailTableProps) {
    // Value columns: display columns + TOTAL (year)
    const totalHeader = String(year);

    return (
        <div>
            <h3 className="text-base font-semibold text-gray-700 mb-2">{title}</h3>
            <div className="overflow-x-auto border border-gray-200 rounded-lg">
                <table className="min-w-full text-xs">
                    <thead>
                        <tr className="bg-gray-800 text-white">
                            <th
                                scope="col"
                                colSpan={labelKeys.length}
                                className="sticky left-0 z-10 bg-gray-800 px-3 py-2 text-left font-medium whitespace-nowrap min-w-[300px]"
                            >
                                {headerLabels.join(' / ')}
                            </th>
                            {columns.map(col => (
                                <th scope="col" key={col.header} className="px-2 py-2 text-right font-medium whitespace-nowrap min-w-[85px]">
                                    {col.header}
                                </th>
                            ))}
                            <th scope="col" className="px-2 py-2 text-right font-medium font-bold whitespace-nowrap min-w-[85px]">
                                {totalHeader}
                            </th>
                        </tr>
                    </thead>
                    <tbody>
                        {rows.map((row, idx) => {
                            const isTotal = labelKeys.some(k => row[k] === 'TOTAL');
                            const rowFilterVal = isTotal ? null : String(row[filterCol] ?? '');
                            const rowLabel = isTotal ? 'TOTAL' : String(row[labelKeys[labelKeys.length - 1]] ?? '');

                            const isRowSelected = selection &&
                                selection.partida === partida &&
                                selection.month === null &&
                                selection.filterVal === rowFilterVal;

                            return (
                                <tr
                                    key={idx}
                                    className={`border-b border-gray-100 transition-colors
                                        ${isTotal ? 'bg-gray-50 font-bold' : 'hover:bg-blue-50/50'}
                                        ${isRowSelected ? 'ring-1 ring-blue-400' : ''}`}
                                >
                                    <td
                                        colSpan={labelKeys.length}
                                        onClick={() => onCellClick({
                                            partida,
                                            month: null,
                                            filterCol: isTotal ? null : filterCol,
                                            filterVal: rowFilterVal,
                                            label: `${rowLabel} — Todo el periodo`,
                                        })}
                                        className={`sticky left-0 z-10 px-3 py-1.5 whitespace-nowrap cursor-pointer hover:underline
                                            ${isTotal ? 'font-bold text-gray-900 bg-gray-50 hover:bg-gray-100' : 'text-gray-700 bg-white hover:bg-blue-50'}
                                            ${isRowSelected ? 'bg-blue-100' : ''}`}
                                    >
                                        {labelKeys.map(key => row[key] ?? '').join(' — ')}
                                    </td>
                                    {columns.map(col => {
                                        const val = getCellValue(row, col);
                                        const isNeg = val !== null && val !== undefined && val < 0;
                                        const hasValue = val !== null && val !== undefined && val !== 0;

                                        // For drill-down: pass the source months so PLNoteView can filter
                                        const clickLabel = col.sourceMonths.length === 1
                                            ? `${rowLabel} — ${col.sourceMonths[0]}`
                                            : `${rowLabel} — ${col.header}`;

                                        const isClickable = hasValue;
                                        const isSelected = selection &&
                                            selection.partida === partida &&
                                            selection.month === col.sourceMonths.join(',') &&
                                            selection.filterVal === (isTotal ? null : rowFilterVal);

                                        return (
                                            <td
                                                key={col.header}
                                                onClick={isClickable ? () => onCellClick({
                                                    partida,
                                                    // Encode source months as comma-separated for quarterly
                                                    month: col.sourceMonths.join(','),
                                                    filterCol: isTotal ? null : filterCol,
                                                    filterVal: isTotal ? null : rowFilterVal,
                                                    label: isTotal ? `TOTAL — ${col.header}` : clickLabel,
                                                }) : undefined}
                                                className={`px-2 py-1.5 text-right whitespace-nowrap font-mono
                                                    ${isTotal ? 'font-bold' : ''}
                                                    ${isNeg ? 'text-red-600' : 'text-gray-800'}
                                                    ${isClickable ? 'cursor-pointer hover:bg-blue-100 hover:underline' : ''}
                                                    ${isSelected ? 'bg-blue-200 ring-1 ring-blue-400' : ''}`}
                                            >
                                                {formatNumber(val)}
                                            </td>
                                        );
                                    })}
                                    {/* Year total column */}
                                    {(() => {
                                        const total = getDetailTotal(row, columns);
                                        const isNeg = total !== null && total !== undefined && total < 0;
                                        const hasValue = total !== null && total !== undefined && total !== 0;

                                        const isSelected = selection &&
                                            selection.partida === partida &&
                                            selection.month === null &&
                                            selection.filterVal === (isTotal ? null : rowFilterVal);

                                        return (
                                            <td
                                                onClick={hasValue ? () => onCellClick({
                                                    partida,
                                                    month: null,
                                                    filterCol: isTotal ? null : filterCol,
                                                    filterVal: isTotal ? null : rowFilterVal,
                                                    label: `${rowLabel} — Todo el periodo`,
                                                }) : undefined}
                                                className={`px-2 py-1.5 text-right whitespace-nowrap font-mono font-bold
                                                    ${isNeg ? 'text-red-600' : 'text-gray-800'}
                                                    ${hasValue ? 'cursor-pointer hover:bg-blue-100 hover:underline' : ''}
                                                    ${isSelected ? 'bg-blue-200 ring-1 ring-blue-400' : ''}`}
                                            >
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
        </div>
    );
}
