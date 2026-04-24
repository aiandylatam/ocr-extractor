"""
OCR Extractor — Interfaz gráfica
Requiere: pip install customtkinter
Backend: ocr_extractor.py en la misma carpeta.
"""

from __future__ import annotations

import os
import queue
import sys
import threading
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox

try:
    import customtkinter as ctk
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("blue")
except ImportError:
    sys.exit("Instala la dependencia de UI: pip install customtkinter")

# Backend — mismo directorio
sys.path.insert(0, str(Path(__file__).parent))
try:
    from ocr_extractor import process_one, LOW_CONF_WORD_THRESHOLD
except ImportError as _e:
    sys.exit(f"No se encontró ocr_extractor.py junto a este archivo.\n{_e}")

# ── Constantes de UI ──────────────────────────────────────────────────────────

LANG_OPTIONS  = ["spa", "eng", "spa+eng", "fra", "por"]
DPI_OPTIONS   = ["150  —  rápido", "200", "300  —  recomendado", "400"]
DPI_MAP       = {"150  —  rápido": 150, "200": 200, "300  —  recomendado": 300, "400": 400}
WORKER_OPTS   = ["Auto", "1", "2", "4"]

ACCENT   = "#1f6aa5"
ACCENT_H = "#2980b9"
RED      = "#c0392b"
GREEN    = "#27ae60"
MONO     = ("Consolas", 10)

# ── Helpers ───────────────────────────────────────────────────────────────────

class _QStream:
    """Redirige stdout/stderr al log_queue para consumo en el hilo GUI."""
    def __init__(self, q: queue.Queue):
        self._q = q
    def write(self, s: str):
        if s.strip():
            self._q.put(("log", s.rstrip()))
    def flush(self):
        pass


