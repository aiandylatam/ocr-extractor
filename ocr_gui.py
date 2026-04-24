"""
OCR Extractor — Interfaz gráfica / Graphical interface
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

# ── Strings i18n ──────────────────────────────────────────────────────────────

STRINGS: dict[str, dict[str, str]] = {
    "es": {
        "subtitle":          "PDF → Texto limpio  ·  nativo, escaneado e híbrido",
        "section_files":     "Archivos",
        "btn_add_folder":    "📁 Carpeta",
        "btn_clear_files":   "🗑 Limpiar",
        "files_count":       "{n} archivo(s)",
        "section_options":   "Opciones",
        "lbl_ocr_lang":      "Idioma OCR",
        "lbl_dpi":           "DPI",
        "lbl_workers":       "Workers",
        "lbl_min_conf":      "Confianza mín.",
        "chk_markers":       "Marcadores de atención  [TABLA] [IMAGEN] [?word?]",
        "lbl_tesseract":     "Tesseract",
        "ph_tess":           "Auto-detectado",
        "lbl_out_folder":    "Carpeta salida",
        "ph_out":            "out/  junto a cada PDF (default)",
        "dpi_fast":          "150  —  rápido",
        "dpi_rec":           "300  —  recomendado",
        "status_ready":      "Listo",
        "status_starting":   "Iniciando…",
        "status_processing": "Procesando: {name}",
        "status_done":       "Completado",
        "status_partial":    "Parcial",
        "status_stopped":    "⏹ Detenido por usuario.",
        "btn_run":           "▶   EXTRAER TEXTO",
        "btn_stop":          "⏹   DETENER",
        "btn_stopping":      "Deteniendo…",
        "btn_open_out":      "📂  Abrir salida",
        "btn_clear_log":     "🗒  Limpiar log",
        "dlg_sel_pdfs":      "Seleccionar PDFs",
        "dlg_folder":        "Carpeta con PDFs",
        "dlg_no_pdfs_t":     "Sin PDFs",
        "dlg_no_pdfs_m":     "No se encontraron PDFs en esa carpeta.",
        "dlg_no_files_t":    "Sin archivos",
        "dlg_no_files_m":    "Agrega al menos un PDF.",
        "dlg_conf_err_m":    "Confianza mínima: número entre 0 y 100.",
        "dlg_tess":          "tesseract.exe",
        "dlg_out_folder":    "Carpeta de salida",
        "dlg_no_out_t":      "Sin salida",
        "dlg_no_out_m":      "La carpeta de salida aún no existe.\nProcesa al menos un PDF primero.",
        "done_summary":      "OK\n{'─'*55}",
    },
    "en": {
        "subtitle":          "PDF → Clean text  ·  native, scanned & hybrid",
        "section_files":     "Files",
        "btn_add_folder":    "📁 Folder",
        "btn_clear_files":   "🗑 Clear",
        "files_count":       "{n} file(s)",
        "section_options":   "Options",
        "lbl_ocr_lang":      "OCR Language",
        "lbl_dpi":           "DPI",
        "lbl_workers":       "Workers",
        "lbl_min_conf":      "Min. confidence",
        "chk_markers":       "Attention markers  [TABLE] [IMAGE] [?word?]",
        "lbl_tesseract":     "Tesseract",
        "ph_tess":           "Auto-detected",
        "lbl_out_folder":    "Output folder",
        "ph_out":            "out/  next to each PDF (default)",
        "dpi_fast":          "150  —  fast",
        "dpi_rec":           "300  —  recommended",
        "status_ready":      "Ready",
        "status_starting":   "Starting…",
        "status_processing": "Processing: {name}",
        "status_done":       "Completed",
        "status_partial":    "Partial",
        "status_stopped":    "⏹ Stopped by user.",
        "btn_run":           "▶   EXTRACT TEXT",
        "btn_stop":          "⏹   STOP",
        "btn_stopping":      "Stopping…",
        "btn_open_out":      "📂  Open output",
        "btn_clear_log":     "🗒  Clear log",
        "dlg_sel_pdfs":      "Select PDFs",
        "dlg_folder":        "Folder with PDFs",
        "dlg_no_pdfs_t":     "No PDFs",
        "dlg_no_pdfs_m":     "No PDFs found in that folder.",
        "dlg_no_files_t":    "No files",
        "dlg_no_files_m":    "Add at least one PDF.",
        "dlg_conf_err_m":    "Minimum confidence: number between 0 and 100.",
        "dlg_tess":          "tesseract.exe",
        "dlg_out_folder":    "Output folder",
        "dlg_no_out_t":      "No output",
        "dlg_no_out_m":      "Output folder doesn't exist yet.\nProcess at least one PDF first.",
        "done_summary":      "OK\n{'─'*55}",
    },
}

# ── Constantes de UI ──────────────────────────────────────────────────────────

LANG_OPTIONS  = ["spa", "eng", "spa+eng", "fra", "por"]
WORKER_OPTS   = ["Auto", "1", "2", "4"]
DPI_VALUES    = [150, 200, 300, 400]   # valores numéricos canónicos

def _dpi_options(ui_lang: str) -> list[str]:
    s = STRINGS[ui_lang]
    return [s["dpi_fast"], "200", s["dpi_rec"], "400"]

def _dpi_map(ui_lang: str) -> dict[str, int]:
    s = STRINGS[ui_lang]
    return {s["dpi_fast"]: 150, "200": 200, s["dpi_rec"]: 300, "400": 400}

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
    candidates = [
        Path(sys.executable).parent / "tesseract" / "tesseract.exe",
        Path(__file__).parent / "tesseract" / "tesseract.exe",
        Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe"),
        Path(r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe"),
    ]
    for c in candidates:
        if c.exists():
            return str(c)
    return ""


def _detect_tessdata() -> str:
    candidates = [
        Path(sys.executable).parent / "tessdata",
        Path(__file__).parent / "tessdata",
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
        self._ui_lang: str = "es"          # idioma activo de la interfaz
        self._current_dpi_val: int = 300   # valor numérico DPI seleccionado

        self._build()
        self._auto_detect()
        self._load_argv()

    # ── Construcción de UI ────────────────────────────────────────────────────

    def _build(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(3, weight=1)

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
        hdr.grid_columnconfigure(3, weight=0)

        ctk.CTkLabel(
            hdr, text="  OCR Extractor",
            font=ctk.CTkFont(size=22, weight="bold"),
        ).grid(row=0, column=0, padx=4, pady=14, sticky="w")

        self._subtitle_lbl = ctk.CTkLabel(
            hdr, text=STRINGS["es"]["subtitle"],
            font=ctk.CTkFont(size=11), text_color="gray",
        )
        self._subtitle_lbl.grid(row=0, column=1, padx=8, pady=14, sticky="w")

        # Toggle de idioma
        self._lang_toggle = ctk.CTkSegmentedButton(
            hdr, values=["ES", "EN"], width=80,
            font=ctk.CTkFont(size=11),
            command=self._on_lang_toggle,
        )
        self._lang_toggle.set("ES")
        self._lang_toggle.grid(row=0, column=2, padx=10, pady=14)

        _credit = ctk.CTkFrame(hdr, fg_color="transparent")
        _credit.grid(row=0, column=3, padx=16, pady=10, sticky="e")
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

        self._section_files_lbl = ctk.CTkLabel(
            f, text=STRINGS["es"]["section_files"],
            font=ctk.CTkFont(size=13, weight="bold"))
        self._section_files_lbl.grid(row=0, column=0, sticky="w", padx=14, pady=(10, 4))

        btns = ctk.CTkFrame(f, fg_color="transparent")
        btns.grid(row=1, column=0, sticky="ew", padx=10, pady=(0, 6))

        ctk.CTkButton(btns, text="+ PDFs", width=110, command=self._add_files).pack(side="left", padx=3)

        self._btn_add_folder = ctk.CTkButton(
            btns, text=STRINGS["es"]["btn_add_folder"], width=120, command=self._add_folder)
        self._btn_add_folder.pack(side="left", padx=3)

        self._btn_clear_files = ctk.CTkButton(
            btns, text=STRINGS["es"]["btn_clear_files"], width=110,
            fg_color="transparent", border_width=1,
            hover_color=("gray80", "gray30"),
            command=self._clear_files,
        )
        self._btn_clear_files.pack(side="left", padx=3)

        self._count_lbl = ctk.CTkLabel(
            btns, text=STRINGS["es"]["files_count"].format(n=0),
            text_color="gray", font=ctk.CTkFont(size=11))
        self._count_lbl.pack(side="right", padx=8)

        self._files_box = ctk.CTkTextbox(f, height=100, state="disabled",
                                          font=ctk.CTkFont(family="Consolas", size=10))
        self._files_box.grid(row=2, column=0, sticky="ew", padx=10, pady=(0, 10))

    def _build_settings_panel(self):
        f = ctk.CTkFrame(self)
        f.grid(row=2, column=0, sticky="ew", padx=16, pady=(10, 0))
        f.grid_columnconfigure((1, 3, 5), weight=1)

        self._section_opts_lbl = ctk.CTkLabel(
            f, text=STRINGS["es"]["section_options"],
            font=ctk.CTkFont(size=13, weight="bold"))
        self._section_opts_lbl.grid(row=0, column=0, columnspan=6, sticky="w", padx=14, pady=(10, 6))

        def lbl(key, r, c, **kw):
            widget = ctk.CTkLabel(f, text=STRINGS["es"][key], font=ctk.CTkFont(size=11))
            widget.grid(row=r, column=c, sticky="w", padx=(12, 2), pady=4, **kw)
            return widget

        # Row 1: idioma, DPI, workers
        self._lbl_ocr_lang = lbl("lbl_ocr_lang", 1, 0)
        self._ocr_lang = ctk.StringVar(value="spa")
        ctk.CTkComboBox(f, values=LANG_OPTIONS, variable=self._ocr_lang, width=130).grid(
            row=1, column=1, sticky="ew", padx=6, pady=4)

        self._lbl_dpi = lbl("lbl_dpi", 1, 2)
        self._dpi_var = ctk.StringVar(value=STRINGS["es"]["dpi_rec"])
        self._dpi_combo = ctk.CTkComboBox(
            f, values=_dpi_options("es"), variable=self._dpi_var, width=180,
            command=self._on_dpi_change,
        )
        self._dpi_combo.grid(row=1, column=3, sticky="ew", padx=6, pady=4)

        self._lbl_workers = lbl("lbl_workers", 1, 4)
        self._workers = ctk.StringVar(value="Auto")
        ctk.CTkComboBox(f, values=WORKER_OPTS, variable=self._workers, width=90).grid(
            row=1, column=5, sticky="ew", padx=6, pady=4)

        # Row 2: min-conf, markers
        self._lbl_min_conf = lbl("lbl_min_conf", 2, 0)
        self._minconf = ctk.StringVar(value=str(LOW_CONF_WORD_THRESHOLD))
        ctk.CTkEntry(f, textvariable=self._minconf, width=60).grid(
            row=2, column=1, sticky="w", padx=6, pady=4)

        self._markers = ctk.BooleanVar(value=True)
        self._chk_markers = ctk.CTkCheckBox(
            f, text=STRINGS["es"]["chk_markers"], variable=self._markers)
        self._chk_markers.grid(row=2, column=2, columnspan=4, sticky="w", padx=12, pady=4)

        # Row 3: tesseract path
        self._lbl_tesseract = lbl("lbl_tesseract", 3, 0)
        self._tess = ctk.StringVar()
        self._tess_entry = ctk.CTkEntry(
            f, textvariable=self._tess,
            placeholder_text=STRINGS["es"]["ph_tess"])
        self._tess_entry.grid(row=3, column=1, columnspan=4, sticky="ew", padx=6, pady=4)
        ctk.CTkButton(f, text="…", width=36, command=self._browse_tess).grid(
            row=3, column=5, padx=6, pady=4)

        # Row 4: output dir
        self._lbl_out_folder = lbl("lbl_out_folder", 4, 0)
        self._outdir = ctk.StringVar()
        self._out_entry = ctk.CTkEntry(
            f, textvariable=self._outdir,
            placeholder_text=STRINGS["es"]["ph_out"])
        self._out_entry.grid(row=4, column=1, columnspan=4, sticky="ew", padx=6, pady=(4, 12))
        ctk.CTkButton(f, text="…", width=36, command=self._browse_outdir).grid(
            row=4, column=5, padx=6, pady=(4, 12))

    def _build_log_panel(self):
        f = ctk.CTkFrame(self)
        f.grid(row=3, column=0, sticky="nsew", padx=16, pady=(10, 0))
        f.grid_columnconfigure(0, weight=1)
        f.grid_rowconfigure(2, weight=1)

        hdr = ctk.CTkFrame(f, fg_color="transparent")
        hdr.grid(row=0, column=0, sticky="ew", padx=10, pady=(8, 2))
        hdr.grid_columnconfigure(1, weight=1)

        self._status = ctk.CTkLabel(
            hdr, text=STRINGS["es"]["status_ready"],
            text_color="gray", font=ctk.CTkFont(size=11))
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
            f, text=STRINGS["es"]["btn_run"], height=44,
            font=ctk.CTkFont(size=16, weight="bold"),
            fg_color=ACCENT, hover_color=ACCENT_H,
            command=self._toggle,
        )
        self._run_btn.grid(row=0, column=0, sticky="ew", pady=(0, 8))

        side = ctk.CTkFrame(f, fg_color="transparent")
        side.grid(row=1, column=0, sticky="ew")

        self._btn_open_out = ctk.CTkButton(
            side, text=STRINGS["es"]["btn_open_out"], width=160,
            fg_color="transparent", border_width=1,
            hover_color=("gray80", "gray30"),
            command=self._open_out)
        self._btn_open_out.pack(side="left", padx=3)

        self._btn_clear_log = ctk.CTkButton(
            side, text=STRINGS["es"]["btn_clear_log"], width=140,
            fg_color="transparent", border_width=1,
            hover_color=("gray80", "gray30"),
            command=self._clear_log)
        self._btn_clear_log.pack(side="left", padx=3)

    # ── Cambio de idioma ──────────────────────────────────────────────────────

    def _on_lang_toggle(self, value: str):
        self._ui_lang = value.lower()
        self._apply_lang()

    def _apply_lang(self):
        s = STRINGS[self._ui_lang]

        # Header
        self._subtitle_lbl.configure(text=s["subtitle"])

        # Files panel
        self._section_files_lbl.configure(text=s["section_files"])
        self._btn_add_folder.configure(text=s["btn_add_folder"])
        self._btn_clear_files.configure(text=s["btn_clear_files"])
        n = len(self._files)
        self._count_lbl.configure(text=s["files_count"].format(n=n))

        # Settings panel
        self._section_opts_lbl.configure(text=s["section_options"])
        self._lbl_ocr_lang.configure(text=s["lbl_ocr_lang"])
        self._lbl_dpi.configure(text=s["lbl_dpi"])
        self._lbl_workers.configure(text=s["lbl_workers"])
        self._lbl_min_conf.configure(text=s["lbl_min_conf"])
        self._chk_markers.configure(text=s["chk_markers"])
        self._lbl_tesseract.configure(text=s["lbl_tesseract"])
        self._tess_entry.configure(placeholder_text=s["ph_tess"])
        self._lbl_out_folder.configure(text=s["lbl_out_folder"])
        self._out_entry.configure(placeholder_text=s["ph_out"])

        # DPI ComboBox — preservar valor numérico actual
        new_opts = _dpi_options(self._ui_lang)
        new_map  = _dpi_map(self._ui_lang)
        self._dpi_combo.configure(values=new_opts)
        # Encontrar la etiqueta que corresponde al valor numérico guardado
        for label, val in new_map.items():
            if val == self._current_dpi_val:
                self._dpi_var.set(label)
                break

        # Log / status (solo si está en estado estático)
        if not self._running:
            self._status.configure(text=s["status_ready"])

        # Bottom bar
        if not self._running:
            self._run_btn.configure(text=s["btn_run"])
        self._btn_open_out.configure(text=s["btn_open_out"])
        self._btn_clear_log.configure(text=s["btn_clear_log"])

    def _on_dpi_change(self, value: str):
        self._current_dpi_val = _dpi_map(self._ui_lang).get(value, 300)

    def _t(self, key: str, **kwargs) -> str:
        """Shortcut para obtener string en idioma activo."""
        return STRINGS[self._ui_lang][key].format(**kwargs)

    # ── Auto-detección ────────────────────────────────────────────────────────

    def _load_argv(self):
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
            title=self._t("dlg_sel_pdfs"),
            filetypes=[("PDF", "*.pdf"), ("All" if self._ui_lang == "en" else "Todos", "*.*")],
        )
        for p in paths:
            path = Path(p)
            if path not in self._files:
                self._files.append(path)
        self._refresh_files()

    def _add_folder(self):
        folder = filedialog.askdirectory(title=self._t("dlg_folder"))
        if not folder:
            return
        pdfs = sorted(Path(folder).rglob("*.pdf"))
        added = 0
        for p in pdfs:
            if p not in self._files:
                self._files.append(p)
                added += 1
        if added == 0:
            messagebox.showinfo(self._t("dlg_no_pdfs_t"), self._t("dlg_no_pdfs_m"))
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
        self._count_lbl.configure(text=self._t("files_count", n=len(self._files)))

    # ── Navegación de rutas ───────────────────────────────────────────────────

    def _browse_tess(self):
        p = filedialog.askopenfilename(
            title=self._t("dlg_tess"),
            filetypes=[("Executable" if self._ui_lang == "en" else "Ejecutable", "*.exe"),
                       ("All" if self._ui_lang == "en" else "Todos", "*.*")],
        )
        if p:
            self._tess.set(p)

    def _browse_outdir(self):
        d = filedialog.askdirectory(title=self._t("dlg_out_folder"))
        if d:
            self._outdir.set(d)

    # ── Ejecución ─────────────────────────────────────────────────────────────

    def _toggle(self):
        if self._running:
            self._stop.set()
            self._run_btn.configure(text=self._t("btn_stopping"), fg_color="gray")
        else:
            self._start()

    def _start(self):
        if not self._files:
            messagebox.showwarning(self._t("dlg_no_files_t"), self._t("dlg_no_files_m"))
            return

        try:
            min_conf = int(self._minconf.get())
            assert 0 <= min_conf <= 100
        except (ValueError, AssertionError):
            messagebox.showerror("Error", self._t("dlg_conf_err_m"))
            return

        dpi = _dpi_map(self._ui_lang).get(self._dpi_var.get(), self._current_dpi_val)
        self._current_dpi_val = dpi

        ws = self._workers.get()
        if ws == "Auto":
            cpu = os.cpu_count() or 1
            workers = max(1, min(4, cpu))
        else:
            workers = int(ws)

        tess      = self._tess.get().strip() or None
        outdir_s  = self._outdir.get().strip()
        out_dir   = Path(outdir_s) if outdir_s else None
        tessdata  = _detect_tessdata() or None

        self._running = True
        self._stop.clear()
        self._run_btn.configure(text=self._t("btn_stop"), fg_color=RED)
        self._bar.set(0)
        self._pct.configure(text="")
        self._status.configure(text=self._t("status_starting"), text_color="gray")
        self._log_append(f"{'─'*55}\n▶ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n{'─'*55}\n")

        threading.Thread(
            target=self._worker,
            args=(list(self._files), self._ocr_lang.get(), dpi, workers,
                  min_conf, self._markers.get(), tess, tessdata, out_dir),
            daemon=True,
        ).start()
        self.after(80, self._poll)

    def _worker(self, files, lang, dpi, workers, min_conf, add_markers,
                tess_cmd, tessdata_dir, out_dir):
        try:
            import pytesseract as _pyt
        except ImportError:
            self._q.put(("log", "✗ pytesseract not installed / no instalado."))
            self._q.put(("done", (0, len(files), "")))
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
                    self._q.put(("log", STRINGS[self._ui_lang]["status_stopped"]))
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
        s = STRINGS[self._ui_lang]
        try:
            while True:
                msg = self._q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._log_append(msg[1] + "\n")
                elif kind == "progress":
                    i, total, name = msg[1]
                    self._bar.set(i / max(total, 1))
                    self._pct.configure(text=f"{i}/{total}")
                    self._status.configure(
                        text=s["status_processing"].format(name=name),
                        text_color="gray")
                elif kind == "done":
                    ok, total, last_out = msg[1][0], msg[1][1], (msg[1][2] if len(msg[1]) > 2 else "")
                    self._bar.set(1.0)
                    self._pct.configure(text=f"{ok}/{total}")
                    color = GREEN if ok == total else ("gray" if ok == 0 else "orange")
                    lbl = s["status_done"] if ok == total else s["status_partial"]
                    self._status.configure(text=f"{lbl} — {ok}/{total} OK", text_color=color)
                    self._run_btn.configure(text=s["btn_run"], fg_color=ACCENT)
                    self._running = False
                    if last_out:
                        self._last_out_dir = last_out
                    self._log_append(
                        f"{'─'*55}\n⏹ {datetime.now().strftime('%H:%M:%S')}  —  {ok}/{total} OK\n{'─'*55}\n")
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
            messagebox.showinfo(self._t("dlg_no_out_t"), self._t("dlg_no_out_m"))
            return
        os.startfile(target)


# ── Entry-point ───────────────────────────────────────────────────────────────

def main():
    import multiprocessing
    multiprocessing.freeze_support()
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
