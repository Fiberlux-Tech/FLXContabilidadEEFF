import { useCallback, useEffect, useMemo, useState } from 'react';
import { api } from '@/lib/api';
import { useAuth } from '@/contexts/AuthContext';

interface AdminUser {
    id: number;
    username: string;
    display_name: string;
    is_admin: boolean;
    allowed_views: string[];
    created_at: string;
}

type SectionKey = 'pl' | 'bs' | 'analysis' | 'uploads';

interface SectionDef {
    key: SectionKey;
    title: string;
    items: { id: string; label: string }[];
}

// Hardcoded labels here mirror viewRegistry.ts navLabels but use display-friendly Spanish
// (with proper accents) for this admin UI. They're intentionally decoupled from
// VIEW_TITLE_MAP because the registry uses ASCII-only labels for legacy reasons.
const SECTIONS: SectionDef[] = [
    { key: 'pl', title: 'Estado de Resultados', items: [
        { id: 'pl', label: 'Resumen' },
        { id: 'ingresos', label: 'Ingresos' },
        { id: 'costo', label: 'Costo de Operaciones' },
        { id: 'gasto_venta', label: 'Gastos de Ventas' },
        { id: 'gasto_admin', label: 'Gastos de Administración' },
        { id: 'otros_egresos', label: 'Otros' },
        { id: 'dya', label: 'Depreciación y Amortización' },
        { id: 'resultado_financiero', label: 'Resultado Financiero' },
    ]},
    { key: 'bs', title: 'Balance General', items: [
        { id: 'bs', label: 'Resumen' },
        { id: 'bs_efectivo', label: 'Efectivo y Equivalentes' },
        { id: 'bs_cxc_comerciales', label: 'CxC Comerciales' },
        { id: 'bs_cxc_otras', label: 'Otras CxC' },
        { id: 'bs_cxc_relacionadas', label: 'CxC Relacionadas' },
        { id: 'bs_ppe', label: 'PPE e Intangibles' },
        { id: 'bs_otros_activos', label: 'Otros Activos' },
        { id: 'bs_cxp_comerciales', label: 'CxP Comerciales' },
        { id: 'bs_cxp_otras', label: 'Otras CxP' },
        { id: 'bs_cxp_relacionadas', label: 'CxP Relacionadas' },
        { id: 'bs_provisiones', label: 'Provisiones' },
        { id: 'bs_tributos', label: 'Tributos' },
    ]},
    { key: 'analysis', title: 'Reportes Variados', items: [
        { id: 'analysis_pl_finanzas', label: 'Análisis de Costos/Gastos' },
        { id: 'analysis_planilla', label: 'Análisis de Planilla' },
        { id: 'analysis_proveedores', label: 'Análisis de Proveedores' },
        { id: 'analysis_flujo_caja', label: 'Proxy Flujo de Caja' },
    ]},
    { key: 'uploads', title: 'Carga de Datos', items: [
        { id: 'upload_planilla', label: 'Cargar Planilla' },
    ]},
];

interface RowProps {
    user: AdminUser;
    isSelf: boolean;
    onChange: (updated: AdminUser) => void;
}

