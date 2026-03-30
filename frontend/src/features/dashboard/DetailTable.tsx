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

/** Resolve a cell's CSS classes based on its value and row type */
function cellClass(val: number | null | undefined, isBold: boolean): string {
    if (val === null || val === undefined) return 'cell-normal';
    if (val === 0) return 'cell-zero';
    if (val < 0) return 'cell-neg';
    return isBold ? 'cell-bold' : 'cell-normal';
}

export default function DetailTable({ title, rows, labelKeys, headerLabels, columns, year, partida, filterCol, selection, onCellClick }: DetailTableProps) {
    const totalHeader = String(year);
    const dataRowCount = rows.filter(r => !labelKeys.some(k => r[k] === 'TOTAL')).length;

    return (
        <div>
            <h3 className="section-title">
                {title}
                <span className="section-badge">
                    {dataRowCount} {dataRowCount === 1 ? 'cuenta' : 'cuentas'}
                </span>
            </h3>
            <div className="table-card overflow-x-auto">
                <table className="min-w-full text-xs">
                    <thead>
                        <tr className="thead-row">
                            <th
                                scope="col"
                                colSpan={labelKeys.length}
                                className="thead-cell sticky-col bg-surface-alt text-left min-w-[360px]"
                            >
                                {headerLabels.join(' / ')}
                            </th>
                            {columns.map(col => (
                                <th scope="col" key={col.header} className="thead-cell text-right min-w-[90px]">
                                    {col.header}
                                </th>
                            ))}
                            <th scope="col" className="thead-cell text-right min-w-[90px] cell-total-col">
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
                                    className={`${isTotal ? 'row-total' : 'row-base'}
                                        ${isRowSelected ? 'cell-selected' : ''}`}
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
                                        className={`sticky-col px-4 py-2 whitespace-nowrap cursor-pointer
                                            ${isTotal
                                                ? 'font-bold text-txt bg-surface-alt hover:bg-nav-hover'
                                                : 'text-txt-secondary bg-surface hover:bg-accent-light hover:text-accent'}
                                            ${isRowSelected ? 'bg-accent-light' : ''}`}
                                    >
                                        {isTotal
                                            ? `\u2014 TOTAL`
                                            : labelKeys.map(key => row[key] ?? '').join(' \u2014 ')}
                                    </td>
                                    {columns.map(col => {
                                        const val = getCellValue(row, col);
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
                                                className={`cell-base
                                                    ${cellClass(val, isTotal)}
                                                    ${isClickable ? 'cell-clickable' : ''}
                                                    ${isSelected ? 'cell-selected' : ''}`}
                                            >
                                                {formatNumber(val)}
                                            </td>
                                        );
                                    })}
                                    {/* Year total column */}
                                    {(() => {
                                        const total = getDetailTotal(row, columns);
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
                                                className={`cell-base cell-total-col
                                                    ${cellClass(total, true)}
                                                    ${hasValue ? 'cell-clickable' : ''}
                                                    ${isSelected ? 'cell-selected' : ''}`}
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
