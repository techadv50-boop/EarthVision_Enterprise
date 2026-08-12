"""Desktop launcher: starts local server, opens the UI, shows a control window."""

from __future__ import annotations

import socket
import sys
import threading
import time
import traceback
import webbrowser
from pathlib import Path


APP_TITLE = "DOI → ReDIF Converter"


def _log_file() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).with_name("DOI_REDIF_Converter.log")
    return Path(__file__).resolve().parent.parent / "DOI_REDIF_Converter.log"


def _append_log(text: str) -> None:
    try:
        path = _log_file()
        with path.open("a", encoding="utf-8") as fh:
            fh.write(text)
            if not text.endswith("\n"):
                fh.write("\n")
    except Exception:
        pass


def _find_free_port(host: str = "127.0.0.1") -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind((host, 0))
        return int(sock.getsockname()[1])


def _wait_until_up(host: str, port: int, timeout: float = 30.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def _run_server(host: str, port: int, error_box: list[str]) -> None:
    try:
        import uvicorn
        from app.main import app

        _append_log(f"Starting server on {host}:{port}")
        uvicorn.run(app, host=host, port=port, log_level="info", access_log=False)
    except Exception:
        msg = traceback.format_exc()
        error_box.append(msg)
        _append_log(msg)


def main() -> int:
    print(f"{APP_TITLE}")
    print("Starting... please wait a few seconds.")
    _append_log(f"--- launch {time.strftime('%Y-%m-%d %H:%M:%S')} ---")

    host = "127.0.0.1"
    port = _find_free_port(host)
    url = f"http://{host}:{port}"
    error_box: list[str] = []

    # Show a visible window immediately so double-click feels responsive
    try:
        import tkinter as tk
        from tkinter import messagebox
    except Exception as exc:
        print(f"Tkinter unavailable ({exc}); using console mode.")
        server = threading.Thread(target=_run_server, args=(host, port, error_box), daemon=True)
        server.start()
        if not _wait_until_up(host, port):
            print("Failed to start local server. See DOI_REDIF_Converter.log")
            return 1
        print(f"Open this URL in your browser:\n  {url}")
        webbrowser.open(url)
        print("Keep this window open. Press Ctrl+C to stop.")
        try:
            while True:
                time.sleep(1)
                if error_box:
                    print(error_box[0])
                    return 1
        except KeyboardInterrupt:
            return 0

    root = tk.Tk()
    root.title(APP_TITLE)
    root.geometry("520x260")
    root.minsize(480, 220)
    try:
        root.lift()
        root.attributes("-topmost", True)
        root.after(800, lambda: root.attributes("-topmost", False))
    except Exception:
        pass

    frame = tk.Frame(root, padx=18, pady=16)
    frame.pack(fill="both", expand=True)

    title = tk.Label(frame, text=APP_TITLE, font=("Segoe UI", 14, "bold"))
    title.pack(anchor="w")
    status = tk.Label(
        frame,
        text="Starting local server…",
        justify="left",
        wraplength=460,
    )
    status.pack(anchor="w", pady=(10, 8))

    link = tk.Label(frame, text="", fg="#0f6b4c", cursor="hand2")
    link.pack(anchor="w")

    btns = tk.Frame(frame)
    btns.pack(anchor="w", pady=(16, 0))
    open_btn = tk.Button(btns, text="Open in browser", width=16, state="disabled")
    open_btn.pack(side="left", padx=(0, 8))
    quit_btn = tk.Button(btns, text="Quit", width=10, command=root.destroy)
    quit_btn.pack(side="left")

    def on_close() -> None:
        if messagebox.askokcancel("Quit", "Stop DOI → ReDIF Converter?"):
            root.destroy()

    root.protocol("WM_DELETE_WINDOW", on_close)

    server = threading.Thread(target=_run_server, args=(host, port, error_box), daemon=True)
    server.start()

    def finish_start() -> None:
        if error_box:
            status.config(text="Failed to start.\nSee DOI_REDIF_Converter.log in the same folder.")
            messagebox.showerror(APP_TITLE, error_box[0][-1500:])
            return
        if not _wait_until_up(host, port, timeout=0.1):
            # keep polling via after()
            root.after(250, finish_start)
            # timeout guard using elapsed
            elapsed = time.time() - finish_start.started  # type: ignore[attr-defined]
            if elapsed > 35:
                status.config(
                    text=(
                        "Server did not start in time.\n"
                        "Close other copies of this program and try again.\n"
                        "Also check DOI_REDIF_Converter.log"
                    )
                )
            return

        status.config(
            text=(
                "App is running.\n"
                "Your browser should open automatically.\n"
                "Keep this window open while you use the converter."
            )
        )
        link.config(text=url)
        link.bind("<Button-1>", lambda _e: webbrowser.open(url))
        open_btn.config(state="normal", command=lambda: webbrowser.open(url))
        try:
            webbrowser.open(url)
        except Exception as exc:
            _append_log(f"browser open failed: {exc}")
            status.config(text=status.cget("text") + f"\nOpen manually: {url}")

    finish_start.started = time.time()  # type: ignore[attr-defined]
    root.after(300, finish_start)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
