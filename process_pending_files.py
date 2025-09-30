import os
import pandas as pd
from datetime import datetime
import re  # Import the regular expressions library
import config
import utils

if __name__ == "__main__":

    print("Iniciando Proceso de Carga. Conectando a la Base de Datos...")

    try:
        valid_servicios = utils.get_validation_list(
            config.DATABASE_PATH, "listaServicios", "servicios"
        )
        valid_cotizaciones = utils.get_validation_list(
            config.DATABASE_PATH, "listaCotizaciones", "equipos"
        )
    except Exception as e:
        print(
            f"ERROR CRÍTICO: No se pudo conectar a la base de datos. Error: {e}")
        exit()

    processed_count = 0
    error_count = 0

    for file_name in os.listdir(config.EXCEL_FOLDER_PATH):
        if file_name.endswith(".xlsx") and not file_name.startswith("~"):
            excel_file_path = os.path.join(config.EXCEL_FOLDER_PATH, file_name)
            print(f"\n======================================================\nInspeccionando archivo: {file_name}")

            try:
                # Timestamps are captured early
                file_mod_time = os.path.getmtime(excel_file_path)
                date_file_submitted = datetime.fromtimestamp(file_mod_time).strftime('%Y-%m-%d %H:%M:%S')
                date_processed = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

                file_is_clean, wb = utils.validate_excel_data(
                    excel_file_path, valid_servicios, valid_cotizaciones, config.RED_FILL
                )

                if not file_is_clean:
                    print(f"Errores de validacion en '{file_name}'. El archivo no será procesado.")
                    wb.save(excel_file_path)
                    error_count += 1
                    continue

                plantilla_sheet = wb[config.PLANTILLA_SHEET_NAME]

                extracted_variables = {}
                for var_name, cell_address in config.variables_to_extract.items():
                    value = plantilla_sheet[cell_address].value
                    extracted_variables[var_name] = value if value is not None else 0

                # ## KEY CHANGE HERE: Generate the new custom transactionID ##
                unidad_negocio_str = str(extracted_variables.get('unidadNegocio', 'XXXX')).strip().upper()
                client_name_str = str(extracted_variables.get('clientName', '')).strip()

                # Sanitize client name to remove spaces and special characters
                clean_client_name = re.sub(r'[^A-Z0-9]', '', client_name_str.upper())

                # Get the timestamp part
                timestamp_str = datetime.now().strftime("%Y%m%d%H%M%S")

                # Combine the parts to create the new ID
                transaction_id = f"{unidad_negocio_str[:4]}_{clean_client_name}_{timestamp_str}"
                print(f"Generated Transaction ID: {transaction_id}")
                # ## END OF CHANGE ##

                client_name = extracted_variables.get('clientName', 'N/A')
                client_name = 'N/A' if client_name is None or client_name == 0 else client_name

                fixed_details_list, calculated_costoInstalacion = utils.extract_and_calculate_fixed_costs(
                    plantilla_sheet, transaction_id
                )
                recurring_details_list, total_monthly_expense_calculated = utils.extract_and_calculate_recurring_services(
                    plantilla_sheet, transaction_id
                )
                total_monthly_revenue_line_item_sum = sum(
                    d.get('ingreso', 0) for d in recurring_details_list
                )

                base_variables = {
                    'costoCapital_annual': extracted_variables['costoCapital_annual'],
                    'MRC': extracted_variables['MRC'], 'NRC': extracted_variables['NRC'],
                    'plazoContrato': extracted_variables['plazoContrato'],
                    'comisionesPersonal': extracted_variables['comisionesPersonal'],
                    'tipoCambio': extracted_variables['tipoCambio'],
                    'costoInstalacion': calculated_costoInstalacion,
                    'total_monthly_expense': total_monthly_expense_calculated,
                    'total_monthly_revenue_line_item_sum': total_monthly_revenue_line_item_sum,
                    'clientName': client_name, 'companyID': extracted_variables['companyID'],
                    'salesman': extracted_variables.get('salesman', 'Unknown'),
                    'orderID': extracted_variables['orderID'], 'unidadNegocio': extracted_variables['unidadNegocio'],
                    'transactionID': transaction_id, 'file_path': excel_file_path,
                    'DateFileSubmitted': date_file_submitted, 'DateProcessed': date_processed,
                }

                unidad_negocio = str(extracted_variables['unidadNegocio']).upper()
                final_metrics_to_save = {}

                if unidad_negocio == "ESTADO":
                    print("Procesando flujo ESTADO...")
                    tipo_pago_value = str(extracted_variables.get('tipoPago', '')).strip().upper()
                    is_pago_unico = (tipo_pago_value == 'PAGO UNICO')
                    print(f"Tipo de pago detectado: {'PAGO UNICO' if is_pago_unico else 'RECURRENTE'}")
                    base_variables_for_calc = base_variables.copy()
                    base_variables_for_calc['comisionesPersonal'] = 0.0
                    initial_metrics = utils.calculate_financial_metrics(**base_variables_for_calc)
                    final_metrics = utils.calculate_state_commission_automated(initial_metrics, base_variables,
                                                                               is_pago_unico)
                    final_metrics_to_save = {
                        **base_variables,
                        'totalRevenue': final_metrics.get('totalRevenue'),
                        'totalExpense': final_metrics.get('totalExpense'),
                        'grossMargin': final_metrics.get('grossMargin'),
                        'VAN_pre_commission': initial_metrics.get('VAN'),
                        'TIR_pre_commission': initial_metrics.get('TIR'),
                        'Payback_pre_commission': initial_metrics.get('paybackPeriod'),
                        'comisionesPersonal': final_metrics.get('comisionesPersonal'),
                        'CommissionRate': final_metrics.get('commission_rate'),
                        'VAN_final': final_metrics.get('VAN'),
                        'TIR_final': final_metrics.get('TIR'),
                        'Payback_final': final_metrics.get('paybackPeriod'),
                        'ApprovalStatus': 'PENDING'
                    }

                elif unidad_negocio == "GIGALAN":
                    print("Procesando flujo GIGALAN (solo pre-cálculo)...")
                    base_variables_for_calc = base_variables.copy()
                    base_variables_for_calc['comisionesPersonal'] = 0.0
                    initial_metrics = utils.calculate_financial_metrics(**base_variables_for_calc)
                    final_metrics_to_save = {
                        **base_variables,
                        'totalRevenue': initial_metrics.get('totalRevenue'),
                        'totalExpense': initial_metrics.get('totalExpense'),
                        'grossMargin': initial_metrics.get('grossMargin'),
                        'VAN_pre_commission': initial_metrics.get('VAN'),
                        'TIR_pre_commission': initial_metrics.get('TIR'),
                        'Payback_pre_commission': initial_metrics.get('paybackPeriod'),
                        'ApprovalStatus': 'PENDING_GIGA_INPUT'
                    }

                elif unidad_negocio == "CORPORATIVO":
                    print("Procesando flujo CORPORATIVO...")
                    metrics = utils.calculate_financial_metrics(**base_variables)
                    # ## KEY FIX HERE: Include ALL calculated metrics in the save dictionary ##
                    final_metrics_to_save = {
                        **base_variables,
                        'totalRevenue': metrics.get('totalRevenue'),
                        'totalExpense': metrics.get('totalExpense'),
                        'grossMargin': metrics.get('grossMargin'),
                        'comisionesPersonal': extracted_variables['comisionesPersonal'],
                        'VAN_final': metrics.get('VAN'),
                        'TIR_final': metrics.get('TIR'),
                        'Payback_final': metrics.get('paybackPeriod'),
                        'ApprovalStatus': 'PENDING'
                    }
                else:
                    print(f"ADVERTENCIA: Unidad de Negocio '{unidad_negocio}' no reconocida. Se omite el archivo.")
                    error_count += 1
                    continue

                header_df = utils.create_results_dataframe([final_metrics_to_save])
                fixed_costs_df = pd.DataFrame(fixed_details_list)
                recurring_df = pd.DataFrame(recurring_details_list)

                utils.append_to_access_database_minimized(
                    header_df, fixed_costs_df, recurring_df, config.DATABASE_PATH
                )
                print(
                    f"Archivo '{file_name}' procesado y guardado en la BD con estado '{final_metrics_to_save['ApprovalStatus']}'.")
                processed_count += 1

            except Exception as e:
                print(f"Ocurrió un error inesperado al procesar '{file_name}'. Omitiendo. Error: {e}")
                error_count += 1
                continue

    print("\n" + "=" * 60)
    print(f"--- Proceso de carga completado ---")
    print("=" * 60)
    print(f"Archivos procesados y cargados exitosamente: {processed_count}")
    print(f"Archivos con errores o no reconocidos: {error_count}")
    print("=" * 60)