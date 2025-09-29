import os
import openpyxl
from openpyxl.styles import PatternFill
import numpy_financial as npf
import numpy as np
import pandas as pd
import pyodbc
import win32com.client as win32
from datetime import datetime
import shutil
import re
import config


# -----------------------------------------------------------------------------
# STEP 2: FUNCTIONS
# -----------------------------------------------------------------------------

def create_results_dataframe(results_list):
    """
    Converts a list of dictionaries into a pandas DataFrame.
    """
    if not results_list:
        return pd.DataFrame()  # Return empty DataFrame if list is empty
    return pd.DataFrame(results_list)

def get_validation_list(db_path, table_name, column_name):
    """Fetches a list of unique values from an Access database table."""
    conn_str = r'DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=' + db_path + r';'
    cnxn = pyodbc.connect(conn_str)
    cursor = cnxn.cursor()
    sql = f"SELECT [{column_name}] FROM [{table_name}]"
    rows = cursor.execute(sql).fetchall()
    valid_values = {row[0] for row in rows}
    cursor.close()
    cnxn.close()
    return valid_values

def validate_excel_data(file_path, valid_servicios, valid_cotizaciones, red_fill):
    """
    Validates data in the single PLANTILLA sheet against the FINAL rules:
    - Col L against valid_servicios.
    - Col C against fixed categories.
    - Col D (Tipo de Servicio) against valid_cotizaciones (Master List).
    - Col E (Ticker) conditionally checked for emptiness if Col C requires it.
    """
    wb = openpyxl.load_workbook(file_path, data_only=True)
    plantilla_sheet = wb[config.PLANTILLA_SHEET_NAME]
    file_is_clean = True

    start_row = config.DETAIL_START_ROW
    end_row = plantilla_sheet.max_row + 1

    # --- VALID CATEGORY CONSTANTS ---
    # 1. CATEGORIES: All accepted values for Column C
    VALID_CATEGORIES = {"FACTIBILIDAD", "EQUIPAMIENTO", "INVERSIÓN", "INVERSION"}

    # 2. TRIGGER: Values in Column C that require a Ticker in Column E
    TRIGGER_CATEGORIES = {"EQUIPAMIENTO"}
    # --- END CONSTANTS ---

    # --- SETUP COLUMN POINTERS ---
    TIPO_SERVICIO_COL = config.FIXED_TIPO_SERVICIO_COL  # Column D
    TICKET_COL = config.FIXED_TICKET_COL  # Column E
    CATEGORY_COL = config.FIXED_CATEGORY_COL  # Column C
    RECURRING_COL = config.RECURRING_SERVICE_COL  # Column L

    # --------------------------------------------------------------------------
    # VALIDATION 1: Check column L (RECURRING_SERVICE_COL) for valid services
    # --------------------------------------------------------------------------
    for row in range(start_row, end_row):
        cell = plantilla_sheet[f'{RECURRING_COL}{row}']
        if cell.value and cell.value not in valid_servicios:
            cell.fill = red_fill
            file_is_clean = False

    # --------------------------------------------------------------------------
    # VALIDATIONS 2, 3, & 4: Fixed Costs Table Checks (C, D, E)
    # --------------------------------------------------------------------------

    for row in range(start_row, end_row):

        c_cell = plantilla_sheet[f'{CATEGORY_COL}{row}']
        d_cell = plantilla_sheet[f'{TIPO_SERVICIO_COL}{row}']
        e_cell = plantilla_sheet[f'{TICKET_COL}{row}']

        c_value = str(c_cell.value).strip().upper() if c_cell.value else None

        # Optimization: Stop if the row is completely empty based on the main columns
        if c_cell.value is None and d_cell.value is None and e_cell.value is None:
            break

        # --- VALIDATION 2: Check Column C (CATEGORIA) against VALID_CATEGORIES ---
        if c_value and c_value not in VALID_CATEGORIES:
            c_cell.fill = red_fill
            file_is_clean = False

        # --- VALIDATION 3: Check Column D (TIPO DE SERVICIO) against valid_cotizaciones (MASTER LIST) ---
        if d_cell.value and d_cell.value not in valid_cotizaciones:
            d_cell.fill = red_fill
            file_is_clean = False

        # --- VALIDATION 4: Conditional Check on Column E (TICKER) ---
        # Rule: If category is EQUIPAMIENTO, INVERSION, or INVERSIÓN, E must not be empty.
        if c_value in TRIGGER_CATEGORIES:
            e_value_is_empty = (e_cell.value is None or str(e_cell.value).strip() == "")

            if e_value_is_empty:
                # Mark the E cell as invalid
                e_cell.fill = red_fill
                file_is_clean = False
    return file_is_clean, wb