def _detect_tesseract() -> str:
    """Busca tesseract.exe en ubicaciones comunes; devuelve la ruta o ''."""
    candidates = [
        Path(sys.executable).parent / "tesseract" / "tesseract.exe",  # PyInstaller onedir
        Path(__file__).parent / "tesseract" / "tesseract.exe",        # ejecución directa
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return ""


def _detect_tessdata() -> str:
    """Busca la carpeta tessdata local.

    En un bundle PyInstaller (onedir), los archivos de datos quedan junto al
    ejecutable, no junto a __file__, así que buscamos en ambos lugares.
    """
    candidates = [
        Path(sys.executable).parent / "tessdata",   # PyInstaller onedir
        Path(__file__).parent / "tessdata",          # ejecución directa
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return ""


# ── Aplicación ────────────────────────────────────────────────────────────────

class App(ctk.CTk):

    def __init__(self):
        super().__init__()
        self.title("OCR Extractor")
        self.geometry("820x860")
        self.minsize(680, 640)

        self._files: list[Path] = []
        self._q: queue.Queue = queue.Queue()
        self._running = False
        self._stop = threading.Event()
        self._last_out_dir: str = ""

        self._build()
        self._auto_detect()
        self._load_argv()

    # ── Construcción de UI ────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)  # log row expands

        self._build_header()
        self._build_files_panel()
        self._build_settings_panel()
        self._build_log_panel()
        self._build_bottom_bar()

    def _build_header(self):
        hdr = ctk.CTkFrame(self, corner_radius=0, fg_color=("gray88", "gray18"))
        hdr.grid(row=0, column=0, sticky="ew")
        hdr.grid_columnconfigure(1, weight=1)
        hdr.grid_columnconfigure(2, weight=0)

        ctk.CTkLabel(
            hdr, text="  OCR Extractor",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, padx=4, pady=14, sticky="w")

        ctk.CTkLabel(
            hdr, text="PDF → Texto limpio  ·  native, escaneado e híbrido",
            font=ctk.CTkFont(size=11), text_color="gray",
        ).grid(row=0, column=1, padx=8, pady=14, sticky="w")

        _credit = ctk.CTkFrame(hdr, fg_color="transparent")
        _credit.grid(row=0, column=2, padx=16, pady=10, sticky="e")
        ctk.CTkLabel(
            _credit, text="by Andrés M.",
            font=ctk.CTkFont(size=11), text_color="gray",
        ).pack(anchor="e")
        ctk.CTkLabel(
            _credit, text="@aiAndyLatam",
            font=ctk.CTkFont(size=10), text_color=("gray60", "gray45"),
        ).pack(anchor="e")

    def _build_files_panel(self):
        f = ctk.CTkFrame(self)
        f.grid(row=1, column=0, sticky="ew", padx=16, pady=(14, 0))
        f.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(f, text="Archivos", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, sticky="w", padx=14, pady=(10, 4))

        btns = ctk.CTkFrame(f, fg_color="transparent")
        btns.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))

        ctk.CTkButton(btns, text="+ PDFs",    width=110, command=self._add_files).pack(side="left", padx=3)
        ctk.CTkButton(btns, text="📁 Carpeta", width=120, command=self._add_folder).pack(side="left", padx=3)
        ctk.CTkButton(
            btns, text="🗑 Limpiar", width=110,
            fg_color="transparent", border_width=1,
            hover_color=("gray80", "gray30"),
            command=self._clear_files,
        ).pack(side="left", padx=3)

        self._count_lbl = ctk.CTkLabel(btns, text="0 archivo(s)", text_color="gray",
                                        font=ctk.CTkFont(size=11))
        self._count_lbl.pack(side="right", padx=8)

        self._files_box = ctk.CTkTextbox(f, height=100, state="disabled",
                                          font=ctk.CTkFont(family="Consolas", size=10))
        self._files_box.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))

    def _build_settings_panel(self):
        f = ctk.CTkFrame(self)
        f.grid(row=2, column=0, sticky="ew", padx=16, pady=(10, 0))
        f.grid_columnconfigure((1, 3, 5), weight=1)

        ctk.CTkLabel(f, text="Opciones", font=ctk.CTkFont(size=13, weight="bold")).grid(
            row=0, column=0, columnspan=6, sticky="w", padx=14, pady=(10, 6))

        def lbl(text, r, c, **kw):
            ctk.CTkLabel(f, text=text, font=ctk.CTkFont(size=11)).grid(
                row=r, column=c, sticky="w", padx=(12, 2), pady=4, **kw)

        # Row 1: idioma, DPI, workers
        lbl("Idioma OCR", 1, 0)
        self._lang = ctk.StringVar(value="spa")
        ctk.CTkComboBox(f, values=LANG_OPTIONS, variable=self._lang, width=130).grid(
            row=1, column=1, sticky="ew", padx=6, pady=4)

        lbl("DPI", 1, 2)
        self._dpi = ctk.StringVar(value="300  —  recomendado")
        ctk.CTkComboBox(f, values=DPI_OPTIONS, variable=self._dpi, width=180).grid(
            row=1, column=3, sticky="ew", padx=6, pady=4)

        lbl("Workers", 1, 4)
        self._workers = ctk.StringVar(value="Auto")
        ctk.CTkComboBox(f, values=WORKER_OPTS, variable=self._workers, width=90).grid(
            row=1, column=5, sticky="ew", padx=6, pady=4)

        # Row 2: min-conf, markers
        lbl("Confianza mín.", 2, 0)
        self._minconf = ctk.StringVar(value=str(LOW_CONF_WORD_THRESHOLD))
        ctk.CTkEntry(f, textvariable=self._minconf, width=60).grid(
            row=2, column=1, sticky="w", padx=6, pady=4)

        self._markers = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(f, text="Marcadores de atención  [TABLA] [IMAGEN] [?word?]",
                        variable=self._markers).grid(
            row=2, column=2, columnspan=4, sticky="w", padx=12, pady=4)

        # Row 3: tesseract path
        lbl("Tesseract", 3, 0)
        self._tess = ctk.StringVar()
        ctk.CTkEntry(f, textvariable=self._tess, placeholder_text="Auto-detectado").grid(
            row=3, column=1, columnspan=4, sticky="ew", padx=6, pady=4)
        ctk.CTkButton(f, text="…", width=36, command=self._browse_tess).grid(
            row=3, column=5, padx=6, pady=4)

        # Row 4: output dir
        lbl("Carpeta salida", 4, 0)
        self._outdir = ctk.StringVar()
        ctk.CTkEntry(f, textvariable=self._outdir,
                     placeholder_text="out/  junto a cada PDF (default)").grid(
            row=4, column=1, columnspan=4, sticky="ew", padx=6, pady=(4, 12))
        ctk.CTkButton(f, text="…", width=36, command=self._browse_outdir).grid(
            row=4, column=5, padx=6, pady=(4, 12))

    def _build_log_panel(self):
        f = ctk.CTkFrame(self)
        f.grid(row=3, column=0, sticky="nsew", padx=16, pady=(10, 0))
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)  # row 2 = log textbox

        hdr = ctk.CTkFrame(f, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        hdr.grid_columnconfigure(1, weight=1)

        self._status = ctk.CTkLabel(hdr, text="Listo", text_color="gray",
                                     font=ctk.CTkFont(size=11))
        self._status.grid(row=0, column=0, sticky="w")
        self._pct = ctk.CTkLabel(hdr, text="", font=ctk.CTkFont(size=11))
        self._pct.grid(row=0, column=2, sticky="e")

        self._bar = ctk.CTkProgressBar(f)
        self._bar.set(0)
        self._bar.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 4))

        self._log = ctk.CTkTextbox(f, font=ctk.CTkFont(family="Consolas", size=10),
                                    state="disabled")
        self._log.grid(row=2, column=0, sticky="nsew", padx=10, pady=(4, 10))

    def _build_bottom_bar(self):
        f = ctk.CTkFrame(self, fg_color="transparent")
        f.grid(row=4, column=0, sticky="ew", padx=16, pady=14)
        f.grid_columnconfigure(0, weight=1)

        self._run_btn = ctk.CTkButton(
            f, text="▶   EXTRAER TEXTO", height=44,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_H,
            command=self._toggle,
        )
        self._run_btn.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        side = ctk.CTkFrame(f, fg_color="transparent")
        side.grid(row=1, column=0, sticky="ew")

        ctk.CTkButton(side, text="📂  Abrir salida", width=160,
                      fg_color="transparent", border_width=1,
                      hover_color=("gray80", "gray30"),
                      command=self._open_out).pack(side="left", padx=3)
        ctk.CTkButton(side, text="🗒  Limpiar log", width=140,
                      fg_color="transparent", border_width=1,
                      hover_color=("gray80", "gray30"),
                      command=self._clear_log).pack(side="left", padx=3)

    # ── Auto-detección ────────────────────────────────────────────────────────

    def _load_argv(self):
        """Load PDFs or folders passed as CLI args (drag & drop onto the .exe)."""
        for arg in sys.argv[1:]:
            p = Path(arg)
            if p.is_file() and p.suffix.lower() == ".pdf":
                if p not in self._files:
                    self._files.append(p)
            elif p.is_dir():
                for pdf in sorted(p.rglob("*.pdf")):
                    if pdf not in self._files:
                        self._files.append(pdf)
        if self._files:
            self._refresh_files()

    def _auto_detect(self):
        t = _detect_tesseract()
        if t:
            self._tess.set(t)

    # ── Manejo de archivos ────────────────────────────────────────────────────

    def _add_files(self):
        paths = filedialog.askopenfilenames(
            title="Seleccionar PDFs",
            filetypes=[("PDF", "*.pdf"), ("Todos", "*.*")],
        )
        for p in paths:
            path = Path(p)
            if path not in self._files:
                self._files.append(path)
        self._refresh_files()

    def _add_folder(self):
        folder = filedialog.askdirectory(title="Carpeta con PDFs")
        if not folder:
            return
        pdfs = sorted(Path(folder).rglob("*.pdf"))
        added = 0
        for p in pdfs:
            if p not in self._files:
                self._files.append(p)
                added += 1
        if added == 0:
            messagebox.showinfo("Sin PDFs", "No se encontraron PDFs en esa carpeta.")
        self._refresh_files()

    def _clear_files(self):
        self._files.clear()
        self._refresh_files()

    def _refresh_files(self):
        self._files_box.configure(state="normal")
        self._files_box.delete("1.0", "end")
        for p in self._files:
            self._files_box.insert("end", f"  {p.name}   ← {p.parent}\n")
        self._files_box.configure(state="disabled")
        self._count_lbl.configure(text=f"{len(self._files)} archivo(s)")

    # ── Navegación de rutas ───────────────────────────────────────────────────

    def _browse_tess(self):
        p = filedialog.askopenfilename(
            title="tesseract.exe",
            filetypes=[("Ejecutable", "*.exe"), ("Todos", "*.*")],
        )
        if p:
            self._tess.set(p)

    def _browse_outdir(self):
        d = filedialog.askdirectory(title="Carpeta de salida")
        if d:
            self._outdir.set(d)

    # ── Ejecución ─────────────────────────────────────────────────────────────

    def _toggle(self):
        if self._running:
            self._stop.set()
            self._run_btn.configure(text="Deteniendo…", fg_color="gray")
            # Don't set _running=False here — the worker's "done" message resets state.
        else:
            self._start()

    def _start(self):
        if not self._files:
            messagebox.showwarning("Sin archivos", "Agrega al menos un PDF.")
            return

        try:
            min_conf = int(self._minconf.get())
            assert 0 <= min_conf <= 100
        except (ValueError, AssertionError):
            messagebox.showerror("Error", "Confianza mínima: número entre 0 y 100.")
            return

        dpi = DPI_MAP.get(self._dpi.get(), 300)
        ws  = self._workers.get()
        if ws == "Auto":
            cpu = os.cpu_count() or 1
            workers = max(1, min(4, cpu))
        else:
            workers = int(ws)
        tess = self._tess.get().strip() or None
        outdir_s = self._outdir.get().strip()
        out_dir = Path(outdir_s) if outdir_s else None
        tessdata = _detect_tessdata() or None

        self._running = True
        self._stop.clear()
        self._run_btn.configure(text="⏹   DETENER", fg_color=RED)
        self._bar.set(0)
        self._pct.configure(text="")
        self._status.configure(text="Iniciando…", text_color="gray")
        self._log_append(f"{'─'*55}\n▶ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'─'*55}\n")

        threading.Thread(
            target=self._worker,
            args=(list(self._files), self._lang.get(), dpi, workers,
                  min_conf, self._markers.get(), tess, tessdata, out_dir),
            daemon=True,
        ).start()
        self.after(80, self._poll)

    def _worker(self, files, lang, dpi, workers, min_conf, add_markers,
                tess_cmd, tessdata_dir, out_dir):
        try:
            import pytesseract as _pyt
        except ImportError:
            self._q.put(("log", "✗ pytesseract no instalado."))
            self._q.put(("done", (0, len(files))))
            return

        if tess_cmd:
            _pyt.pytesseract.tesseract_cmd = tess_cmd

        if tessdata_dir:
            os.environ["TESSDATA_PREFIX"] = tessdata_dir

        orig_out, orig_err = sys.stdout, sys.stderr
        stream = _QStream(self._q)
        sys.stdout = sys.stderr = stream

        ok = 0
        total = len(files)
        last_out = ""
        try:
            for i, pdf in enumerate(files):
                if self._stop.is_set():
                    self._q.put(("log", "⏹ Detenido por usuario."))
                    break
                self._q.put(("progress", (i, total, pdf.name)))
                _out = out_dir if out_dir else pdf.parent / "out"
                last_out = str(_out)
                try:
                    r = process_one(
                        pdf, lang, [], _out, tessdata_dir,
                        dpi=dpi, workers=workers,
                        add_markers=add_markers, min_conf=min_conf,
                    )
                    ok += 1
                    self._q.put(("log", f"✓  {pdf.name}  —  {r.pages}p  {r.clean_chars:,} chars"))
                except Exception as exc:
                    self._q.put(("log", f"✗  {pdf.name}  —  {exc}"))
        finally:
            sys.stdout, sys.stderr = orig_out, orig_err
            self._q.put(("done", (ok, total, last_out)))

    def _poll(self):
        try:
            while True:
                msg = self._q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log_append(msg[1] + "\n")
                elif kind == "progress":
                    i, total, name = msg[1]
                    pct = i / max(total, 1)
                    self._bar.set(pct)
                    self._pct.configure(text=f"{i}/{total}")
                    self._status.configure(text=f"Procesando: {name}", text_color="gray")
                elif kind == "done":
                    ok, total, last_out = msg[1][0], msg[1][1], (msg[1][2] if len(msg[1]) > 2 else "")
                    self._bar.set(1.0)
                    self._pct.configure(text=f"{ok}/{total}")
                    color = GREEN if ok == total else ("gray" if ok == 0 else "orange")
                    self._status.configure(
                        text=f"{'Completado' if ok == total else 'Parcial'} — {ok}/{total} OK",
                        text_color=color,
                    )
                    self._run_btn.configure(text="▶   EXTRAER TEXTO", fg_color=ACCENT)
                    self._running = False
                    if last_out:
                        self._last_out_dir = last_out
                    self._log_append(f"{'─'*55}\n⏹ {datetime.now().strftime('%H:%M:%S')}  —  {ok}/{total} OK\n{'─'*55}\n")
                    return
        except queue.Empty:
            pass
        if self._running:
            self.after(80, self._poll)

    # ── Helpers de UI ─────────────────────────────────────────────────────────

    def _log_append(self, text: str):
        self._log.configure(state="normal")
        self._log.insert("end", text)
        self._log.see("end")
        self._log.configure(state="disabled")

    def _clear_log(self):
        self._log.configure(state="normal")
        self._log.delete("1.0", "end")
        self._log.configure(state="disabled")

    def _open_out(self):
        target = self._outdir.get().strip() or self._last_out_dir
        if not target and self._files:
            target = str(self._files[0].parent / "out")
        if not target or not Path(target).exists():
            messagebox.showinfo("Sin salida", "La carpeta de salida aún no existe.\nProcesa al menos un PDF primero.")
            return
        os.startfile(target)


# ── Entry-point ───────────────────────────────────────────────────────────────

def main():
    import multiprocessing
    multiprocessing.freeze_support()  # required for ProcessPoolExecutor in PyInstaller on Windows
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