function UserRow({ user, isSelf, onChange }: RowProps) {
    // Local edit state so toggles don't fire a save until the user clicks Guardar
    const [draftIsAdmin, setDraftIsAdmin] = useState(user.is_admin);
    const [draftViews, setDraftViews] = useState<Set<string>>(new Set(user.allowed_views));
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState<string | null>(null);

    // Reset draft when the source user changes (e.g. after a save).
    useEffect(() => {
        setDraftIsAdmin(user.is_admin);
        setDraftViews(new Set(user.allowed_views));
        setError(null);
    }, [user.is_admin, user.allowed_views]);

    const dirty =
        draftIsAdmin !== user.is_admin ||
        draftViews.size !== user.allowed_views.length ||
        user.allowed_views.some(v => !draftViews.has(v));

    const toggleView = (id: string) => {
        setDraftViews(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
    };

    const toggleSection = (section: SectionDef, allOn: boolean) => {
        setDraftViews(prev => {
            const next = new Set(prev);
            for (const item of section.items) {
                if (allOn) next.delete(item.id);
                else next.add(item.id);
            }
            return next;
        });
    };

    const sectionAllOn = (section: SectionDef) =>
        section.items.every(i => draftViews.has(i.id));

    const handleSave = async () => {
        setSaving(true);
        setError(null);
        try {
            const updated = await api.patch<AdminUser>(`/api/admin/users/${user.id}`, {
                is_admin: draftIsAdmin,
                allowed_views: Array.from(draftViews),
            });
            onChange(updated);
        } catch (err) {
            setError(err instanceof Error ? err.message : 'Error al guardar');
        } finally {
            setSaving(false);
        }
    };

    const handleCancel = () => {
        setDraftIsAdmin(user.is_admin);
        setDraftViews(new Set(user.allowed_views));
        setError(null);
    };

    const initial = (user.display_name || user.username).charAt(0).toUpperCase();

    return (
        <details className="user-row">
            <summary className="px-5 py-4 flex items-center justify-between hover:bg-surface-alt rounded-lg">
                <div className="flex items-center gap-3 min-w-0">
                    <span className="chev text-[10px] text-txt-muted">▶</span>
                    <div className={`w-9 h-9 rounded-full flex items-center justify-center text-[13px] font-semibold shrink-0
                        ${isSelf ? 'bg-accent text-white' : 'bg-nav-hover text-txt border border-nav-border'}`}>
                        {initial}
                    </div>
                    <div className="min-w-0">
                        <div className="text-[14px] font-semibold text-txt truncate">
                            {user.display_name}
                            {isSelf && <span className="text-xs text-txt-muted font-normal ml-1">(tú)</span>}
                        </div>
                        <div className="text-xs text-txt-muted mt-0.5 truncate">{user.username}</div>
                    </div>
                </div>
                <div
                    className="flex items-center gap-2 shrink-0"
                    title={isSelf ? 'No puedes quitarte tu propio acceso' : ''}
                >
                    <label
                        className={`admin-inline ${draftIsAdmin ? 'is-on' : ''} ${isSelf ? 'is-disabled' : ''}`}
                        onClick={e => e.stopPropagation()}
                    >
                        <input
                            type="checkbox"
                            checked={draftIsAdmin}
                            disabled={isSelf}
                            onChange={e => setDraftIsAdmin(e.target.checked)}
                        />
                        Es administrador
                    </label>
                </div>
            </summary>

            <div className="border-t border-border px-6 py-5 bg-surface-alt">
                {draftIsAdmin ? (
                    <p className="text-[13px] text-txt-secondary italic">
                        Acceso total a todas las vistas. La selección de vistas no aplica a administradores.
                    </p>
                ) : (
                    <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                        {SECTIONS.map(section => {
                            const allOn = sectionAllOn(section);
                            return (
                                <div key={section.key} className="perm-card">
                                    <div className="perm-card-header">
                                        <span className="perm-card-title">{section.title}</span>
                                        <label
                                            className="flex items-center gap-2 text-xs text-txt-secondary cursor-pointer"
                                            onClick={e => e.stopPropagation()}
                                        >
                                            <input
                                                type="checkbox"
                                                checked={allOn}
                                                onChange={() => toggleSection(section, allOn)}
                                                style={{ accentColor: '#D1453B' }}
                                            />
                                            Toda la sección
                                        </label>
                                    </div>
                                    {section.items.map(item => (
                                        <label
                                            key={item.id}
                                            className="perm-row"
                                            onClick={e => e.stopPropagation()}
                                        >
                                            <span>{item.label}</span>
                                            <input
                                                type="checkbox"
                                                checked={draftViews.has(item.id)}
                                                onChange={() => toggleView(item.id)}
                                            />
                                        </label>
                                    ))}
                                </div>
                            );
                        })}
                    </div>
                )}

                {error && (
                    <p className="mt-4 text-sm text-negative">{error}</p>
                )}

                <div className="flex justify-end gap-2 mt-5 pt-5 border-t border-border">
                    <button
                        onClick={handleCancel}
                        disabled={!dirty || saving}
                        className="px-4 py-2 text-sm font-medium border border-border rounded-md bg-surface text-txt
                                   hover:bg-surface-alt disabled:opacity-40 disabled:cursor-not-allowed"
                    >
                        Cancelar
                    </button>
                    <button
                        onClick={handleSave}
                        disabled={!dirty || saving}
                        className="px-4 py-2 text-sm font-medium bg-accent text-white rounded-md
                                   hover:bg-accent-hover disabled:opacity-40 disabled:cursor-not-allowed
                                   shadow-sm"
                    >
                        {saving ? 'Guardando...' : 'Guardar cambios'}
                    </button>
                </div>
            </div>
        </details>
    );
}

export default function AdminUsersPage() {
    const { user: currentUser, refreshUser } = useAuth();
    const [users, setUsers] = useState<AdminUser[] | null>(null);
    const [loadError, setLoadError] = useState<string | null>(null);

    const load = useCallback(async () => {
        setLoadError(null);
        try {
            const data = await api.get<{ users: AdminUser[] }>('/api/admin/users');
            setUsers(data.users);
        } catch (err) {
            setLoadError(err instanceof Error ? err.message : 'Error al cargar usuarios');
        }
    }, []);

    useEffect(() => { load(); }, [load]);

    const handleUpdated = useCallback((updated: AdminUser) => {
        setUsers(prev => prev?.map(u => u.id === updated.id ? updated : u) ?? null);
        // If admin updated themselves (e.g. tweaked another admin's permissions affecting
        // session caches), refresh /me so the local sidebar reflects reality.
        if (currentUser && updated.id === currentUser.id) {
            void refreshUser();
        }
    }, [currentUser, refreshUser]);

    const sortedUsers = useMemo(() => {
        if (!users) return null;
        return [...users].sort((a, b) => {
            // Self first, then admins, then alphabetical
            if (currentUser && a.id === currentUser.id) return -1;
            if (currentUser && b.id === currentUser.id) return 1;
            if (a.is_admin !== b.is_admin) return a.is_admin ? -1 : 1;
            return a.username.localeCompare(b.username);
        });
    }, [users, currentUser]);

    return (
        <div className="flex-1 flex flex-col min-h-0">
            <main className="flex-1 px-8 py-6 space-y-3 overflow-y-auto">
                {loadError && (
                    <div className="bg-accent-light border border-border rounded-md p-4 text-sm text-negative">
                        {loadError}
                    </div>
                )}

                {sortedUsers === null && !loadError && (
                    <div className="flex items-center justify-center py-16">
                        <div className="text-center">
                            <div className="animate-spin rounded-full h-8 w-8 border-2 border-accent border-t-transparent mx-auto mb-4"></div>
                            <p className="text-sm text-txt-muted">Cargando usuarios...</p>
                        </div>
                    </div>
                )}

                {sortedUsers && sortedUsers.length === 0 && (
                    <p className="text-sm text-txt-muted">No hay usuarios.</p>
                )}

                {sortedUsers?.map(u => (
                    <UserRow
                        key={u.id}
                        user={u}
                        isSelf={!!currentUser && currentUser.id === u.id}
                        onChange={handleUpdated}
                    />
                ))}

                <p className="text-xs text-txt-faint mt-6">
                    Para crear, eliminar o cambiar contraseñas de usuarios, usa el script de terminal{' '}
                    <code className="font-mono text-[11px]">backend/scripts/manage_users.py</code>.
                </p>
            </main>
        </div>
    );
}