def calculate_financial_metrics(
        costoCapital_annual,
        plazoContrato,
        # Line-item sum (for record/validation)
        total_monthly_revenue_line_item_sum,
        total_monthly_expense,
        # Extracted/Input variables
        MRC,  # THE OFFICIAL MRC VALUE FROM CELL H9 (used for cash flow)
        NRC,
        comisionesPersonal,
        costoInstalacion,
        tipoCambio,
        # Header/ID variables for output dictionary
        clientName, companyID, salesman, orderID, unidadNegocio, submission_timestamp
):
    """
    Calculates key financial metrics (VAN, TIR, Payback) based on cash flows.
    Uses the Official MRC (from H9) for cash flow and the calculated CostoInstalacion
    and Total Monthly Expense from the line-item tables.
    """
    cash_flows = []
    # total_revenues_calculated tracks the official revenue used in the financial model
    total_revenues_calculated = NRC
    total_expenses = 0
    payback_period = None
    cumulative_cash_flow = 0

    # 1. Period 0: Upfront Costs
    # Apply currency conversion to the upfront costs
    upfront_costs = (costoInstalacion * tipoCambio) + comisionesPersonal
    period_0_cash_flow = -upfront_costs

    cash_flows.append(period_0_cash_flow)
    cumulative_cash_flow += period_0_cash_flow
    total_expenses += abs(period_0_cash_flow)

    # Apply currency conversion to the monthly expenses
    total_monthly_expense_converted = total_monthly_expense * tipoCambio

    # 2. Periods 1 to N: Monthly Cash Flows
    for period in range(1, int(plazoContrato) + 1):
        # CORRECTED LOGIC: Use the OFFICIAL MRC from the H9 input cell for cash flow
        monthly_revenue_for_cash_flow = MRC

        monthly_cash_flow = monthly_revenue_for_cash_flow - total_monthly_expense_converted

        if period == 1:
            # ADD NRC to the first month's cash flow
            monthly_cash_flow += NRC

        cash_flows.append(monthly_cash_flow)

        # Track the total official revenue used for financial calculations
        total_revenues_calculated += monthly_revenue_for_cash_flow
        total_expenses += total_monthly_expense_converted
        cumulative_cash_flow += monthly_cash_flow

        # Payback Calculation
        if payback_period is None and cumulative_cash_flow >= 0:
            # Simple Payback Period is the month number when cumulative cash flow turns positive
            payback_period = period

    # 3. Final Metric Calculation
    gross_margin = total_revenues_calculated - total_expenses

    # Handle the potential for division by zero
    costo_instalacion_ratio = upfront_costs / total_revenues_calculated if total_revenues_calculated != 0 else 0

    # The annual rate (costoCapital_annual) is converted to monthly: rate / 12
    npv = npf.npv(costoCapital_annual / 12, cash_flows)

    # --- CORRECCIÓN 1: Manejo de errores de TIR (para enviar 'N/A' como texto) ---
    try:
        # 1. Use the calculation (adding guess=0.1 for robustness is recommended)
        irr = npf.irr(cash_flows)

        # 2. Check for NaN or Inf
        if not np.isfinite(irr):
            final_TIR = 'N/A'
        else:
            # --- CORRECT LOGIC ---: Format the successful number for the Access Short Text field
            # The line that was previously failing is fixed here.
            final_TIR = f"{irr:.6f}"

            # 3. Catch the exception and define 'e' for logging the failure reason
    except Exception as e:
        # Use the variable 'e' here to log what went wrong.
        print(f"DEBUG: npf.irr FAILED to find root or failed post-calculation. Error: {e}")
        final_TIR = 'N/A'

        # 4. Return Comprehensive Output Dictionary
    return {
        'totalRevenue': round(total_revenues_calculated,4),
        'totalExpense': round(total_expenses,4),
        'paybackPeriod': payback_period,
        # Using the corrected, database-safe key:
        'installationCostRatio': costo_instalacion_ratio,
        'grossMargin': round(gross_margin,4),
        'TIR': final_TIR,  # Uses the prepared variable
        'VAN': round(npv,4),

        # Key inputs for the header table
        'MRC': round(MRC,4),
        'NRC': round(NRC,4),
        'plazoContrato': plazoContrato,
        'comisionesPersonal': round(comisionesPersonal,4),
        'costoInstalacion': round(costoInstalacion,4),
        'tipoCambio': round(tipoCambio,4),
        'costoCapital_annual': costoCapital_annual,
        'totalRevenueLineItemSum': round(total_monthly_revenue_line_item_sum,4),

        # Header variables
        'clientName': clientName,
        'companyID': companyID,
        'salesman': salesman,
        'orderID': orderID,
        'unidadNegocio': unidadNegocio,
        'timestamp': submission_timestamp
    }

def append_to_access_database_minimized(header_df, fixed_costs_df, recurring_df, db_path):
    """
    Appends three pandas DataFrames to their respective tables in the Access database.
    """
    # ... (connection string setup remains the same)
    conn_str = (r'DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=' + db_path + r';')
    cnxn = pyodbc.connect(conn_str)
    cursor = cnxn.cursor()

    # Define the three tables and their corresponding DataFrames using config constants
    tables_to_insert = [
        (config.HEADER_TABLE_NAME, header_df),
        (config.FIXED_COST_TABLE_NAME, fixed_costs_df),
        (config.RECURRING_TABLE_NAME, recurring_df),
    ]

    for table_name, df in tables_to_insert:
        if df.empty:
            # Handle cases where a detail table is empty (e.g., no fixed costs)
            print(f"Advertencia: DataFrame para la tabla '{table_name}' está vacío. Omitiendo inserción.")
            continue

        columns = ', '.join(f"[{col}]" for col in df.columns)
        placeholders = ', '.join('?' * len(df.columns))
        sql = f"INSERT INTO [{table_name}] ({columns}) VALUES ({placeholders})"

        # Use .fillna('') to handle None values for Short Text fields in Access
        for _, row in df.fillna('').iterrows():
            try:
                # Convert the row tuple to a list to handle potential pyodbc errors with numpy dtypes
                cursor.execute(sql, list(row))
            except pyodbc.Error as e:
                print(f"Error al insertar fila en [{table_name}]: {e}")
                print(f"Fila problemática: {row.to_dict()}")
                # You might want to raise the error here if the failure is critical

    cnxn.commit()
    cursor.close()
    cnxn.close()

