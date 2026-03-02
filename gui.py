"""Minimal Tkinter GUI for the Plantillas FLX report pipeline — arcade style."""

import logging
import os
import sys
import threading
import tkinter as tk
from tkinter import messagebox

from dotenv import load_dotenv

# Support PyInstaller --onefile (files extracted to temp _MEIPASS dir)
_BASE_DIR = getattr(sys, "_MEIPASS", os.path.dirname(os.path.abspath(__file__)))

load_dotenv(os.path.join(_BASE_DIR, ".env"))

from config.settings import get_config  # noqa: E402
from config.company import VALID_COMPANIES  # noqa: E402
from config.calendar import MIN_YEAR, derive_period_type  # noqa: E402

logging.basicConfig(
    level=get_config().log_level,
    format="%(asctime)s [%(levelname)s] %(message)s",
)

COMPANIES = sorted(VALID_COMPANIES)
YEARS = list(range(MIN_YEAR, MIN_YEAR + 10))

# --- Retro pixel / LED display palette ---
BG = "#2b2b2b"
FG = "#D4874E"        # warm copper/orange
FG_COPPER = "#C47A45" # slightly darker copper for labels
FG_BROWN = "#8B6040"  # muted brown for hints
BTN_BG = "#D4874E"
BTN_FG = "#2b2b2b"
ENTRY_BG = "#1e1e1e"
ENTRY_FG = "#D4874E"
CHECK_SEL = "#D4874E"
FONT = ("Fixedsys", 14)
FONT_SM = ("Fixedsys", 11)
FONT_LG = ("Fixedsys", 20)
FONT_TITLE = ("Fixedsys", 14)


