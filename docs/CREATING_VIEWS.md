# Creating New Views

Step-by-step guide for adding new detailed views to the dashboard. Every view follows the same pattern: define the view key, create the component, wire it into navigation, and (optionally) add a backend endpoint.

---

## Overview: What Touches What

| Step | File(s) | Required? |
|------|---------|-----------|
| 1. Add view key | `frontend/src/contexts/ReportContext.tsx` | Always |
| 2. Create component | `frontend/src/features/dashboard/YourView.tsx` | Always |
| 3. Register in MainContent | `frontend/src/features/dashboard/MainContent.tsx` | Always |
| 4. Add sidebar nav | `frontend/src/features/dashboard/Sidebar.tsx` | Always |
| 5. Add TypeScript types | `frontend/src/types/index.ts` | If new data shape |
| 6. Add API endpoint | `backend/routes.py` | If new data needed |
| 7. Add endpoint constant | `frontend/src/config/constants.ts` | If new endpoint |
| 8. Update ReportContext loader | `frontend/src/contexts/ReportContext.tsx` | If data comes from load |

---

## Step 1: Add the View Key

In `frontend/src/contexts/ReportContext.tsx`, extend the `View` type union:

```typescript
// Current views:
type View = 'pl' | 'bs' | 'ingresos' | 'costo' | 'gasto_venta' | 'gasto_admin' | 'dya' | 'resultado_financiero' | 'your_view';
```

This key is used everywhere: sidebar active state, MainContent rendering, and any view-specific logic.

**Naming convention:** lowercase snake_case, short, descriptive. Examples: `gastos_admin`, `cuentas_cobrar`, `detalle_cecos`.

---

## Step 2: Create the View Component

Create `frontend/src/features/dashboard/YourView.tsx`. All view components live in the `features/dashboard/` directory — no subdirectories.

### Minimal Template (Display-Only View)

For views that render data already present in `reportData`:

```tsx
import { useMemo } from 'react';
import type { ReportRow } from '@/types';

interface YourViewProps {
  data: ReportRow[];
  months: string[];
}

export default function YourView({ data, months }: YourViewProps) {
  if (!data || data.length === 0) {
    return (
      <div className="text-center py-12 text-gray-500">
        No hay datos disponibles.
      </div>
    );
  }

  return (
    <div className="space-y-6">
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="bg-gray-800 text-white">
              <th className="sticky left-0 z-10 bg-gray-800 px-3 py-1.5 text-left">
                Descripción
              </th>
              {months.map((m) => (
                <th key={m} className="px-3 py-1.5 text-right whitespace-nowrap">
                  {m}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {data.map((row, i) => (
              <tr key={i} className="border-b border-gray-200 hover:bg-blue-50/50">
                <td className="sticky left-0 z-10 bg-white px-3 py-1.5 font-medium">
                  {row.LABEL_KEY}
                </td>
                {months.map((m) => (
                  <td key={m} className={`px-3 py-1.5 text-right tabular-nums
                    ${(row[m] as number) < 0 ? 'text-red-600' : ''}`}>
                    {row[m] != null ? Number(row[m]).toLocaleString('es-PE', {
                      minimumFractionDigits: 2,
                      maximumFractionDigits: 2,
                    }) : ''}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

### Drill-Down Template (Clickable Cells)

For views that support clicking a cell to see journal entries (like IngresosView):

```tsx
import { useState, useCallback } from 'react';
import { api } from '@/lib/api';
import { API_CONFIG } from '@/config/constants';
import type { ReportRow } from '@/types';

interface YourViewProps {
  data: ReportRow[];
  months: string[];
  year: number;
  company: string;
}

interface Selection {
  partida: string;
  month: string;
  filterCol?: string;
  filterVal?: string;
}