def move_file_to_historico(file_path, base_dest_path, unidad_negocio_value, client_name, submission_timestamp):
    """
    Moves a processed file to a subfolder within the HISTORICO directory
    and renames the file to clientname_year_month.xlsx.
    """
    # 1. Sanitize the folder name (Existing Logic)
    safe_folder_name = re.sub(r'[^\w\s-]', '_', str(unidad_negocio_value)).strip()
    safe_folder_name = re.sub(r'[-\s]+', '_', safe_folder_name)
    safe_folder_name = safe_folder_name.upper()

    # 2. Generate the New File Name (New Logic)
    clean_client_name = re.sub(r'[\s]+', '_', str(client_name)).strip('_')
    clean_client_name = re.sub(r'[^\w_]', '', clean_client_name)

    try:
        dt_object = datetime.strptime(submission_timestamp, "%Y-%m-%d %H:%M:%S")
        date_suffix = dt_object.strftime("%Y_%m_%d")
    except ValueError:
        print(f"Advertencia: Formato de tiempo invalido: '{submission_timestamp}'. Usando fecha actual.")
        date_suffix = datetime.now().strftime("%Y_%m_%d")

    base_file_name = f"{clean_client_name}_{date_suffix}"
    extension = ".xlsx"
    new_file_name = f"{base_file_name}{extension}"

    # 3. Check for valid destination folder (Existing Logic)
    valid_folders = {"CORPORATIVO", "ESTADO", "GIGALAN"}

    if safe_folder_name in valid_folders:
        # 3a. Construct the full destination folder path
        dest_folder = os.path.join(base_dest_path, safe_folder_name)

        # 3b. Ensure the destination folder exists
        if not os.path.exists(dest_folder):
            print(f"Folder para archivar '{dest_folder}' No se encontro. Creandolo...")
            os.makedirs(dest_folder)

        # 4. Conflict Resolution
        counter = 1
        final_dest_path = os.path.join(dest_folder, new_file_name)

        # Keep checking until a unique path is found
        while os.path.exists(final_dest_path):
            print(f"Archivo '{new_file_name}' ya existe. Probando con nuevo nombre...")
            new_file_name = f"{base_file_name}_{counter}{extension}"
            final_dest_path = os.path.join(dest_folder, new_file_name)
            counter += 1

        # 5. Move and Rename the file
        try:
            shutil.move(file_path, final_dest_path)
            print(f"Cambio de nombre y archivado exitoso como: {new_file_name} en {dest_folder}")
            return True
        except Exception as e:
            print(f"Error moviendo/renombrando archivo '{os.path.basename(file_path)}' a '{new_file_name}': {e}")
            return False
    else:
        print(
            f"Advertencia: Valor de 'unidadNegocio' '{unidad_negocio_value}' resulta en un folder invalido '{safe_folder_name}' para su archivado. No se movio el archivo.")
        return False

def get_salesman_email(db_path, salesman_name):
    """
    Fetches the email address for a given salesman from the Access database.
    """
    # Fallback/Default Email in case of lookup failure
    DEFAULT_EMAIL = "sternero@fiberlux.pe"
    conn_str = r'DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=' + db_path + r';'
    cnxn = None

    try:
        cnxn = pyodbc.connect(conn_str)
        cursor = cnxn.cursor()

        # SQL query usa constantes de config
        sql = f"""
            SELECT [{config.SALESMAN_EMAIL_COLUMN}] 
            FROM [{config.SALESMAN_TABLE_NAME}] 
            WHERE [{config.SALESMAN_NAME_COLUMN}] = ?
        """

        # Execute with parameter for the salesman's name
        cursor.execute(sql, (salesman_name,))
        row = cursor.fetchone()

        if row:
            # Return the email if found
            return str(row[0]).strip()
        else:
            print(
                f"Advertencia: No se encontro vendedor '{salesman_name}' en la tabla de 'emails'. Usando default email.")
            return DEFAULT_EMAIL

    except pyodbc.Error as e:
        print(f"Erorr en la base de datos en la busqueda de correo: {e}")
        return DEFAULT_EMAIL

    finally:
        if cnxn:
            cnxn.close()

# --- NUEVAS FUNCIONES DE CONFIRMACIÓN Y ENVÍO ---

