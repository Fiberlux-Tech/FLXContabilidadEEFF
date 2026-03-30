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
    const totalHeader = String(year);

    return (
        <div>
            <h3 className="text-base font-semibold text-gray-700 mb-2">{title}</h3>
            <div className="overflow-x-auto border border-gray-200 rounded-xl shadow-sm">
                <table className="min-w-full text-xs">
                    <thead>
                        <tr className="bg-thead text-white">
                            <th
                                scope="col"
                                colSpan={labelKeys.length}
                                className="sticky left-0 z-10 bg-thead px-4 py-2.5 text-left font-semibold whitespace-nowrap min-w-[300px] sticky-col-shadow"
                            >
                                {headerLabels.join(' / ')}
                            </th>
                            {columns.map(col => (
                                <th scope="col" key={col.header} className="px-3 py-2.5 text-right font-semibold whitespace-nowrap min-w-[85px]">
                                    {col.header}
                                </th>
                            ))}
                            <th scope="col" className="px-3 py-2.5 text-right font-bold whitespace-nowrap min-w-[85px]">
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
                                        ${isTotal
                                            ? 'bg-gray-100/80 font-bold border-t-2 border-t-gray-300'
                                            : 'hover:bg-gray-50/70'}
                                        ${isRowSelected ? 'ring-1 ring-accent-ring ring-inset' : ''}`}
                                >
                                    <td
                                        colSpan={labelKeys.length}
                                        onClick={() => onCellClick({
                                            partida,
                                            month: null,
                                            filterCol: isTotal ? null : filterCol,
                                            filterVal: rowFilterVal,
                                            label: `${rowLabel} \u2014 Todo el periodo`,
                                        })}
                                        className={`sticky left-0 z-10 px-4 py-1.5 whitespace-nowrap cursor-pointer sticky-col-shadow
                                            ${isTotal
                                                ? 'font-bold text-gray-900 bg-gray-100/80 hover:bg-gray-200/70'
                                                : 'text-gray-700 bg-white hover:bg-accent-light hover:text-accent'}
                                            ${isRowSelected ? 'bg-accent-light' : ''}`}
                                    >
                                        {isTotal
                                            ? `\u2014 TOTAL`
                                            : labelKeys.map(key => row[key] ?? '').join(' \u2014 ')}
                                    </td>
                                    {columns.map(col => {
                                        const val = getCellValue(row, col);
                                        const isNeg = val !== null && val !== undefined && val < 0;
                                        const hasValue = val !== null && val !== undefined && val !== 0;

                                        const clickLabel = col.sourceMonths.length === 1
                                            ? `${rowLabel} \u2014 ${col.sourceMonths[0]}`
                                            : `${rowLabel} \u2014 ${col.header}`;

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
                                                    month: col.sourceMonths.join(','),
                                                    filterCol: isTotal ? null : filterCol,
                                                    filterVal: isTotal ? null : rowFilterVal,
                                                    label: isTotal ? `TOTAL \u2014 ${col.header}` : clickLabel,
                                                }) : undefined}
                                                className={`px-3 py-1.5 text-right whitespace-nowrap font-mono
                                                    ${isTotal ? 'font-bold' : ''}
                                                    ${isNeg ? 'text-negative' : 'text-gray-800'}
                                                    ${isClickable ? 'cursor-pointer hover:bg-accent-hover hover:text-accent' : ''}
                                                    ${isSelected ? 'bg-accent-hover ring-1 ring-accent-ring ring-inset' : ''}`}
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
                                                    label: `${rowLabel} \u2014 Todo el periodo`,
                                                }) : undefined}
                                                className={`px-3 py-1.5 text-right whitespace-nowrap font-mono font-bold
                                                    ${isNeg ? 'text-negative' : 'text-gray-800'}
                                                    ${hasValue ? 'cursor-pointer hover:bg-accent-hover hover:text-accent' : ''}
                                                    ${isSelected ? 'bg-accent-hover ring-1 ring-accent-ring ring-inset' : ''}`}
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
