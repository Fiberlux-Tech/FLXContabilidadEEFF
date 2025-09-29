import os
import pandas as pd
from datetime import datetime
import config
import utils

if __name__ == "__main__":

    # -------------------------------------------------------------------------
    # INICIALIZACIÓN: Obtener datos de validación
    # -------------------------------------------------------------------------

    print("Iniciando Proceso. Conectando a la Base de Datos para obtener validaciones...")

    try:
        # Obtener las listas de validación de la base de datos una sola vez
        valid_servicios = utils.get_validation_list(
            config.DATABASE_PATH, "listaServicios", "servicios"
        )
        valid_cotizaciones = utils.get_validation_list(
            config.DATABASE_PATH, "listaCotizaciones", "equipos"
        )
    except Exception as e:
        print(
            f"ERROR CRÍTICO: No se pudo conectar a la base de datos o leer las listas de validación. Asegúrese de que la ruta y el driver sean correctos. Error: {e}")
        exit()  # Detiene la ejecución si no se pueden obtener las listas

    # Inicialización de contadores
    processed_count = 0
    automatic_rejections = 0
    manual_rejections = 0
    approved_count = 0

    # -------------------------------------------------------------------------
    # BUCLE PRINCIPAL: Procesar archivos
    # -------------------------------------------------------------------------

    # Bucle a través de todos los archivos en la carpeta especificada
    for file_name in os.listdir(config.EXCEL_FOLDER_PATH):

        # Solo procesar archivos Excel que no sean temporales
        if file_name.endswith(".xlsx") and not file_name.startswith("~"):
            excel_file_path = os.path.join(config.EXCEL_FOLDER_PATH, file_name)
            current_timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            print(f"\n======================================================\nInspeccionando archivo: {file_name}")

            # 1. GENERAR UN ID ÚNICO DE TRANSACCIÓN
            # Este ID es la clave que enlaza los registros en las tres tablas de la BD.
            transaction_id = datetime.now().strftime("%Y%m%d%H%M%S")

            try:
                # 2. VALIDACIÓN AUTOMÁTICA Y EXTRACCIÓN DE DATOS CON OPENPYXL
                # (Includes the new validation for Column C categories)
                file_is_clean, wb = utils.validate_excel_data(
                    excel_file_path, valid_servicios, valid_cotizaciones, config.RED_FILL
                )

                # Obtener la única hoja necesaria
                plantilla_sheet = wb[config.PLANTILLA_SHEET_NAME]

                # 3. EXTRACCIÓN DE VARIABLES Y VERIFICACIÓN INICIAL
                extracted_variables = {}
                for var_name, cell_address in config.variables_to_extract.items():
                    value = plantilla_sheet[cell_address].value
                    # Almacena los valores. Los valores None se manejan como 0 en el cálculo.
                    extracted_variables[var_name] = value if value is not None else 0

                # Variables clave extraídas para el email
                salesman = extracted_variables.get('salesman', 'Unknown')
                client_name = extracted_variables.get('clientName', 'N/A')

                # Asegurar que salesman y client_name no sean None para el email
                salesman = 'Unknown' if salesman is None or salesman == 0 else salesman
                client_name = 'N/A' if client_name is None or client_name == 0 else client_name

                # Get the recipient email
                recipient_email = utils.get_salesman_email(config.DATABASE_PATH, salesman)

                if not file_is_clean:
                    print(f"Errores de validacion en '{file_name}'. Enviando email de rechazo.")
                    # Guarda el archivo con las celdas marcadas en rojo
                    wb.save(excel_file_path)

                    # Correo de RECHAZO por validación automática
                    subject = f"PLANTILLA {client_name} RECHAZADA - REVISION AUTOMATICA"
                    body = f"""
                        <p>Hola {salesman},</p>
                        <p>La verificación automática <b>falló</b>. Revise las celdas marcadas en <b>rojo</b> en el archivo adjunto.</p>
                        <p>Por favor, corrija las celdas y vuelva a enviarlo.</p>
                    """
                    utils.send_outlook_email(recipient_email, subject, body, attachment_path=excel_file_path)

                    automatic_rejections += 1
                    processed_count += 1
                    continue  # Pasa al siguiente archivo

                # Si el archivo está limpio, se procede a extraer datos de las tablas y calcular costos
                print(f"Archivo '{file_name}' esta limpio. Extrayendo data de tablas y calculando costos.")

                # -------------------------------------------------------------------------
                # 4. PROCESAMIENTO DE TABLAS DE DETALLE Y CÁLCULOS
                # -------------------------------------------------------------------------

                # A. CALCULO DE COSTOS FIJOS (INSTALACIÓN)
                # Retorna la lista de detalles y el costo total de instalación
                fixed_details_list, calculated_costoInstalacion = utils.extract_and_calculate_fixed_costs(
                    plantilla_sheet, transaction_id
                )

                # B. CALCULO DE COSTOS RECURRENTES
                # Retorna la lista de detalles y el costo mensual total
                recurring_details_list, total_monthly_expense_calculated = utils.extract_and_calculate_recurring_services(
                    plantilla_sheet, transaction_id
                )

                # C. Obtener la suma de INGRESOS de la tabla recurrente (para grabación/validación)
                # Este valor es grabado, pero NO se usa para el cálculo VAN/TIR (que usa el MRC oficial de H9)
                total_monthly_revenue_line_item_sum = sum(
                    d.get('ingreso', 0) for d in recurring_details_list
                )

                # -------------------------------------------------------------------------
                # 5. PREPARACIÓN DE VARIABLES BASE PARA CÁLCULO FINANCIERO
                # -------------------------------------------------------------------------

                # Crear un diccionario para pasar todas las variables como argumentos
                base_variables = {
                    # Valores oficiales extraídos del encabezado (incluyen el MRC oficial)
                    'costoCapital_annual': extracted_variables['costoCapital_annual'],
                    'MRC': extracted_variables['MRC'],  # <--- OFICIAL MRC (H9)
                    'NRC': extracted_variables['NRC'],
                    'plazoContrato': extracted_variables['plazoContrato'],
                    'comisionesPersonal': extracted_variables['comisionesPersonal'],
                    'tipoCambio': extracted_variables['tipoCambio'],

                    # Totales CALCULADOS a partir de las tablas de detalle
                    'costoInstalacion': calculated_costoInstalacion,
                    'total_monthly_expense': total_monthly_expense_calculated,
                    'total_monthly_revenue_line_item_sum': total_monthly_revenue_line_item_sum,
                    # Para grabar en el header

                    # Variables de identificación
                    'clientName': client_name,
                    'companyID': extracted_variables['companyID'],
                    'salesman': salesman,
                    'orderID': extracted_variables['orderID'],
                    'unidadNegocio': extracted_variables['unidadNegocio'],
                    'submission_timestamp': current_timestamp
                }

                unidad_negocio = str(extracted_variables['unidadNegocio']).upper()

                # -------------------------------------------------------------------------
                # 6. FLUJO CONDICIONAL Y CÁLCULO FINAL
                # -------------------------------------------------------------------------

                if unidad_negocio == "ESTADO":
                    # PRIMER CÁLCULO: con comisionesPersonal = 0 (Base para Rentabilidad)
                    base_variables_for_calc = base_variables.copy()
                    base_variables_for_calc['comisionesPersonal'] = 0.0  # Establecer a cero para el cálculo base

                    initial_metrics = utils.calculate_financial_metrics(**base_variables_for_calc)

                    # Se añade la info auxiliar necesaria para el flujo de ESTADO
                    initial_metrics.update({
                        'file_path': excel_file_path,
                        'costoInstalacion': calculated_costoInstalacion,
                        'tipoCambio': extracted_variables['tipoCambio']
                    })

                    # LLAMAR AL FLUJO CONDICIONAL Y RECALCULADOR DE COMISIÓN
                    metrics = utils.calculate_state_commission(
                        first_metrics=initial_metrics,
                        calculator_function=utils.calculate_financial_metrics,
                        variables_to_pass=base_variables  # Pasamos las variables base originales para el recálculo
                    )

                    # INTERFAZ MANUAL Y DECISIÓN (Para flujo ESTADO)
                    is_approved = utils.get_manual_approval(metrics, is_estado_flow=True)

                elif unidad_negocio == "GIGALAN":
                    print("\n" + "#" * 80)
                    print(f"| GIGALAN FLOW: Calculando metrics sin comision para evaluar.")
                    print("#" * 80)

                    # 1. Primer cálculo: con comisionesPersonal = 0 (Base para Rentabilidad)
                    base_variables_for_calc = base_variables.copy()
                    base_variables_for_calc['comisionesPersonal'] = 0.0  # Establecer a cero para el cálculo base
                    initial_metrics = utils.calculate_financial_metrics(**base_variables_for_calc)

                    # Display initial metrics
                    utils.display_financial_summary(initial_metrics, show_headers=True)
                    # Call the new function to display the recurring service details
                    utils.display_recurring_details(recurring_details_list)
                    # 2. Get GIGALAN specific inputs from user
                    region_giga, project_type, old_mrc = utils.get_gigalan_inputs(initial_metrics)

                    # 3. Calculate GIGALAN commission
                    calculated_commission = utils.calculate_gigalan_commission(initial_metrics, region_giga,
                                                                               project_type, old_mrc)

                    print(f"Comisión GIGALAN calculada: {calculated_commission:,.2f}")

                    # 4. Final recalculation with calculated commission
                    base_variables['comisionesPersonal'] = calculated_commission
                    metrics = utils.calculate_financial_metrics(**base_variables)

                    # Se añade la info auxiliar necesaria para el prompt/archivo
                    metrics.update({
                        'file_path': excel_file_path,
                        'comisionesPersonal': calculated_commission,
                        'costoInstalacion': calculated_costoInstalacion,
                        'tipoCambio': extracted_variables['tipoCambio']
                    })

                    # 5. Manual approval with final metrics
                    is_approved = utils.get_manual_approval(metrics)

                elif unidad_negocio == "CORPORATIVO":

                    # CÁLCULO ÚNICO: con la comisión original extraída de la plantilla
                    metrics = utils.calculate_financial_metrics(**base_variables)

                    # Se añade la info auxiliar necesaria para el prompt/archivo
                    metrics.update({
                        'file_path': excel_file_path,
                        'comisionesPersonal': extracted_variables['comisionesPersonal'],
                        'costoInstalacion': calculated_costoInstalacion,
                        'tipoCambio': extracted_variables['tipoCambio']
                    })

                    # INTERFAZ MANUAL Y DECISIÓN (Para otros flujos)
                    is_approved = utils.get_manual_approval(metrics)

                else:
                    # Manejar cualquier otra unidad de negocio no definida
                    print(f"ADVERTENCIA: Unidad de Negocio '{unidad_negocio}' no reconocida. Se omite el archivo.")
                    continue

                if is_approved:
                    print("APROBACION MANUAL: YES. Procediendo a archivar y agregar a la BD.")

                    # -------------------------------------------------------------------------
                    # 7. ACCIÓN: APROBADO - CREACIÓN DE DATAFRAMES E INSERCIÓN
                    # -------------------------------------------------------------------------

                    # 1. Añadir el transactionID al diccionario de metrics
                    metrics['transactionID'] = transaction_id

                    # 2. Crear DF para Header (solo una fila)
                    header_df = utils.create_results_dataframe([metrics])

                    # 3. Crear DF para Tablas de Detalle
                    # Nota: fixed_details_list y recurring_details_list ya tienen 'transactionID'
                    fixed_costs_df = pd.DataFrame(fixed_details_list)
                    recurring_df = pd.DataFrame(recurring_details_list)

                    # 4. Guardar en las 3 nuevas tablas de la BD (REQUIERE EL NUEVO UTILS.PY)
                    utils.append_to_access_database_minimized(
                        header_df, fixed_costs_df, recurring_df, config.DATABASE_PATH
                    )

                    # 5. Archivar archivo
                    wb.close()
                    utils.move_file_to_historico(
                        file_path=excel_file_path,
                        base_dest_path=config.HISTORICO_FOLDER_PATH,
                        unidad_negocio_value=metrics['unidadNegocio'],
                        client_name=metrics['clientName'],
                        submission_timestamp=current_timestamp
                    )

                    # 6. Enviar Correo de ÉXITO (NO attachment)
                    subject = f"PLANTILLA {client_name} - APROBADA"
                    body = f"""
                        <p>Hola {salesman},</p>
                        <p>La plantilla para el cliente {metrics['clientName']} fue verificada y <b>APROBADA</b> por Finanzas.</p>
                        <p><em>Los datos han sido registrados en la base de datos con ID: {transaction_id}</em></p>
                    """
                    utils.send_outlook_email(recipient_email, subject, body)
                    approved_count += 1
                    processed_count += 1

                else:
                    print("Aprobacion manual: NO. Enviando email de rechazo.")

                    # PROMPT: Obtener el motivo del rechazo manual
                    rejection_reason = input(
                        "Ingrese el motivo del RECHAZO MANUAL (Este texto se incluirá en el email): "
                    ).strip()

                    # -------------------------------------------------------------------------
                    # 8. ACCIÓN: RECHAZADO MANUAL
                    # -------------------------------------------------------------------------
                    wb.close()
                    # Enviar Correo de RECHAZO MANUAL (adjuntando archivo para su corrección)
                    subject = f"PLANTILLA {client_name} - RECHAZADA: REVISIÓN MANUAL"
                    body = f"""
                        <p>Hola {salesman},</p>
                        <p>La plantilla para el cliente {metrics['clientName']} fue <b>RECHAZADA</b> después de la revisión final.</p>
                        <p><b>MOTIVO:</b> <em>{rejection_reason}</em></p>
                        <p>Por favor, comuníquese con el equipo de Finanzas para detalles sobre la corrección o justificación necesaria.</p>
                    """
                    utils.send_outlook_email(recipient_email, subject, body, attachment_path=excel_file_path)
                    manual_rejections += 1
                    processed_count += 1

            except Exception as e:
                print(f"Ocurrió un error inesperado al procesar '{file_name}'. Omitiendo. Error: {e}")
                processed_count += 1  # Count this file as processed
                # En este punto, si el error es grave, el archivo queda pendiente en la carpeta

    print("\n" + "=" * 60)
    print(f"--- Proceso completado. Resumen de Archivos ---")
    print("=" * 60)
    print(f"Archivos procesados: {processed_count}")
    print(f"  - Aprobados: {approved_count}")
    print(f"  - Rechazo automático: {automatic_rejections}")
    print(f"  - Rechazo manual: {manual_rejections}")
    print("=" * 60)