def get_send_approval(recipient, subject):
    """
    Prompts the user for confirmation before sending an email.
    """
    print("\n" + "=" * 60)
    print(f"| REQUERIMIENTO DE CONFIRMACIÓN DE ENVÍO DE CORREO")
    print(f"|      Para: {recipient}")
    print(f"|      Asunto: {subject}")
    print("=" * 60)

    while True:
        # Pide confirmación
        user_input = input("¿Deseas ENVIAR este correo? (Y/N): ").strip().lower()
        if user_input in ['yes', 'Y', 'y']:
            return True
        elif user_input in ['no', 'N', 'n']:
            print("Envío cancelado por el usuario.")
            return False
        else:
            print("Input inválido. Por favor, ingresa 'Y' o 'N'.")

def send_outlook_email(recipient, subject, body, attachment_path=None):
    """
    Sends an email using the local Outlook application via win32com, optionally with an attachment,
    after receiving manual confirmation from the user.
    """
    # *** PASO DE CONFIRMACIÓN AÑADIDO ***
    if not get_send_approval(recipient, subject):
        return  # Si el usuario dice 'N', termina la función aquí.
    # ***********************************

    try:
        # Check if Outlook is running and available
        outlook = win32.Dispatch('outlook.application')
        mail = outlook.CreateItem(0)  # 0 is for MailItem

        mail.To = recipient
        mail.Subject = subject
        # Use HTML body for better formatting
        mail.HTMLBody = f"<html><body>{body}</body></html>"

        if attachment_path:
            mail.Attachments.Add(attachment_path)

        mail.Send()
        print(f"Se envió email exitosamente a {recipient} con asunto: '{subject}'.")

    except Exception as e:
        print(f"Fallo al enviar correo a {recipient}. Asegurate que outlook este abierto. Error: {e}")

# -----------------------------------------------------------------------------

def get_manual_approval(metrics_dict, is_estado_flow=False):
    """
    Muestra las métricas financieras y solicita la aprobación manual del usuario.

    Args:
        metrics_dict (dict): El diccionario de métricas financieras.
        is_estado_flow (bool): Indica si el flujo es para la unidad de negocio 'ESTADO'.
                               Si es True, el resumen completo no se vuelve a imprimir.

    Returns:
        bool: True si el usuario aprueba, False si no lo hace.
    """
    # Usar la nueva función de display de forma condicional
    # En el flujo ESTADO, ya se mostraron los headers. Aquí solo mostramos el resumen final.
    display_financial_summary(metrics_dict, show_headers=not is_estado_flow)

    while True:
        user_input = input("SE APRUEBA? (Y/N): ").strip().lower()
        if user_input in ['y', 'yes']:
            return True
        elif user_input in ['n', 'no']:
            return False
        else:
            print("Input inválido. Por favor, ingrese 'Y' o 'N'.")

# -----------------------------------------------------------------------------

