import subprocess
import sys


def main_dashboard():
    """
    Displays a menu to the user and runs the selected script.
    """

    # Get the path to the python executable that is running this script
    python_executable = sys.executable

    while True:
        print("\n" + "=" * 40)
        print("    FIBERLUX - FINANCIAL APPROVALS")
        print("=" * 40)
        print("What do you want to do?")
        print("  1. Process new Excel files")
        print("  2. Approve pending transactions")
        print("  3. Exit")
        print("-" * 40)

        choice = input("Enter your choice (1, 2, or 3): ").strip()

        if choice == '1':
            print("\n--- Running the file processor... ---\n")
            try:
                # Runs the process_pending_files.py script
                subprocess.run([python_executable, "process_pending_files.py"], check=True)
            except FileNotFoundError:
                print("\nERROR: 'process_pending_files.py' not found in this directory.")
            except subprocess.CalledProcessError as e:
                print(f"\nAn error occurred while processing files: {e}")

            input("\nPress Enter to return to the menu...")

        elif choice == '2':
            print("\n--- Opening the approval dashboard... ---\n")
            try:
                # Runs the approve_transactions.py script
                subprocess.run([python_executable, "approve_transactions.py"], check=True)
            except FileNotFoundError:
                print("\nERROR: 'approve_transactions.py' not found in this directory.")
            except subprocess.CalledProcessError as e:
                print(f"\nAn error occurred during the approval process: {e}")

        elif choice == '3':
            print("Exiting.")
            break

        else:
            print("\nInvalid choice. Please enter 1, 2, or 3.")
            input("Press Enter to continue...")


if __name__ == "__main__":
    main_dashboard()