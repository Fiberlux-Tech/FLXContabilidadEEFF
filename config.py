import os
from openpyxl.styles import PatternFill

# -----------------------------------------------------------------------------
# STEP 1: SETUP AND CONFIGURATION
# -----------------------------------------------------------------------------

# Usa os.path.expanduser('~') para obtener el directorio de inicio del usuario (C:\Users\Username)
USER_PROFILE_DIR = os.path.expanduser('~')

# El nombre de la carpeta raíz de sincronización de OneDrive.
ONEDRIVE_ROOT_NAME = r"OneDrive - FIBERLUX S.A.C"

# La ruta específica *dentro* de la carpeta raíz de OneDrive para los archivos de Excel.
EXCEL_SUB_PATH = r"Financial Planning Team - Documents\06. PLANTILLAS ECONOMICAS"

# La ruta específica *dentro* de la carpeta raíz de OneDrive para la base de datos de Access.
DATABASE_SUB_PATH = r"Financial Planning Team - Documents\00. DATA BASE\Plantillas Economicas.accdb"

# Construcción de la ruta base de OneDrive
ONEDRIVE_BASE_PATH = os.path.join(USER_PROFILE_DIR, ONEDRIVE_ROOT_NAME)

# Ruta final a la carpeta de Excel que contiene las plantillas
EXCEL_FOLDER_PATH = os.path.join(ONEDRIVE_BASE_PATH, EXCEL_SUB_PATH)

# Ruta a la carpeta histórica para archivar archivos procesados
HISTORICO_FOLDER_PATH = os.path.join(EXCEL_FOLDER_PATH, "HISTORICO")

# Ruta final a tu base de datos de Access
DATABASE_PATH = os.path.join(ONEDRIVE_BASE_PATH, DATABASE_SUB_PATH)

# -----------------------------------------------------------------------------
# DEFINICIONES DE NOMBRES DE HOJAS Y TABLAS
# -----------------------------------------------------------------------------

# Nombre de la única hoja de trabajo
PLANTILLA_SHEET_NAME = "PLANTILLA"

# Definiciones de nombres de las tres nuevas tablas en Access
HEADER_TABLE_NAME = "transactionTable"
FIXED_COST_TABLE_NAME = "FixedCosts"
RECURRING_TABLE_NAME = "recurringServiceDetails"

# Definiciones para la tabla de emails
SALESMAN_TABLE_NAME = "emails"
SALESMAN_NAME_COLUMN = "salesman"
SALESMAN_EMAIL_COLUMN = "email"

# -----------------------------------------------------------------------------
# CONSTANTES DE EXCEL Y VARIABLES DE TRABAJO
# -----------------------------------------------------------------------------

# Diccionario que mapea nombres de variables a sus nuevas direcciones de celda en Excel
variables_to_extract = {
    'unidadNegocio': 'D5',
    'clientName': 'D7',
    'companyID': 'D9',
    'salesman': 'D11',
    'orderID': 'D13',
    'tipoCambio': 'D15',
    'costoCapital_annual': 'D17',
    'plazoContrato': 'D19',
    'tipoPago': 'D21',  # ## ADD THIS LINE ##
    'MRC': 'H9',
    'NRC': 'H11',
    'comisionesPersonal': 'H23',
}

# Fila de inicio para el procesamiento y validación de tablas de detalle
DETAIL_START_ROW = 37

# --- COLUMNAS PARA LA TABLA DE COSTOS FIJOS (C-I) ---

# Columnas para la validación condicional y categorías
FIXED_CATEGORY_COL = 'C'       # CATEGORIA (Validation check)
FIXED_TIPO_SERVICIO_COL = 'D'  # TIPO DE SERVICIO (Validation check against listaCotizaciones)
FIXED_TICKET_COL = 'E'         # TICKER (Conditional check for emptiness)

# Columnas para la extracción de valores numéricos y de texto
FIXED_UBICACION_COL = 'F'      # UBICACION
FIXED_Q_COL = 'G'              # CANTIDAD
FIXED_COST_UNITARIO_COL = 'H'  # COSTO UNITARIO
FIXED_COST_TOTAL_COL = 'I'     # TOTAL (Suma de Costos de Instalación)


# --- COLUMNAS PARA LA TABLA DE SERVICIOS RECURRENTES (L-T) ---

RECURRING_SERVICE_COL = 'L'    # Tipo de Servicio (Validation check contra listaServicios)
RECURRING_NOTA_COL = 'M'       # NOTA
RECURRING_UBICACION_COL = 'N'  # UBICACIÓN
RECURRING_Q_COL = 'O'          # Q (Cantidad) <--- CORREGIDO (Usuario: Columna O)
RECURRING_REVENUE_UNIT_COL = 'P' # P (Precio Unitario de Ingreso) <--- NUEVA VARIABLE
RECURRING_COST_1_COL = 'R'     # Costo Unitario (1) / CU1
RECURRING_COST_2_COL = 'S'     # Costo Unitario (2) / CU2
RECURRING_PROVEEDOR_COL = 'T'  # PROVEEDOR

# Define el color de relleno rojo para celdas inválidas (usado en validación)
RED_FILL = PatternFill(start_color="FF3300", end_color="FF3300", fill_type="solid")