def calculate_state_commission(first_metrics, calculator_function, variables_to_pass):
    """
    Handles the conditional commission calculation flow for the 'ESTADO' business unit.

    Args:
        first_metrics (dict): The financial results dictionary calculated with comisionesPersonal = 0.
        calculator_function (function): Reference to the calculate_financial_metrics function.
        variables_to_pass (dict): Dictionary of all necessary variables for the calculator_function.

    Returns:
        dict: The final financial metrics dictionary, or the original metrics if commission is not applied.
    """

    total_revenues = first_metrics['totalRevenue']
    gross_margin = first_metrics['grossMargin']

    if total_revenues == 0:
        print("Advertencia: Ingresos totales son cero. No se puede calcular la comisión.")
        return first_metrics

    # Calcular Rentabilidad sin comisión (para base de reglas)
    rentabilidad_sin_comision = gross_margin / total_revenues

    # Ahora usamos la nueva función de display para el primer resumen
    display_financial_summary(first_metrics, show_headers=True)

    while True:
        user_input = input("¿Está listo para evaluar con comisión? (Y/N): ").strip().lower()
        if user_input in ['n', 'no']:
            print("Evaluación de comisión omitida. Se procede con comision de 0.")
            return first_metrics
        elif user_input in ['y', 'yes']:
            break
        else:
            print("Input inválido. Por favor, ingrese 'Y' o 'N'.")

    is_pago_unico = False
    while True:
        user_input = input(
            "¿Es este un proyecto de pago único? (Y/N, si N, se procesará como recurrente): ").strip().lower()
        if user_input in ['y', 'yes']:
            is_pago_unico = True
            break
        elif user_input in ['n', 'no']:
            break
        else:
            print("Input inválido. Por favor, ingrese 'Y' o 'N'.")

    final_commission_amount = 0.0
    commission_rate = 0.0

    if is_pago_unico:

        limit_pen = float('inf')

        if 0.30 <= rentabilidad_sin_comision <= 0.35:
            commission_rate = 0.01
            limit_pen = 11000
        elif 0.35 < rentabilidad_sin_comision <= 0.39:
            commission_rate = 0.02
            limit_pen = 12000
        elif 0.39 < rentabilidad_sin_comision <= 0.49:
            commission_rate = 0.03
            limit_pen = 13000
        elif 0.49 < rentabilidad_sin_comision <= 0.59:
            commission_rate = 0.04
            limit_pen = 14000
        elif rentabilidad_sin_comision > 0.59:
            commission_rate = 0.05
            limit_pen = 15000

        calculated_commission = total_revenues * commission_rate

        if commission_rate > 0.0:
            final_commission_amount = min(calculated_commission, limit_pen)
            print(
                f"Comisión ({commission_rate:.2%}) calculada: {calculated_commission:,.2f} | Tope PEN: {limit_pen:,.2f}")
            print(f"Comisión PAGO ÚNICO aplicada: {final_commission_amount:,.2f}")
        else:
            print("\nRentabilidad menor a 30%. NO DEBERÍA APLICAR COMISIÓN AUTOMÁTICA.")
            while True:
                override_input = input("¿QUIERE APLICAR COMISIÓN MANUALMENTE? (Y/N): ").strip().lower()
                if override_input in ['y', 'yes']:
                    while True:
                        try:
                            manual_rate = float(input("Indique la comisión (en decimal, ej: 1% es 0.01): ").strip())
                            final_commission_amount = total_revenues * manual_rate
                            print(f"Comisión MANUAL ({manual_rate:.2%}) aplicada: {final_commission_amount:,.2f}")
                            break
                        except ValueError:
                            print("Input inválido. Por favor, ingrese un número decimal (ej: 0.01).")
                    break
                elif override_input in ['n', 'no']:
                    print("No se aplica comisión. Se procede con 0.")
                    return first_metrics
                else:
                    print("Input inválido. Por favor, ingrese 'Y' o 'N'.")

    else:
        plazo = first_metrics['plazoContrato']
        payback = first_metrics['paybackPeriod']
        mrc = first_metrics['MRC']
        payback_ok = (payback is not None)
        limit_mrc_multiplier = 0.0

        if plazo == 12:
            if 0.30 <= rentabilidad_sin_comision <= 0.35 and payback_ok and payback <= 7:
                commission_rate = 0.025
                limit_mrc_multiplier = 0.8
            elif 0.35 < rentabilidad_sin_comision <= 0.39 and payback_ok and payback <= 7:
                commission_rate = 0.03
                limit_mrc_multiplier = 0.9
            elif rentabilidad_sin_comision > 0.39 and payback_ok and payback <= 6:
                commission_rate = 0.035
                limit_mrc_multiplier = 1.0
        elif plazo == 24:
            if 0.30 <= rentabilidad_sin_comision <= 0.35 and payback_ok and payback <= 11:
                commission_rate = 0.025
                limit_mrc_multiplier = 0.8
            elif 0.35 < rentabilidad_sin_comision <= 0.39 and payback_ok and payback <= 11:
                commission_rate = 0.03
                limit_mrc_multiplier = 0.9
            elif rentabilidad_sin_comision > 0.39 and payback_ok and payback <= 10:
                commission_rate = 0.035
                limit_mrc_multiplier = 1.0
        elif plazo == 36:
            if 0.30 <= rentabilidad_sin_comision <= 0.35 and payback_ok and payback <= 19:
                commission_rate = 0.025
                limit_mrc_multiplier = 0.8
            elif 0.35 < rentabilidad_sin_comision <= 0.39 and payback_ok and payback <= 19:
                commission_rate = 0.03
                limit_mrc_multiplier = 0.9
            elif rentabilidad_sin_comision > 0.39 and payback_ok and payback <= 18:
                commission_rate = 0.035
                limit_mrc_multiplier = 1.0
        elif plazo == 48:
            if 0.30 <= rentabilidad_sin_comision <= 0.35 and payback_ok and payback <= 26:
                commission_rate = 0.02
                limit_mrc_multiplier = 0.8
            elif 0.35 < rentabilidad_sin_comision <= 0.39 and payback_ok and payback <= 26:
                commission_rate = 0.025
                limit_mrc_multiplier = 0.9
            elif rentabilidad_sin_comision > 0.39 and payback_ok and payback <= 25:
                commission_rate = 0.03
                limit_mrc_multiplier = 1.0

        if commission_rate > 0.0:
            calculated_commission = total_revenues * commission_rate
            limit_mrc_amount = mrc * limit_mrc_multiplier
            final_commission_amount = min(calculated_commission, limit_mrc_amount)
            print(
                f"Comisión ({commission_rate:.2%}) calculada: {calculated_commission:,.2f} | Tope MRC ({limit_mrc_multiplier}x): {limit_mrc_amount:,.2f}")
            print(f"Comisión RECURRENTE aplicada: {final_commission_amount:,.2f}")
        else:
            print(
                f"No se cumplió ninguna regla para Plazo {plazo} y Rentabilidad {rentabilidad_sin_comision:.2%}. Comisión 0.")
            return first_metrics

    variables_to_pass['comisionesPersonal'] = final_commission_amount
    final_metrics = calculator_function(**variables_to_pass)
    final_metrics['file_path'] = first_metrics['file_path']
    final_metrics['comisionesPersonal'] = final_commission_amount
    final_metrics['costoInstalacion'] = first_metrics['costoInstalacion']
    final_metrics['tipoCambio'] = first_metrics['tipoCambio']

    print("\n" + "#" * 80)
    print(f"| RECALCULADO: Métricas actualizadas con Comisión: {final_commission_amount:,.2f}")
    print("#" * 80)

    return final_metrics


