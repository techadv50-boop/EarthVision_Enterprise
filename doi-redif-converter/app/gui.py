"""Standalone desktop GUI (tkinter) — no browser required."""

from __future__ import annotations

import asyncio
import io
import threading
import traceback
import zipfile
from pathlib import Path
from tkinter import (
    END,
    BOTH,
    LEFT,
    RIGHT,
    X,
    Y,
    W,
    E,
    N,
    S,
    DISABLED,
    NORMAL,
    StringVar,
    IntVar,
    filedialog,
    messagebox,
    ttk,
)
import tkinter as tk

from .extractor import extract_many, inputs_from_xlsx_bytes, parse_input_list
from .models import ArticleMeta
from .redif import DEFAULT_REPEC_HANDLE_PREFIX, build_filename, to_redif
from .report import build_summary, failed_entries, format_failed_csv, format_report_text

APP_TITLE = "DOI / URL → ReDIF Converter"


class ConverterApp(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("980x720")
        self.minsize(860, 640)
        try:
            self.lift()
            self.attributes("-topmost", True)
            self.after(800, lambda: self.attributes("-topmost", False))
            self.focus_force()
        except Exception:
            pass

        self.handle_var = StringVar(value=DEFAULT_REPEC_HANDLE_PREFIX)
        self.concurrency_var = IntVar(value=5)
        self.status_var = StringVar(
            value="Standalone desktop mode. Paste DOIs and/or article URLs (no DOI required), then Start."
        )
        self.progress_var = StringVar(value="0 / 0 done · 0 left")
        self.percent_var = StringVar(value="0%")

        self._metas: list[ArticleMeta] = []
        self._running = False
        self._build()

    def _build(self) -> None:
        pad = {"padx": 12, "pady": 8}
        root = ttk.Frame(self)
        root.pack(fill=BOTH, expand=True)

        hdr = ttk.Label(root, text=APP_TITLE, font=("Segoe UI", 16, "bold"))
        hdr.pack(anchor=W, **pad)
        ttk.Label(
            root,
            text="True standalone desktop app (no browser). Paste DOIs and/or article page URLs — one per line.",
        ).pack(anchor=W, padx=12)

        body = ttk.Panedwindow(root, orient=tk.VERTICAL)
        body.pack(fill=BOTH, expand=True, padx=12, pady=8)

        top = ttk.Frame(body)
        bottom = ttk.Frame(body)
        body.add(top, weight=3)
        body.add(bottom, weight=2)

        ttk.Label(top, text="Paste DOIs or article URLs").pack(anchor=W)
        self.text = tk.Text(top, height=12, wrap="word", font=("Consolas", 10))
        self.text.pack(fill=BOTH, expand=True, pady=(4, 8))
        self.text.insert(
            "1.0",
            "https://doi.org/10.33411/IJIST/1936\n"
            "https://journal.50sea.com/index.php/IJIST/article/view/1936\n",
        )

        opts = ttk.Frame(top)
        opts.pack(fill=X, pady=(0, 6))
        ttk.Label(opts, text="RePEc handle prefix").grid(row=0, column=0, sticky=W)
        ttk.Entry(opts, textvariable=self.handle_var, width=36).grid(row=0, column=1, sticky=W, padx=(6, 18))
        ttk.Label(opts, text="Concurrency").grid(row=0, column=2, sticky=W)
        ttk.Spinbox(opts, from_=1, to=10, textvariable=self.concurrency_var, width=5).grid(
            row=0, column=3, sticky=W, padx=(6, 0)
        )

        btns = ttk.Frame(top)
        btns.pack(fill=X, pady=(0, 6))
        self.btn_load = ttk.Button(btns, text="Load Excel/Text…", command=self.load_file)
        self.btn_start = ttk.Button(btns, text="Start conversion", command=self.start)
        self.btn_export = ttk.Button(btns, text="Export ZIP…", command=self.export_zip, state=DISABLED)
        self.btn_save_dir = ttk.Button(btns, text="Save .redif folder…", command=self.save_folder, state=DISABLED)
        self.btn_clear = ttk.Button(btns, text="Clear", command=self.clear)
        for i, b in enumerate(
            (self.btn_load, self.btn_start, self.btn_export, self.btn_save_dir, self.btn_clear)
        ):
            b.pack(side=LEFT, padx=(0 if i == 0 else 6, 0))

        prog = ttk.Frame(top)
        prog.pack(fill=X, pady=(4, 0))
        ttk.Label(prog, textvariable=self.progress_var).pack(side=LEFT)
        ttk.Label(prog, textvariable=self.percent_var).pack(side=RIGHT)
        self.bar = ttk.Progressbar(top, mode="determinate", maximum=100)
        self.bar.pack(fill=X, pady=(4, 2))
        ttk.Label(top, textvariable=self.status_var, wraplength=900).pack(anchor=W, pady=(2, 0))

        # Results + report
        ttk.Label(bottom, text="Results / Final report").pack(anchor=W)
        self.report = tk.Text(bottom, height=12, wrap="word", font=("Consolas", 10))
        self.report.pack(fill=BOTH, expand=True, pady=(4, 0))
        self.report.configure(state=DISABLED)

    def _set_busy(self, busy: bool) -> None:
        self._running = busy
        state = DISABLED if busy else NORMAL
        self.btn_load.configure(state=state)
        self.btn_start.configure(state=state)
        self.btn_clear.configure(state=state)
        if not busy and self._metas:
            self.btn_export.configure(state=NORMAL)
            self.btn_save_dir.configure(state=NORMAL)
        elif busy:
            self.btn_export.configure(state=DISABLED)
            self.btn_save_dir.configure(state=DISABLED)

    def _write_report(self, text: str) -> None:
        self.report.configure(state=NORMAL)
        self.report.delete("1.0", END)
        self.report.insert("1.0", text)
        self.report.configure(state=DISABLED)

    def clear(self) -> None:
        if self._running:
            return
        self.text.delete("1.0", END)
        self._metas = []
        self.bar["value"] = 0
        self.progress_var.set("0 / 0 done · 0 left")
        self.percent_var.set("0%")
        self.status_var.set("Cleared.")
        self._write_report("")
        self.btn_export.configure(state=DISABLED)
        self.btn_save_dir.configure(state=DISABLED)

    def load_file(self) -> None:
        path = filedialog.askopenfilename(
            title="Select DOI/URL list",
            filetypes=[
                ("Excel / Text", "*.xlsx *.xlsm *.txt *.csv *.tsv"),
                ("All files", "*.*"),
            ],
        )
        if not path:
            return
        raw = Path(path).read_bytes()
        lower = path.lower()
        if lower.endswith((".xlsx", ".xlsm")):
            items = inputs_from_xlsx_bytes(raw)
        else:
            items = parse_input_list(raw.decode("utf-8", errors="ignore"))
        self.text.delete("1.0", END)
        self.text.insert("1.0", "\n".join(items))
        self.status_var.set(f"Loaded {len(items)} item(s) from {Path(path).name}")

    def start(self) -> None:
        if self._running:
            return
        items = parse_input_list(self.text.get("1.0", END))
        if not items:
            messagebox.showwarning(APP_TITLE, "Paste at least one DOI or article URL.")
            return
        handle = self.handle_var.get().strip() or DEFAULT_REPEC_HANDLE_PREFIX
        concurrency = max(1, min(int(self.concurrency_var.get() or 5), 10))

        self._set_busy(True)
        self._metas = []
        self.bar["value"] = 0
        total = len(items)
        self.progress_var.set(f"0 / {total} done · {total} left")
        self.percent_var.set("0%")
        self.status_var.set("Working… inaccessible items are skipped automatically.")
        self._write_report("Conversion started…\n")

        def worker() -> None:
            done = 0
            succeeded = 0
            failed = 0

            def on_progress(event: dict) -> None:
                nonlocal done, succeeded, failed
                if event.get("phase") != "done":
                    ref = event.get("doi") or ""
                    self.after(
                        0,
                        lambda: self.status_var.set(f"Processing: {ref}"),
                    )
                    return
                done += 1
                meta: ArticleMeta = event["meta"]
                if meta.ok:
                    succeeded += 1
                else:
                    failed += 1
                left = total - done
                pct = round(100.0 * done / total, 1) if total else 0
                ref = event.get("doi") or meta.input_ref or meta.doi
                label = f"{done} / {total} done · {left} left"
                status = (
                    f"OK {succeeded} · Failed {failed} · Current finished: {ref}"
                )

                def ui_update() -> None:
                    self.progress_var.set(label)
                    self.percent_var.set(f"{pct}%")
                    self.bar["value"] = pct
                    self.status_var.set(status)

                self.after(0, ui_update)

            try:
                metas = asyncio.run(
                    extract_many(items, concurrency=concurrency, progress_cb=on_progress)
                )
            except Exception:
                err = traceback.format_exc()

                def fail() -> None:
                    self._set_busy(False)
                    self.status_var.set("Conversion failed.")
                    self._write_report(err)
                    messagebox.showerror(APP_TITLE, "Conversion failed. See report panel.")

                self.after(0, fail)
                return

            failed_list = failed_entries(metas)
            summary = build_summary(
                total=len(metas),
                succeeded=sum(1 for m in metas if m.ok),
                failed=len(failed_list),
                failed_dois=failed_list,
            )
            report = format_report_text(summary)
            # Append per-item lines
            lines = [report, "Item details:", "-------------"]
            for meta in metas:
                ref = meta.input_ref or meta.doi or meta.landing_url
                if meta.ok:
                    lines.append(f"OK   {ref}")
                    lines.append(f"     -> {build_filename(meta)} | {meta.title[:80]}")
                else:
                    lines.append(f"FAIL {ref}")
                    lines.append(f"     {meta.error}")
            text = "\n".join(lines)

            def done_ui() -> None:
                self._metas = metas
                self._write_report(text)
                self._set_busy(False)
                self.status_var.set(
                    f"Completed. Done: {summary['succeeded']} · Failed: {summary['failed']} · Left: 0"
                )
                self.progress_var.set(f"{total} / {total} done · 0 left")
                self.percent_var.set("100%")
                self.bar["value"] = 100
                messagebox.showinfo(
                    APP_TITLE,
                    f"Finished.\n\nSucceeded: {summary['succeeded']}\nFailed: {summary['failed']}\n\n"
                    "Use Export ZIP or Save .redif folder.",
                )

            self.after(0, done_ui)

        threading.Thread(target=worker, daemon=True).start()

    def _build_zip_bytes(self) -> bytes:
        handle = self.handle_var.get().strip() or DEFAULT_REPEC_HANDLE_PREFIX
        failed = failed_entries(self._metas)
        succeeded = sum(1 for m in self._metas if m.ok)
        summary = build_summary(
            total=len(self._metas),
            succeeded=succeeded,
            failed=len(failed),
            failed_dois=failed,
        )
        buf = io.BytesIO()
        used: dict[str, int] = {}
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
            for meta in self._metas:
                if not meta.ok:
                    continue
                name = build_filename(meta)
                count = used.get(name, 0)
                used[name] = count + 1
                if count:
                    stem = name[:-6] if name.endswith(".redif") else name
                    name = f"{stem}_{count + 1}.redif"
                zf.writestr(name, to_redif(meta, handle_prefix=handle))
            zf.writestr("_conversion_report.txt", format_report_text(summary))
            zf.writestr("_failed.csv", format_failed_csv(failed))
        return buf.getvalue()

    def export_zip(self) -> None:
        if not self._metas:
            messagebox.showwarning(APP_TITLE, "Run a conversion first.")
            return
        path = filedialog.asksaveasfilename(
            title="Save ZIP",
            defaultextension=".zip",
            initialfile="redif-export.zip",
            filetypes=[("ZIP", "*.zip")],
        )
        if not path:
            return
        Path(path).write_bytes(self._build_zip_bytes())
        self.status_var.set(f"ZIP saved: {path}")
        messagebox.showinfo(APP_TITLE, f"Saved:\n{path}")

    def save_folder(self) -> None:
        if not self._metas:
            messagebox.showwarning(APP_TITLE, "Run a conversion first.")
            return
        folder = filedialog.askdirectory(title="Choose output folder")
        if not folder:
            return
        out = Path(folder)
        handle = self.handle_var.get().strip() or DEFAULT_REPEC_HANDLE_PREFIX
        used: dict[str, int] = {}
        ok = 0
        for meta in self._metas:
            if not meta.ok:
                continue
            name = build_filename(meta)
            count = used.get(name, 0)
            used[name] = count + 1
            if count:
                stem = name[:-6] if name.endswith(".redif") else name
                name = f"{stem}_{count + 1}.redif"
            (out / name).write_bytes(to_redif(meta, handle_prefix=handle).encode("utf-8"))
            ok += 1
        failed = failed_entries(self._metas)
        summary = build_summary(
            total=len(self._metas),
            succeeded=ok,
            failed=len(failed),
            failed_dois=failed,
        )
        (out / "_conversion_report.txt").write_text(format_report_text(summary), encoding="utf-8")
        (out / "_failed.csv").write_text(format_failed_csv(failed), encoding="utf-8")
        self.status_var.set(f"Saved {ok} .redif file(s) to {out}")
        messagebox.showinfo(APP_TITLE, f"Saved {ok} file(s) plus report to:\n{out}")


def run_app() -> int:
    app = ConverterApp()
    app.mainloop()
    return 0
