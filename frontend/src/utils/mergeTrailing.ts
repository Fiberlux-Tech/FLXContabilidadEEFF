import type { ReportRow, MonthSource } from '@/types';

export function mergeTrailingRows(
    currentRows: ReportRow[],
    prevRows: ReportRow[],
    labelKey: string,
    monthSources: MonthSource[],
    currentYear: number,
): ReportRow[] {
    // Build a lookup of prev year rows by label
    const prevLookup = new Map<string, ReportRow>();
    for (const row of prevRows) {
        const label = row[labelKey] as string;
        if (label) prevLookup.set(label, row);
    }

    return currentRows.map(row => {
        const label = row[labelKey] as string;
        if (!label || label.trim() === '') return { ...row }; // spacer row

        const prevRow = prevLookup.get(label);
        const merged: ReportRow = { [labelKey]: label };

        // For each trailing month, pick from correct year's data
        let total = 0;
        for (const src of monthSources) {
            const sourceRow = src.year === currentYear ? row : prevRow;
            const val = sourceRow ? (sourceRow[src.month] as number | null) ?? 0 : 0;
            // Store with a tagged key so we can retrieve by position
            merged[src.month] = val;
            total += val;
        }
        merged['TOTAL'] = total;
        return merged;
    });
}

function mergeOneDetailRow(
    currentRow: ReportRow | undefined,
    prevRow: ReportRow | undefined,
    labelKeys: string[],
    monthSources: MonthSource[],
    currentYear: number,
): ReportRow {
    const base = currentRow ?? prevRow!;
    const merged: ReportRow = {};
    for (const k of labelKeys) merged[k] = base[k];

    let total = 0;
    for (const src of monthSources) {
        const sourceRow = src.year === currentYear ? currentRow : prevRow;
        const val = sourceRow ? (sourceRow[src.month] as number | null) ?? 0 : 0;
        merged[src.month] = val;
        total += val;
    }
    merged['TOTAL'] = total;
    return merged;
}

export function mergeTrailingDetailRows(
    currentRows: ReportRow[],
    prevRows: ReportRow[],
    labelKeys: string[],
    monthSources: MonthSource[],
    currentYear: number,
): ReportRow[] {
    const isTotalRow = (row: ReportRow) => labelKeys.some(k => row[k] === 'TOTAL');
    const makeKey = (row: ReportRow) => labelKeys.map(k => String(row[k] ?? '')).join('|||');

    // Separate TOTAL rows from data rows
    const currentData = currentRows.filter(r => !isTotalRow(r));
    const prevData = prevRows.filter(r => !isTotalRow(r));

    const prevLookup = new Map<string, ReportRow>();
    for (const row of prevData) {
        prevLookup.set(makeKey(row), row);
    }

    // Merge data rows (excluding TOTAL)
    const seenKeys = new Set<string>();
    const dataRows: ReportRow[] = [];

    for (const row of currentData) {
        const key = makeKey(row);
        seenKeys.add(key);
        dataRows.push(mergeOneDetailRow(row, prevLookup.get(key), labelKeys, monthSources, currentYear));
    }
    for (const row of prevData) {
        const key = makeKey(row);
        if (!seenKeys.has(key)) {
            dataRows.push(mergeOneDetailRow(undefined, row, labelKeys, monthSources, currentYear));
        }
    }

    // Re-sort data rows by TOTAL descending (matching backend behavior)
    dataRows.sort((a, b) => {
        const ta = (a['TOTAL'] as number) ?? 0;
        const tb = (b['TOTAL'] as number) ?? 0;
        return Math.abs(tb) - Math.abs(ta);
    });

    // Rebuild TOTAL row by summing all month columns from merged data rows
    const monthKeys = monthSources.map(s => s.month);
    const totalRow: ReportRow = {};
    for (const k of labelKeys) totalRow[k] = 'TOTAL';
    let grandTotal = 0;
    for (const m of monthKeys) {
        let colSum = 0;
        for (const row of dataRows) {
            colSum += (row[m] as number) ?? 0;
        }
        totalRow[m] = colSum;
        grandTotal += colSum;
    }
    totalRow['TOTAL'] = grandTotal;

    // Append TOTAL row at the end
    return [...dataRows, totalRow];
}

export function mergeTrailingBSRows(
    currentRows: ReportRow[],
    prevRows: ReportRow[],
    labelKey: string,
    monthSources: MonthSource[],
    currentYear: number,
): ReportRow[] {
    const prevLookup = new Map<string, ReportRow>();
    for (const row of prevRows) {
        const label = row[labelKey] as string;
        if (label) prevLookup.set(label, row);
    }

    return currentRows.map(row => {
        const label = row[labelKey] as string;
        if (!label || label.trim() === '') return { ...row };

        const prevRow = prevLookup.get(label);
        const merged: ReportRow = { [labelKey]: label };

        // Each month's value is the balance at end of that month — no summing for TOTAL
        let lastVal = 0;
        for (const src of monthSources) {
            const sourceRow = src.year === currentYear ? row : prevRow;
            const val = sourceRow ? (sourceRow[src.month] as number | null) ?? 0 : 0;
            merged[src.month] = val;
            lastVal = val;
        }
        // BS TOTAL = last month's balance (not sum)
        merged['TOTAL'] = lastVal;
        return merged;
    });
}