def display_financial_summary(metrics, show_headers=True):
    """
    Imprime un resumen formateado de las métricas financieras del proyecto.

    Args:
        metrics (dict): Diccionario que contiene todas las métricas y datos del proyecto.
        show_headers (bool, optional): Si es True, muestra el encabezado del proyecto.
                                        Si es False, solo muestra el resumen financiero.
    """
    payback_display = f"{metrics['paybackPeriod']:.0f} meses" if metrics.get(
        'paybackPeriod') is not None else "N/A (No se recupera)"
    total_revenues = metrics.get('totalRevenue', 0)
    total_expenses = metrics.get('totalExpense', 0)

    # Nuevo cálculo para la Utilidad Bruta
    gross_margin_percentage = (total_revenues - total_expenses) / total_revenues if total_revenues != 0 else 0

    # Calcular el CAPEX
    upfront_installation_cost = metrics.get('costoInstalacion', 0) * metrics.get('tipoCambio', 1)
    capex_percentage = upfront_installation_cost / total_revenues if total_revenues != 0 else 0

    # --- MANEJO DE TIR CORREGIDO ---
    tir_value = metrics.get('TIR', 0)  # Obtiene el valor de TIR (puede ser float o 'N/A')

    if isinstance(tir_value, str) and tir_value == 'N/A':
        # Si es 'N/A', lo asigna directamente para la impresión
        tir_display = 'N/A'
    else:
        # Si es un número (como float o string numérico de tu cálculo), lo formatea como porcentaje
        try:
            tir_display = f"{float(tir_value):.2%}"
        except (ValueError, TypeError):
            # En caso de que el valor sea inesperado (ej. 0.0 o un número no convertible), se usa 0.0%
            tir_display = "0.00%"
    # -------------------------------

    # 1. Mostrar Encabezados (si show_headers es True)
    if show_headers:
        print("\n" + "=" * 80)
        print(f"| BIENVENIDO/A: EVALUANDO ARCHIVO: {os.path.basename(metrics.get('file_path', 'N/A'))}")
        print("=" * 80)
        print(f"| CLIENTE: {metrics.get('clientName', 'N/A')} | SEGMENTO: {metrics.get('unidadNegocio', 'N/A')}")
        print(f"| VENDEDOR: {metrics.get('salesman', 'N/A')} | ORDER ID: {metrics.get('orderID', 'N/A')}")
        print("-" * 80)
        print(
            f"| MRC: {metrics.get('MRC', 0):,.2f} | NRC: {metrics.get('NRC', 0):,.2f} | PLAZO: {metrics.get('plazoContrato', 0):.0f} meses | T/C: {metrics.get('tipoCambio', 0):,.3f}")
        print("-" * 80)

    # 2. Mostrar Resumen Financiero con el nuevo orden
    print(f"|   TOTAL INGRESOS: {total_revenues:,.2f}")
    print(f"|   TOTAL EGRESOS: {total_expenses:,.2f}")
    print(f"|   UTILIDAD BRUTA: {gross_margin_percentage:.2%}")
    print(f"|   CAPEX (Costo instalacion): {upfront_installation_cost:,.2f}")
    print(f"|   CAPEX % (Costo instalacion / Ingresos Totales): {capex_percentage:.2%}")
    # --- ¡LÍNEA CRÍTICA CORREGIDA! Usamos la variable preparada tir_display ---
    print(f"|   TIR (Internal Rate of Return): {tir_display}")
    print(f"|   VAN (Net Present Value): {metrics.get('VAN', 0):,.2f}")
    print(f"|   Recupero de Inversion (Payback): {payback_display}")
    print("=" * 80)

# -----------------------------------------------------------------------------

# --- NUEVAS FUNCIONES PARA EL FLUJO GIGALAN ---

def get_gigalan_inputs(metrics):
    """
    Prompts the user for GIGALAN-specific information and validates the input.
    """
    # 1. Get GIGALAN Region
    while True:
        print("\n--- Categorización GIGALAN ---")
        print("Regiones válidas: 'LIMA', 'PROVINCIAS CON CACHING', 'PROVINCIAS CON INTERNEXA', 'PROVINCIAS CON TDP'")
        region_input = input("Ingrese la región exacta del proyecto: ").strip().upper()

        valid_regions = {
            'LIMA', 'PROVINCIAS CON CACHING',
            'PROVINCIAS CON INTERNEXA', 'PROVINCIAS CON TDP'
        }
        if region_input in valid_regions:
            region = region_input
            break
        else:
            print("Entrada inválida. Por favor, ingrese una de las regiones válidas.")

    # 2. Get Project Type
    while True:
        project_type_input = input("¿Es una venta nueva o un upgrade? (N/U): ").strip().upper()
        if project_type_input == 'N':
            project_type = 'VENTA NUEVA'
            old_mrc = 0.0
            break
        elif project_type_input == 'U':
            project_type = 'UPGRADE'
            while True:
                try:
                    old_mrc = float(input("Ingrese el valor del MRC antiguo: "))
                    break
                except ValueError:
                    print("Entrada inválida. Por favor, ingrese un número.")
            break
        else:
            print("Entrada inválida. Por favor, ingrese 'N' para Venta Nueva o 'U' para Upgrade.")

    return region, project_type, old_mrc