def _set_windows_appid():
    """Give this app its own taskbar identity so Windows uses our icon."""
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("flx.plantillas.gui")
    except Exception:
        pass


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        _set_windows_appid()
        self.title("PLANTILLAS FLX")
        self.resizable(False, False)
        self.configure(bg=BG)

        # --- Window icon ---
        ico_path = os.path.join(_BASE_DIR, "images", "ICON.ico")
        if os.path.exists(ico_path):
            self.iconbitmap(ico_path)

        # --- Main frame ---
        frame = tk.Frame(self, bg=BG, padx=30, pady=20)
        frame.grid()

        # --- Title ---
        tk.Label(
            frame, text="[ REPORT GENERATOR ]", font=FONT_LG,
            bg=BG, fg=FG,
        ).grid(row=0, column=0, columnspan=2, pady=(0, 15))

        # --- Company ---
        tk.Label(frame, text="COMPANY:", font=FONT, bg=BG, fg=FG_COPPER).grid(
            row=1, column=0, sticky="w", pady=5,
        )
        self.company_var = tk.StringVar(value=COMPANIES[0])
        company_menu = tk.OptionMenu(frame, self.company_var, *COMPANIES)
        company_menu.config(
            font=FONT, bg=ENTRY_BG, fg=ENTRY_FG, activebackground=BG,
            activeforeground=FG, highlightthickness=1, highlightbackground=FG_COPPER,
            bd=0, width=20,
        )
        company_menu["menu"].config(font=FONT, bg=ENTRY_BG, fg=ENTRY_FG)
        company_menu.grid(row=1, column=1, pady=5, padx=(10, 0), sticky="ew")

        # --- Year ---
        tk.Label(frame, text="YEAR:", font=FONT, bg=BG, fg=FG_COPPER).grid(
            row=2, column=0, sticky="w", pady=5,
        )
        self.year_var = tk.StringVar(value=str(YEARS[0]))
        year_menu = tk.OptionMenu(frame, self.year_var, *YEARS)
        year_menu.config(
            font=FONT, bg=ENTRY_BG, fg=ENTRY_FG, activebackground=BG,
            activeforeground=FG, highlightthickness=1, highlightbackground=FG_COPPER,
            bd=0, width=20,
        )
        year_menu["menu"].config(font=FONT, bg=ENTRY_BG, fg=ENTRY_FG)
        year_menu.grid(row=2, column=1, pady=5, padx=(10, 0), sticky="ew")

        # --- Period ---
        tk.Label(frame, text="PERIOD:", font=FONT, bg=BG, fg=FG_COPPER).grid(
            row=3, column=0, sticky="w", pady=5,
        )
        self.period_var = tk.StringVar()
        period_entry = tk.Entry(
            frame, textvariable=self.period_var, font=FONT, width=22,
            bg=ENTRY_BG, fg=ENTRY_FG, insertbackground=FG,
            highlightthickness=1, highlightbackground=FG_COPPER, highlightcolor=FG,
            bd=0,
        )
        period_entry.grid(row=3, column=1, pady=5, padx=(10, 0), sticky="ew")
        tk.Label(
            frame, text="1-12 / Q1-Q4 / blank = full year",
            font=FONT_SM, bg=BG, fg=FG_BROWN,
        ).grid(row=4, column=0, columnspan=2, sticky="w")

        # --- Separator ---
        tk.Frame(frame, height=2, bg=FG_COPPER).grid(
            row=5, column=0, columnspan=2, sticky="ew", pady=(12, 8),
        )

        # --- Options ---
        tk.Label(frame, text="OUTPUT:", font=FONT, bg=BG, fg=FG).grid(
            row=6, column=0, columnspan=2, sticky="w",
        )

        self.excel_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            frame, text="EXCEL", variable=self.excel_var,
            font=FONT, bg=BG, fg=FG_COPPER, selectcolor=ENTRY_BG,
            activebackground=BG, activeforeground=FG_COPPER,
        ).grid(row=7, column=0, columnspan=2, sticky="w", padx=(15, 0))

        self.pdf_var = tk.BooleanVar(value=True)
        tk.Checkbutton(
            frame, text="PDF", variable=self.pdf_var,
            font=FONT, bg=BG, fg=FG_COPPER, selectcolor=ENTRY_BG,
            activebackground=BG, activeforeground=FG_COPPER,
        ).grid(row=8, column=0, columnspan=2, sticky="w", padx=(15, 0))

        self.send_email_var = tk.BooleanVar()
        tk.Checkbutton(
            frame, text="EMAIL", variable=self.send_email_var,
            font=FONT, bg=BG, fg=FG_COPPER, selectcolor=ENTRY_BG,
            activebackground=BG, activeforeground=FG_COPPER,
        ).grid(row=9, column=0, columnspan=2, sticky="w", padx=(15, 0))

        # --- Run button ---
        self.run_btn = tk.Button(
            frame, text=">> GENERATE <<", font=FONT_LG,
            bg=BTN_BG, fg=BTN_FG, activebackground=FG_BROWN, activeforeground=BG,
            bd=0, padx=20, pady=8, cursor="hand2",
            command=self._on_run,
        )
        self.run_btn.grid(row=10, column=0, columnspan=2, pady=(18, 5))

        # --- Status label ---
        self.status_var = tk.StringVar(value="READY.")
        tk.Label(
            frame, textvariable=self.status_var, font=FONT_TITLE,
            bg=BG, fg=FG_BROWN,
        ).grid(row=11, column=0, columnspan=2, pady=(5, 0))

        # --- ODBC driver note ---
        tk.Label(
            frame, text="Requires ODBC Driver 18 for SQL Server",
            font=FONT_SM, bg=BG, fg="#555555",
        ).grid(row=12, column=0, columnspan=2, pady=(15, 0))

    # ------------------------------------------------------------------ #
    def _parse_period(self) -> tuple[int | None, int | None] | None:
        """Parse the period text field.

        Returns (month, quarter) tuple on success, or bare None on error.
        Full year is represented as (None, None) — a truthy value, so the
        caller can distinguish it from the bare None error sentinel.
        """
        raw = self.period_var.get().strip()
        if not raw:
            return (None, None)  # full year — must stay as tuple, not bare None

        upper = raw.upper()
        if upper.startswith("Q") and upper[1:].isdigit():
            q = int(upper[1:])
            if 1 <= q <= 4:
                return None, q
            messagebox.showerror("INVALID PERIOD", "Quarter must be between Q1 and Q4.")
            return None

        try:
            m = int(raw)
        except ValueError:
            messagebox.showerror("INVALID PERIOD", "Enter a month (1-12), quarter (Q1-Q4), or leave blank.")
            return None

        if 1 <= m <= 12:
            return m, None
        messagebox.showerror("INVALID PERIOD", "Month must be between 1 and 12.")
        return None

    # ------------------------------------------------------------------ #
    def _on_run(self):
        want_excel = self.excel_var.get()
        want_pdf = self.pdf_var.get()

        if not want_excel and not want_pdf:
            messagebox.showerror("NO OUTPUT", "Select at least EXCEL or PDF.")
            return

        period = self._parse_period()
        if period is None:
            return

        month, quarter = period
        company = self.company_var.get()
        year = int(self.year_var.get())
        send_email = self.send_email_var.get()

        self.run_btn.config(state="disabled")
        self.status_var.set("GENERATING... PLEASE WAIT")
        self.update_idletasks()

        thread = threading.Thread(
            target=self._run_pipeline,
            args=(company, year, month, quarter, want_excel, want_pdf, send_email),
            daemon=True,
        )
        thread.start()

    # ------------------------------------------------------------------ #
    def _run_pipeline(self, company, year, month, quarter, want_excel, want_pdf, send_email):
        from core.pipeline import run_report
        from core.email_sender import get_email_sender

        period_type, period_num = derive_period_type(month, quarter)

        try:
            sender = get_email_sender()
            if send_email:
                sender.validate_config()

            excel_only = want_excel and not want_pdf

            excel_path, _pdf_path = run_report(
                company, year, month, quarter, period_type, period_num,
                email_sender=sender, no_email=not send_email,
                send_email=send_email, excel_only=excel_only,
            )

            # PDF-only: remove the intermediate Excel file
            if want_pdf and not want_excel and excel_path:
                os.remove(excel_path)

            self.after(0, self._done, None)
        except Exception as exc:
            self.after(0, self._done, exc)

    # ------------------------------------------------------------------ #
    def _done(self, error):
        self.run_btn.config(state="normal")
        if error:
            self.status_var.set("GAME OVER.")
            messagebox.showerror("ERROR", str(error))
        else:
            self.status_var.set("COMPLETE!")
            messagebox.showinfo("SUCCESS", "Report generated successfully!")


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
