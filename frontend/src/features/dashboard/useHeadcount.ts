import { useState, useEffect } from 'react';
import { api } from '@/lib/api';
import { API_CONFIG } from '@/config';

/** CENTRO_COSTO → { month_name → headcount, TOTAL_AVG → average } */
export type HeadcountMap = Record<string, Record<string, number>>;

interface HeadcountResponse {
    headcount: HeadcountMap;
}

export function useHeadcount(company: string, year: number) {
    const [headcount, setHeadcount] = useState<HeadcountMap | null>(null);
    const [isLoading, setIsLoading] = useState(false);

    useEffect(() => {
        if (!company || !year) {
            setHeadcount(null);
            return;
        }

        let cancelled = false;
        setIsLoading(true);

        api.get<HeadcountResponse>(
            `${API_CONFIG.ENDPOINTS.HEADCOUNT}?company=${encodeURIComponent(company)}&year=${year}`
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
    }, [company, year]);

    return { headcount, isLoading };
}
