import { ALL_MONTHS } from '@/types';
import type { DisplayColumn, MonthSource, Month, Granularity, PeriodRange, Quarter } from '@/types';

const QUARTER_MONTHS: [Month, Month, Month][] = [
    ['JAN', 'FEB', 'MAR'],
    ['APR', 'MAY', 'JUN'],
    ['JUL', 'AUG', 'SEP'],
    ['OCT', 'NOV', 'DEC'],
];
const QUARTER_LABELS = ['Q1', 'Q2', 'Q3', 'Q4'];

export function getTrailing12MonthSources(currentYear: number): MonthSource[] {
    const now = new Date();
    // Use current calendar month as the end of trailing window
    const endMonth = now.getFullYear() === currentYear ? now.getMonth() : 11; // 0-indexed
    const sources: MonthSource[] = [];
    for (let i = 11; i >= 0; i--) {
        const monthIdx = (endMonth - i + 12) % 12;
        const year = (endMonth - i < 0) ? currentYear - 1 : currentYear;
        sources.push({ month: ALL_MONTHS[monthIdx], year });
    }
    return sources;
}

export function buildDisplayColumns(
    granularity: Granularity,
    periodRange: PeriodRange,
    selectedYear: number,
    variant: 'pl' | 'bs',
    selectedQuarter: Quarter = 1,
): DisplayColumn[] {
    // Single-quarter mode: 3 months of the chosen quarter, anchored to selectedYear.
    // periodRange is ignored (the quarter is inherently year-bound).
    if (granularity === 'single_quarter') {
        const months = QUARTER_MONTHS[selectedQuarter - 1];
        return months.map(m => ({
            header: `${m} ${selectedYear}`,
            sourceMonths: [m],
        }));
    }

    if (periodRange === 'ytd') {
        // Current year: all 12 months
        if (granularity === 'monthly') {
            return ALL_MONTHS.map(m => ({
                header: m,
                sourceMonths: [m],
            }));
        }
        // Quarterly YTD
        return QUARTER_MONTHS.map((months, qi) => ({
            header: `${QUARTER_LABELS[qi]} ${selectedYear}`,
            sourceMonths: months,
            useLastOnly: variant === 'bs',
        }));
    }

    // Trailing 12M
    const sources = getTrailing12MonthSources(selectedYear);

    if (granularity === 'monthly') {
        return sources.map(s => ({
            header: `${s.month}-${String(s.year).slice(2)}`,
            sourceMonths: [s.month],
        }));
    }

    // Quarterly trailing 12M: group the 12 sources into 4 quarters
    const cols: DisplayColumn[] = [];
    for (let q = 0; q < 4; q++) {
        const qSources = sources.slice(q * 3, q * 3 + 3);
        const lastSource = qSources[qSources.length - 1];
        const lastMonthIdx = ALL_MONTHS.indexOf(lastSource.month);
        const qi = Math.floor(lastMonthIdx / 3);
        cols.push({
            header: `${QUARTER_LABELS[qi]} ${lastSource.year}`,
            sourceMonths: qSources.map(s => s.month),
            useLastOnly: variant === 'bs',
        });
    }
    return cols;
}
