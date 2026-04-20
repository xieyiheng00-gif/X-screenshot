"""GUI dialog to collect start/stop date from the user before crawling begins."""

import datetime
import re
import tkinter as tk
from typing import Optional, Tuple


_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _parse_date(value: str) -> Optional[datetime.date]:
    if not _DATE_RE.match(value):
        return None
    try:
        return datetime.date.fromisoformat(value)
    except ValueError:
        return None


def ask_date_range() -> Tuple[Optional[str], Optional[str]]:
    """
    Open a blocking tkinter dialog asking for start and stop dates.
    Returns (start_date, stop_date) as "YYYY-MM-DD" strings,
    or (None, None) if the user closes the window without confirming.
    """
    result: dict = {"start": None, "stop": None, "confirmed": False}

    root = tk.Tk()
    root.title("Screenshot Date Range")
    root.resizable(False, False)

    # Center the window
    root.update_idletasks()
    w, h = 340, 180
    sw = root.winfo_screenwidth()
    sh = root.winfo_screenheight()
    root.geometry(f"{w}x{h}+{(sw - w) // 2}+{(sh - h) // 2}")

    pad = {"padx": 14, "pady": 6}

    tk.Label(root, text="Start Date (recent, YYYY-MM-DD):", anchor="w").grid(
        row=0, column=0, sticky="w", **pad
    )
    today_str = datetime.date.today().isoformat()
    start_var = tk.StringVar(value=today_str)
    start_entry = tk.Entry(root, textvariable=start_var, width=18, font=("Consolas", 12))
    start_entry.grid(row=0, column=1, **pad)

    tk.Label(root, text="End Date   (older,  YYYY-MM-DD):", anchor="w").grid(
        row=1, column=0, sticky="w", **pad
    )
    stop_var = tk.StringVar(value="2025-01-01")
    stop_entry = tk.Entry(root, textvariable=stop_var, width=18, font=("Consolas", 12))
    stop_entry.grid(row=1, column=1, **pad)

    error_label = tk.Label(root, text="", fg="red", wraplength=300)
    error_label.grid(row=2, column=0, columnspan=2)

    def _confirm(event=None):
        s = start_var.get().strip()
        e = stop_var.get().strip()
        start = _parse_date(s)
        stop = _parse_date(e)
        today = datetime.date.today()
        if start is None:
            error_label.config(text="Invalid start date. Use YYYY-MM-DD.")
            return
        if stop is None:
            error_label.config(text="Invalid stop date. Use YYYY-MM-DD.")
            return
        if start > today:
            error_label.config(text=f"Start date cannot be in the future (today is {today}).")
            return
        if start <= stop:
            error_label.config(text="Start date must be more recent than end date.")
            return
        result["start"] = s
        result["stop"] = e
        result["confirmed"] = True
        root.destroy()

    btn = tk.Button(root, text="Start Crawling", command=_confirm, width=16, height=1)
    btn.grid(row=3, column=0, columnspan=2, pady=10)

    # Allow Enter key to confirm
    root.bind("<Return>", _confirm)
    start_entry.focus_set()
    root.protocol("WM_DELETE_WINDOW", root.destroy)
    root.mainloop()

    if result["confirmed"]:
        return result["start"], result["stop"]
    return None, None