def calculate_gigalan_commission(base_metrics, region, project_type, old_mrc):
    """
    Calculates the GIGALAN commission based on the defined rules.
    """
    payback = base_metrics['paybackPeriod']
    rentabilidad = (base_metrics['totalRevenue'] - base_metrics['totalExpense']) / base_metrics['totalRevenue']

    # Check Payback
    if payback is None or payback > 2:
        print("\nADVERTENCIA: Payback > 2 meses. No aplica comisión.")
        return 0.0

    commission_rate = 0.0
    plazo = base_metrics['plazoContrato']
    mrc = base_metrics['MRC']

    # Determine commission rate based on region and rentabilidad
    if region == 'LIMA':
        if project_type == 'VENTA NUEVA':
            if 0.40 <= rentabilidad < 0.50:
                commission_rate = 0.009
            elif 0.50 <= rentabilidad < 0.60:
                commission_rate = 0.014
            elif 0.60 <= rentabilidad < 0.70:
                commission_rate = 0.019
            elif rentabilidad >= 0.70:
                commission_rate = 0.024
        elif project_type == 'UPGRADE':
            if 0.40 <= rentabilidad < 0.50:
                commission_rate = 0.01
            elif 0.50 <= rentabilidad < 0.60:
                commission_rate = 0.015
            elif 0.60 <= rentabilidad < 0.70:
                commission_rate = 0.02
            elif rentabilidad >= 0.70:
                commission_rate = 0.025

    elif region == 'PROVINCIAS CON CACHING':
        if 0.40 <= rentabilidad < 0.45:
            commission_rate = 0.03
        elif rentabilidad >= 0.45:
            commission_rate = 0.035

    elif region == 'PROVINCIAS CON INTERNEXA':
        if 0.17 <= rentabilidad < 0.20:
            commission_rate = 0.02
        elif rentabilidad >= 0.20:
            commission_rate = 0.03

    elif region == 'PROVINCIAS CON TDP':
        if 0.17 <= rentabilidad < 0.20:
            commission_rate = 0.02
        elif rentabilidad >= 0.20:
            commission_rate = 0.03

    # Calculate final commission based on project type
    if project_type == 'VENTA NUEVA':
        calculated_commission = commission_rate * mrc * plazo
    elif project_type == 'UPGRADE':
        # La formula es: % * plazo * (MRC Nuevo - MRC Antiguo)
        calculated_commission = commission_rate * plazo * (mrc - old_mrc)

    return calculated_commission

# --- FUNCIONES PARA NUEVAS TABLAS ---
def extract_and_calculate_fixed_costs(plantilla_sheet, transaction_id):
    fixed_details_list = []
    total_costoInstalacion = 0.0

    start_row = config.DETAIL_START_ROW
    end_row = plantilla_sheet.max_row + 1

    for row in range(start_row, end_row):

        # Extract values using the config columns
        categoria = plantilla_sheet[f'{config.FIXED_CATEGORY_COL}{row}'].value
        tipo_servicio = plantilla_sheet[f'{config.FIXED_TIPO_SERVICIO_COL}{row}'].value
        ticket = plantilla_sheet[f'{config.FIXED_TICKET_COL}{row}'].value
        # Ubicacion is text, no safety check needed

        # --- APPLY SAFE NUMERIC EXTRACTION HERE ---
        cantidad = get_numeric_value(plantilla_sheet[f'{config.FIXED_Q_COL}{row}'].value)
        costoUnitario = get_numeric_value(plantilla_sheet[f'{config.FIXED_COST_UNITARIO_COL}{row}'].value)
        total = get_numeric_value(plantilla_sheet[f'{config.FIXED_COST_TOTAL_COL}{row}'].value)

        # If the category is None, we assume the row is empty and stop
        if categoria is None and total == 0.0:
            break

        # Accumulate total cost (Now safe from NoneType errors)
        total_costoInstalacion += total

        # Append details list (ensuring fields match database structure)
        fixed_details_list.append({
            'transactionID': transaction_id,
            'categoria': categoria,
            'tipo_servicio': tipo_servicio,
            'ticket': ticket,
            'ubicacion': plantilla_sheet[f'{config.FIXED_UBICACION_COL}{row}'].value,
            'cantidad': cantidad,
            'costoUnitario': costoUnitario,
            'total': total
        })

    return fixed_details_list, total_costoInstalacion


