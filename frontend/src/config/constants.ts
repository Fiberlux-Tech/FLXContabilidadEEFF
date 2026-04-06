export const API_CONFIG = {
  ENDPOINTS: {
    COMPANIES: '/api/companies',
    HEALTH: '/api/health',
    DATA_LOAD: '/api/data/load',
    DATA_LOAD_PL: '/api/data/load-pl',
    DATA_LOAD_BS: '/api/data/load-bs',
    DATA_DETAIL: '/api/data/detail',
    EXPORT_EXCEL: '/api/export/excel',
    EXPORT_PDF: '/api/export/pdf',
    EXPORT_ALL: '/api/export/all',
    EXPORT_DOWNLOAD: '/api/export/download',
    HEADCOUNT: '/api/headcount',
    HEADCOUNT_YM: '/api/headcount/ym',
  },

  HTTP: {
    CREDENTIALS_MODE: 'include',
    CONTENT_TYPE_HEADER: 'Content-Type',
    CONTENT_TYPE_JSON: 'application/json',
    METHOD_GET: 'GET',
    METHOD_POST: 'POST',
  },
} as const;

export const UI_LABELS = {
  WELCOME_BACK: 'Iniciar Sesion',
  USUARIO: 'Usuario',
  CONTRASENA: 'Contraseña',
  PROCESSING: 'Procesando...',
  LOGIN: 'Ingresar',
  LOGOUT: 'Cerrar Sesion',
} as const;