export default function YourView({ data, months, year, company }: YourViewProps) {
  const [detailRows, setDetailRows] = useState<ReportRow[]>([]);
  const [selection, setSelection] = useState<Selection | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);

  const handleCellClick = useCallback(async (sel: Selection) => {
    setLoadingDetail(true);
    setSelection(sel);
    try {
      const res = await api.post<{ records: ReportRow[] }>(
        API_CONFIG.ENDPOINTS.DATA_DETAIL,
        { company, year, ...sel }
      );
      setDetailRows(res.records);
    } catch {
      setDetailRows([]);
    } finally {
      setLoadingDetail(false);
    }
  }, [company, year]);

  return (
    <div className="space-y-8">
      {/* Summary table with clickable cells */}
      {/* ... table markup ... */}

      {/* Detail panel (shown after cell click) */}
      {selection && (
        <div className="border rounded-lg p-4">
          <h3 className="font-semibold mb-3">
            Detalle: {selection.partida} — {selection.month}
          </h3>
          {loadingDetail ? (
            <p className="text-gray-500">Cargando...</p>
          ) : (
            <table className="w-full text-sm">
              {/* Detail rows */}
            </table>
          )}
        </div>
      )}
    </div>
  );
}
```

---

## Step 3: Register in MainContent

In `frontend/src/features/dashboard/MainContent.tsx`:

1. Import the component:
```tsx
import YourView from './YourView';
```

2. Add to the title map:
```tsx
const titleMap = {
  pl: 'Estado de Resultados',
  bs: 'Balance General',
  ingresos: 'Ingresos',
  your_view: 'Your View Title',       // ← add
};
```

3. Add the rendering branch (order matters — check specific views first):
```tsx
{currentView === 'your_view' ? (
  <YourView
    data={reportData.your_data}
    months={reportData.months}
    year={reportData.year}
  />
) : currentView === 'ingresos' ? (
  <IngresosView ... />
) : (
  <FinancialTable ... />
)}
```

---

## Step 4: Add Sidebar Navigation

In `frontend/src/features/dashboard/Sidebar.tsx`, add a nav button. Place it in the appropriate section or create a new section.

### Adding to an existing section

```tsx
<button
  onClick={() => setCurrentView('your_view')}
  className={`w-full flex items-center px-3 py-2 text-sm rounded-md transition-colors text-left
    ${currentView === 'your_view'
      ? 'bg-gray-800 text-white'
      : 'text-gray-400 hover:text-white hover:bg-gray-800/50'}`}
>
  <svg className="w-4 h-4 mr-3 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
    {/* Pick an icon from heroicons.com — use outline style */}
  </svg>
  Nombre de la Vista
</button>
```

### Creating a new nav section

```tsx
{/* Section header */}
<div className="flex items-center px-3 py-2 text-xs font-semibold text-gray-500 uppercase tracking-wider">
  <svg className="w-4 h-4 mr-2" ...>{/* section icon */}</svg>
  Section Name
</div>
{/* Buttons underneath, indented by being in same group */}
<button onClick={() => setCurrentView('your_view')} ...>
  Vista Item
</button>
```

### Sidebar conventions
- Icons: 24x24 SVG, `w-4 h-4 mr-3 shrink-0`, outline stroke style
- Active: `bg-gray-800 text-white`
- Inactive: `text-gray-400 hover:text-white hover:bg-gray-800/50`
- Text: Spanish labels, sentence case
- Buttons only appear/are enabled when `reportData` is loaded (use `disabled` prop if needed)

---

## Step 5: Add TypeScript Types (If Needed)

If your view uses data with a new shape, update `frontend/src/types/index.ts`.

### Adding a field to ReportData

```typescript
export interface ReportData {
  pl_summary: ReportRow[];
  bs_summary: ReportRow[];
  ingresos_ordinarios: ReportRow[];
  ingresos_proyectos: ReportRow[];
  costo: ReportRow[];
  gasto_venta: ReportRow[];
  gasto_admin: ReportRow[];
  dya_costo: ReportRow[];
  dya_gasto: ReportRow[];
  resultado_financiero_ingresos: ReportRow[];
  resultado_financiero_gastos: ReportRow[];
  your_data: ReportRow[];              // ← add
  company: string;
  year: number;
  months: string[];
}
```

### Notes on ReportRow

`ReportRow` is a generic `Record<string, string | number | null>`. Every row has:
- A **label column** (e.g., `PARTIDA_PL`, `CUENTA_CONTABLE`, `NIT`) — your view decides which key to use
- **Month columns** (`ENE`, `FEB`, ..., `DIC`) with numeric values
- Optionally a **TOTAL** column

You do NOT need a custom type for most views — `ReportRow[]` handles it.

---

## Step 6: Add Backend Endpoint (If Needed)

Only needed if the view requires data not already in the `/api/data/load` response. Two options:

### Option A: Add data to the existing load response

Best for data derived from the same SQL queries. Modify `services/data_service.py`:

```python
def load_report_data(company: str, year: int, force_refresh: bool = False) -> dict:
    # ... existing logic ...
    result = {
        'pl_summary': ...,
        'bs_summary': ...,
        # ...
        'your_data': _df_to_records(your_dataframe),  # ← add
    }
    return result
