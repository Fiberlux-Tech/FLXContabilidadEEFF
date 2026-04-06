import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import { API_CONFIG } from '@/config';
import type { PeriodRange } from '@/types';

/** CENTRO_COSTO → { year_month_str → headcount } following DB convention (keys are "202501" etc.) */
export type HeadcountMap = Record<string, Record<string, number>>;

interface HeadcountYmResponse {
    headcount: HeadcountMap;
}

export function useHeadcount(company: string, year: number, periodRange: PeriodRange) {
    const [headcount, setHeadcount] = useState<HeadcountMap | null>(null);
    const [isLoading, setIsLoading] = useState(false);

    useEffect(() => {
        if (!company || !year) {
            setHeadcount(null);
            return;
        }

        let cancelled = false;
        setIsLoading(true);

        const years = periodRange === 'trailing12'
            ? `${year - 1},${year}`
            : `${year}`;

        api.get<HeadcountYmResponse>(
            `${API_CONFIG.ENDPOINTS.HEADCOUNT_YM}?company=${encodeURIComponent(company)}&years=${years}`
        )
            .then(data => {
                if (!cancelled) {
                    const map = data.headcount;
                    setHeadcount(map && Object.keys(map).length > 0 ? map : null);
                }
            })
            .catch(() => {
                if (!cancelled) setHeadcount(null);
            })
            .finally(() => {
                if (!cancelled) setIsLoading(false);
            });

        return () => { cancelled = true; };
    }, [company, year, periodRange]);

    return { headcount, isLoading };
}
