import os
import pyodbc
from datetime import datetime
import pandas as pd
import config
import utils


def get_db_connection():
    """Establishes and returns a connection to the Access database."""
    conn_str = (r'DRIVER={Microsoft Access Driver (*.mdb, *.accdb)};DBQ=' + config.DATABASE_PATH + r';')
    try:
        return pyodbc.connect(conn_str)
    except pyodbc.Error as e:
        print(f"Error connecting to database: {e}")
        return None


def get_pending_transactions(conn):
    """Fetches all transactions that need action from the database."""
    sql = "SELECT * FROM transactionTable WHERE ApprovalStatus = 'PENDING' OR ApprovalStatus = 'PENDING_GIGA_INPUT'"
    try:
        pending_df = pd.read_sql(sql, conn)
        return pending_df
    except Exception as e:
        print(f"Error fetching pending transactions: {e}")
        return pd.DataFrame()


def update_db_record(conn, transaction_id, update_data):
    """Updates a specific record in the transactionTable."""
    cursor = conn.cursor()
    set_clause = ", ".join([f"[{key}] = ?" for key in update_data.keys()])
    sql = f"UPDATE transactionTable SET {set_clause} WHERE transactionID = ?"

    params = list(update_data.values())
    params.append(transaction_id)

    try:
        cursor.execute(sql, params)
        conn.commit()
    except pyodbc.Error as e:
        print(f"Database update failed for transaction {transaction_id}: {e}")
        conn.rollback()


if __name__ == "__main__":
    conn = get_db_connection()
    if not conn:
        exit()

    while True:
        pending_transactions = get_pending_transactions(conn)

        if pending_transactions.empty:
            print("No pending transactions found. Exiting.")
            break

        print("\n--- TRANSACTIONS PENDING ACTION ---")
        for index, row in pending_transactions.iterrows():
            # We use os.path.basename to show just the filename, not the whole path
            file_name = os.path.basename(row['file_path'])
            print(
                f"  {index + 1}: [Order ID: {row['orderID']}] Client: {row['clientName']} | File: {file_name} (Status: {row['ApprovalStatus']})")

        print("\nEnter 'q' to quit.")

        try:
            choice = input("Enter the number of the transaction to action: ").strip()
            if choice.lower() == 'q':
                break

            choice_index = int(choice) - 1
            if not 0 <= choice_index < len(pending_transactions):
                print("Invalid number. Please try again.")
                continue

            selected_row = pending_transactions.iloc[choice_index]
            transaction_id = selected_row['transactionID']

            print(f"\n--- ACTIONING TRANSACTION FOR: {selected_row['clientName']} ---")

            # --- GIGALAN SPECIAL FLOW ---
            if selected_row['ApprovalStatus'] == 'PENDING_GIGA_INPUT':
                print("GIGALAN flow detected. Additional input is required.")

                # Create the pre-commission metrics dict from the selected row
                pre_commission_metrics = {
                    'totalRevenue': selected_row['totalRevenue'],
                    'grossMargin': selected_row['grossMargin'],
                    'paybackPeriod': selected_row['Payback_pre_commission'],
                    'plazoContrato': selected_row['plazoContrato'],
                    'MRC': selected_row['MRC']
                }

                region, project_type, old_mrc = utils.get_gigalan_inputs()

                calculated_commission, commission_rate = utils.calculate_gigalan_commission(
                    pre_commission_metrics, region, project_type, old_mrc
                )
                print(f"Calculated GIGALAN Commission: {calculated_commission:,.2f} at {commission_rate:.2%}")

                # Recalculate financial metrics with the new commission
                final_calc_vars = selected_row.to_dict()
                final_calc_vars['comisionesPersonal'] = calculated_commission
                final_metrics = utils.calculate_financial_metrics(**final_calc_vars)

                # Prepare data for final DB update
                update_data = {
                    'comisionesPersonal': calculated_commission,
                    'CommissionRate': commission_rate,
                    'VAN_final': final_metrics['VAN'],
                    'TIR_final': final_metrics['TIR'],
                    'Payback_final': final_metrics['paybackPeriod'],
                }
                update_db_record(conn, transaction_id, update_data)
                print("Final metrics calculated and saved.")

            # --- APPROVAL/REJECTION FLOW ---
            decision = input(f"Approve this transaction? (Y/N): ").strip().lower()
            date_action_taken = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

            if decision == 'y':
                print("Processing APPROVAL...")

                # ## KEY CHANGE HERE: Convert Timestamp to string before passing ##
                submission_timestamp_str = selected_row['DateFileSubmitted'].strftime('%Y-%m-%d %H:%M:%S')

                new_file_path = utils.move_file_to_historico(
                    file_path=selected_row['file_path'],
                    base_dest_path=config.HISTORICO_FOLDER_PATH,
                    unidad_negocio_value=selected_row['unidadNegocio'],
                    client_name=selected_row['clientName'],
                    submission_timestamp=submission_timestamp_str  # Use the new string version
                )

                # 2. Update the database
                approval_data = {
                    'ApprovalStatus': 'APPROVED',
                    'DateActionTaken': date_action_taken
                }
                if new_file_path:
                    approval_data['file_path'] = new_file_path
                update_db_record(conn, transaction_id, approval_data)

                # 3. Send email
                recipient_email = utils.get_salesman_email(config.DATABASE_PATH, selected_row['salesman'])
                subject = f"PLANTILLA {selected_row['clientName']} - APROBADA"
                body = f"""
                    <p>Hola {selected_row['salesman']},</p>
                    <p>La plantilla para el cliente {selected_row['clientName']} fue verificada y <b>APROBADA</b> por Finanzas.</p>
                    <p><em>Los datos han sido registrados en la base de datos con ID: {transaction_id}</em></p>
                """
                utils.send_outlook_email(recipient_email, subject, body)

            elif decision == 'n':
                print("Processing REJECTION...")
                reason = input("Please provide a reason for rejection: ").strip()

                # 1. Update the database
                rejection_data = {
                    'ApprovalStatus': 'REJECTED',
                    'DateActionTaken': date_action_taken
                }
                update_db_record(conn, transaction_id, rejection_data)

                # 2. Send email with attachment
                recipient_email = utils.get_salesman_email(config.DATABASE_PATH, selected_row['salesman'])
                subject = f"PLANTILLA {selected_row['clientName']} - RECHAZADA: REVISIÓN MANUAL"
                body = f"""
                    <p>Hola {selected_row['salesman']},</p>
                    <p>La plantilla para el cliente {selected_row['clientName']} fue <b>RECHAZADA</b> después de la revisión final.</p>
                    <p><b>MOTIVO:</b> <em>{reason}</em></p>
                    <p>Por favor, revise el archivo adjunto y comuníquese con el equipo de Finanzas para detalles.</p>
                """
                utils.send_outlook_email(recipient_email, subject, body, attachment_path=selected_row['file_path'])

            else:
                print("Invalid input. No action taken.")

        except (ValueError, IndexError):
            print("Invalid input. Please enter a valid number from the list.")
        except Exception as e:
            print(f"An unexpected error occurred: {e}")

    conn.close()
    print("Connection closed.")