def extract_and_calculate_recurring_services(plantilla_sheet, transaction_id):
    """
    Extrae los detalles de la tabla de servicios recurrentes, calcula el ingreso y el egreso
    mensual por línea, acumula el total de egresos mensuales y devuelve la lista de detalles
    y el total de egresos.

    NOTA: El MRC total para el resumen financiero se toma del encabezado del Excel (H9),
    no de la suma de esta función.
    """
    recurring_details_list = []
    total_monthly_expense = 0.0  # Acumulador de Costos Mensuales (Egreso Total)

    start_row = config.DETAIL_START_ROW
    end_row = plantilla_sheet.max_row + 1

    for row in range(start_row, end_row):

        # Extracción de campos de texto
        tipo_servicio = plantilla_sheet[f'{config.RECURRING_SERVICE_COL}{row}'].value

        # --- EXTRACCIÓN SEGURA DE VALORES NUMÉRICOS (INPUTS PARA CÁLCULO) ---
        # Q (Cantidad), P (Precio Unitario), CU1, CU2
        cantidad_Q = get_numeric_value(plantilla_sheet[f'{config.RECURRING_Q_COL}{row}'].value)
        precio_unitario_P = get_numeric_value(plantilla_sheet[f'{config.RECURRING_REVENUE_UNIT_COL}{row}'].value)
        costo_unitario_1 = get_numeric_value(plantilla_sheet[f'{config.RECURRING_COST_1_COL}{row}'].value)
        costo_unitario_2 = get_numeric_value(plantilla_sheet[f'{config.RECURRING_COST_2_COL}{row}'].value)

        # Check de fila vacía. Si no hay servicio y las cantidades/precios son cero, se detiene.
        if tipo_servicio is None and cantidad_Q == 0.0 and precio_unitario_P == 0.0:
            break

        # ----------------------------------------------------------------------
        # CÁLCULOS CRÍTICOS POR LÍNEA
        # ----------------------------------------------------------------------

        # 1. INGRESOS MENSUALES (Para guardar en DB): Q * P
        ingreso_calculado = cantidad_Q * precio_unitario_P

        # 2. COSTOS MENSUALES / EGRESOS (Para guardar en DB y para el acumulador): (CU1 + CU2) * Q
        egreso_calculado = (costo_unitario_1 + costo_unitario_2) * cantidad_Q

        # ----------------------------------------------------------------------

        # 1. Acumulación del TOTAL EGRESOS MENSUALES
        total_monthly_expense += egreso_calculado

        # 2. Append details list
        recurring_details_list.append({
            'transactionID': transaction_id,
            'tipo_servicio': tipo_servicio,
            # Se asume que las variables de texto (M, N, T) están definidas en config.py
            'nota': plantilla_sheet[f'{config.RECURRING_NOTA_COL}{row}'].value,
            'ubicacion': plantilla_sheet[f'{config.RECURRING_UBICACION_COL}{row}'].value,

            # Campos numéricos
            'Q': cantidad_Q,
            'P': precio_unitario_P,
            'ingreso': ingreso_calculado,  # Valor calculado para la DB
            'CU1': costo_unitario_1,
            'CU2': costo_unitario_2,

            # Campo de texto
            'proveedor': plantilla_sheet[f'{config.RECURRING_PROVEEDOR_COL}{row}'].value,

            'egreso': egreso_calculado  # Valor calculado para la DB y para el total
        })

    # Se devuelven los detalles y el total de egresos
    return recurring_details_list, total_monthly_expense

def get_numeric_value(cell_value):
    """
    Safely converts an Excel cell value to a float, treating None/empty values as 0.0.
    """
    if cell_value is None or cell_value == "":
        return 0.0
    try:
        # Handle cases where the value might be a string that needs conversion
        return float(cell_value)
    except ValueError:
        # Fallback if conversion fails (e.g., text in a numeric column)
        return 0.0


def display_recurring_details(details_list):
    """
    Imprime un resumen de los detalles clave del servicio recurrente
    (tipo_servicio, nota, ubicacion, Q, P) para dar contexto a la revisión manual.
    """
    print("\n" + "=" * 80)
    print("| DETALLES DE SERVICIOS RECURRENTES |")
    print("=" * 80)

    # Define the formats for the header and the data rows
    header_format = "| {:<30} | {:<20} | {:<20} | {:>5} | {:>10} |"
    # Q is formatted as integer (:>5.0f), P (Ingreso Unitario) as currency (:>10,.2f)
    row_format = "| {:<30} | {:<20} | {:<20} | {:>5.0f} | {:>10,.2f} |"

    print(header_format.format("TIPO DE SERVICIO", "NOTA", "UBICACION", "Q", "P (Ingreso Unit.)"))
    print("-" * 80)

    if not details_list:
        print("| NO HAY SERVICIOS RECURRENTES REGISTRADOS EN LA PLANTILLA. |")
        print("=" * 80)
        return

    for item in details_list:
        # Check if the row has any quantity or service type to avoid printing empty rows
        if item.get('Q', 0) > 0 or item.get('tipo_servicio'):
            # Extract and safely limit string length for clean display
            # The 'or '' ' handles NoneType values gracefully
            tipo_servicio = str(item.get('tipo_servicio', '') or '')[:30]
            nota = str(item.get('nota', '') or '')[:20]
            ubicacion = str(item.get('ubicacion', '') or '')[:20]
            cantidad = item.get('Q', 0.0)
            precio_unitario = item.get('P', 0.0)

            print(row_format.format(
                tipo_servicio,
                nota,
                ubicacion,
                cantidad,
                precio_unitario
            ))

    print("=" * 80)