```

No other changes needed — `ReportContext.loadData()` already passes through the full response.

### Option B: Add a separate endpoint

Best for data that requires different queries or is expensive to compute. In `backend/routes.py`:

```python
@api_bp.route('/data/your-endpoint', methods=['POST'])
@login_required
def get_your_data():
    body = request.get_json(silent=True) or {}
    company, year, error = _validate_company_year(body)
    if error:
        return error

    try:
        # Your data fetching logic
        data = your_service_function(company, year)
        return jsonify({'records': data})
    except Exception as exc:
        logger.exception("Error loading your data")
        return jsonify({'error': 'Error interno del servidor'}), 500
```

Then add the endpoint constant in `frontend/src/config/constants.ts`:

```typescript
ENDPOINTS: {
  // ... existing
  YOUR_ENDPOINT: '/api/data/your-endpoint',
}
```

### Backend conventions
- Always use `@login_required` decorator
- Always validate with `_validate_company_year(body)`
- Return 400 for validation errors, 500 for server errors
- Use `_df_to_records()` or `_sanitize_value()` to convert pandas → JSON-safe dicts
- Log errors with `logger.exception()`

---

## Step 7: Data Flow Decision Tree

```
Does your view need data not in the current /api/data/load response?
│
├── NO → Use existing reportData fields as props
│        (Steps 1-4 only, fastest path)
│
├── YES, derived from same raw SQL data
│   └── Add to load_report_data() in data_service.py (Option A)
│       Update ReportData type → done
│
└── YES, needs different SQL queries or is expensive
    └── Create separate endpoint (Option B)
        Call it from the view component or ReportContext
```

---

## Style Reference

### Tables
| Element | Classes |
|---------|---------|
| Table wrapper | `overflow-x-auto` |
| Table | `w-full text-sm border-collapse` |
| Header row | `bg-gray-800 text-white` |
| Header cell | `px-3 py-1.5 text-right whitespace-nowrap` |
| Label header (sticky) | `sticky left-0 z-10 bg-gray-800 px-3 py-1.5 text-left` |
| Body row | `border-b border-gray-200 hover:bg-blue-50/50` |
| Body cell | `px-3 py-1.5 text-right tabular-nums` |
| Label cell (sticky) | `sticky left-0 z-10 bg-white px-3 py-1.5 font-medium` |
| Negative values | `text-red-600` |
| Bold/summary rows | `font-bold bg-gray-50` |
| Empty state | `text-center py-12 text-gray-500` |

### Numbers
Format with Peruvian locale:
```tsx
value.toLocaleString('es-PE', { minimumFractionDigits: 2, maximumFractionDigits: 2 })
```

Or use the shared `formatNumber()` utility from `@/utils/format.ts` if available.

### Clickable cells
```tsx
<td
  className="cursor-pointer hover:bg-blue-100 hover:underline"
  onClick={() => handleCellClick({ partida, month })}
>
  {formattedValue}
</td>
```

Only make cells clickable when the value is non-zero and non-null.

---

## Checklist

When creating a new view, verify:

- [ ] View key added to `View` type union in ReportContext
- [ ] Component created in `features/dashboard/`
- [ ] Component handles empty data state (shows "No hay datos disponibles")
- [ ] Registered in MainContent with title and render branch
- [ ] Sidebar button added with icon, correct active/inactive styles
- [ ] TypeScript types updated if new data fields
- [ ] Backend endpoint added if new data needed (with auth + validation)
- [ ] Endpoint constant added to `constants.ts` if new endpoint
- [ ] All user-facing text is in Spanish
- [ ] Numbers formatted with `es-PE` locale, 2 decimal places
- [ ] Table has sticky left column for labels
- [ ] Negative values shown in red
- [ ] Builds without TypeScript errors (`npm run build`)
