"""Desktop launcher: starts local server, opens the UI, shows a simple control window."""

from __future__ import annotations

import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn


APP_TITLE = "DOI → ReDIF Converter"


def _find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_until_up(host: str, port: int, timeout: float = 20.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.15)
    return False


def _run_server(host: str, port: int) -> None:
    # Import inside thread so packaging entry stays light
    from app.main import app

    uvicorn.run(app, host=host, port=port, log_level="warning", access_log=False)


def _show_control_window(url: str) -> None:
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception:
        print(f"{APP_TITLE} is running at {url}")
        print("Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            return

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("460x220")
    root.minsize(420, 200)

    # Prefer a readable default font; ignore failures on minimal systems
    try:
        root.option_add("*Font", ("Segoe UI", 11))
    except Exception:
        pass

    frame = tk.Frame(root, padx=18, pady=16)
    frame.pack(fill="both", expand=True)

    tk.Label(frame, text=APP_TITLE, font=("Segoe UI", 14, "bold")).pack(anchor="w")
    tk.Label(
        frame,
        text="The app is running in your browser.\nKeep this window open while you use it.",
        justify="left",
    ).pack(anchor="w", pady=(10, 8))

    link = tk.Label(frame, text=url, fg="#0f6b4c", cursor="hand2")
    link.pack(anchor="w")
    link.bind("<Button-1>", lambda _e: webbrowser.open(url))

    btns = tk.Frame(frame)
    btns.pack(anchor="w", pady=(16, 0))

    tk.Button(btns, text="Open in browser", command=lambda: webbrowser.open(url), width=16).pack(
        side="left", padx=(0, 8)
    )
    tk.Button(btns, text="Quit", command=root.destroy, width=10).pack(side="left")

    def on_close() -> None:
        if messagebox.askokcancel("Quit", "Stop DOI → ReDIF Converter?"):
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


def main() -> int:
    host = "127.0.0.1"
    port = _find_free_port(host)
    url = f"http://{host}:{port}"

    server = threading.Thread(target=_run_server, args=(host, port), daemon=True)
    server.start()

    if not _wait_until_up(host, port):
        print("Failed to start the local server.", file=sys.stderr)
        return 1

    webbrowser.open(url)
    _show_control_window(url)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
