"""
OCR Extractor — PDFs → clean text.

Handles native, scanned, and hybrid PDFs. Strips page numbers, repeated
headers/footers, e-signature blocks, watermarks, and common OCR artifacts
(broken ligatures, mid-word hyphens, mid-sentence line breaks).

Usage:
    python ocr_extractor.py input.pdf
    python ocr_extractor.py input.pdf --lang spa --output-dir ./out
    python ocr_extractor.py input.pdf --extra-pattern "FOLIO SAT" --extra-pattern "Sello:"

Requirements (pip install):
    pymupdf pytesseract pillow
Plus system binary (only needed for scanned PDFs):
    tesseract  (https://github.com/UB-Mannheim/tesseract/wiki on Windows)
    On Windows, if tesseract.exe isn't on PATH, set TESSERACT_CMD env var or
    edit pytesseract.pytesseract.tesseract_cmd below.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    sys.exit("Missing dependency: pip install pymupdf")

try:
    import pytesseract
    from PIL import Image, ImageOps, ImageFilter
    _tess_env = os.environ.get("TESSERACT_CMD")
    if _tess_env:
        pytesseract.pytesseract.tesseract_cmd = _tess_env
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

try:
    import pdfplumber
    PDFPLUMBER_AVAILABLE = True
except ImportError:
    PDFPLUMBER_AVAILABLE = False


# --- Heuristics ----------------------------------------------------------

NATIVE_TEXT_MIN_CHARS_PER_PAGE = 80  # below this (AFTER signature stripping), treat page as scanned

LIGATURE_MAP = {
    "\ufb00": "ff", "\ufb01": "fi", "\ufb02": "fl",
    "\ufb03": "ffi", "\ufb04": "ffl", "\ufb05": "ft", "\ufb06": "st",
    "\u0153": "oe", "\u0152": "OE", "\u00e6": "ae", "\u00c6": "AE",
}

# Patterns to strip as signature/stamp/watermark blocks. Matched line-by-line
# (case-insensitive). Each entry is a regex that marks the *start* of a block;
# once matched, subsequent related lines are also removed.
SIGNATURE_LINE_PATTERNS = [
    r"firmado\s+(digitalmente|electr[oó]nicamente)\s+por",
    r"firma\s+electr[oó]nica\s+avanzada",
    r"certificado\s+digital",
    r"sello\s+digital",
    r"cadena\s+original",
    r"n[uú]mero\s+de\s+serie\s+del\s+certificado",
    r"^folio\s*:?\s*[A-Z0-9\-]{6,}",
    r"this\s+document\s+was\s+signed\s+electronically",
    r"docusign\s+envelope\s+id",
    # Crypto evidence blocks (PJF/PJEBC electronic signature appendix)
    r"evidencia\s+criptogr[aá]fica",
    r"^(firmante|respondedor|algoritmo|datos\s+estampillados|nombre\s+del\s+respondedor)\s*:",
    r"\bocsp\b",
    r"\btsp\b",
    r"cadena\s+de\s+firma",
    r"^([0-9a-f]{2}\s){4,}",           # hex bytes: "3a f0 12 bc ..."
]

# Standalone artifact lines: match the whole stripped line.
STANDALONE_ARTIFACT_PATTERNS = [
    r"^-?\s*\d{1,4}\s*-?$",                          # lone page number / "- 3 -"
    r"^p[aá]gina\s+\d+\s+(de|of)\s+\d+$",            # "Página N de M"
    r"^page\s+\d+\s+of\s+\d+$",
    r"^\d+\s*/\s*\d+$",                              # "3/12"
    r"^[a-f0-9]{32,}$",                              # long hex (cert/hash)
    r"^[A-Z0-9+/]{60,}={0,2}$",                      # long base64
    r"^confidential\s*(draft)?$",
    r"^borrador\s*(confidencial)?$",
    r"^(copia\s+)?sin\s+valor\s+oficial$",
    # Embedded page markers from PJF/PJEBC documents: "2 R.A. (I) 901/2025"
    r"^\d{1,3}\s+[A-Z]{1,6}\.?\s*\([IV]{1,4}\)\s+\d{1,6}/\d{4}",
    r"^-\s*\d{1,3}\s*[–—-]\s*$",                     # "- 2 –" page marker variant
]

# Watermark detection: diagonal/rotated text in PDFs often comes through as
# short ALL-CAPS fragments. We drop lines matching a small vocabulary.
WATERMARK_TOKENS = {
    "DRAFT", "BORRADOR", "COPIA", "CONFIDENTIAL", "CONFIDENCIAL",
    "SAMPLE", "MUESTRA", "VOID", "NULO", "SPECIMEN", "WATERMARK",
    "DO NOT COPY",
}

# Small set of Spanish + legal tokens used to sanity-check whether an isolated
# ALL-CAPS line plausibly reads as Spanish. Used to detect rotated/mirrored
# signature text which OCRs to gibberish uppercase words.
SPANISH_SANITY_TOKENS = {
    "DE", "LA", "EL", "EN", "DEL", "LOS", "LAS", "UN", "UNA", "POR", "CON",
    "PARA", "QUE", "SE", "AL", "ES", "SU", "COMO", "PERO", "SUS", "NI", "SIN",
    "HASTA", "DESDE", "SOBRE", "ESTE", "ESTA", "FUE", "SON", "HAY", "TODO",
    "TODA", "TODOS", "CADA", "OTRO", "OTRA", "Y", "E", "O", "U",
    # Legal / procedural
    "LEY", "AMPARO", "JUICIO", "DEMANDA", "SALA", "TRIBUNAL", "MAGISTRADO",
    "MAGISTRADOS", "DERECHO", "PARTE", "QUEJOSO", "AUTORIDAD", "ACTO",
    "FEDERACION", "FEDERACIÓN", "ESTADO", "ESTADOS", "CIRCUITO", "COLEGIADO",
    "MATERIA", "ADMINISTRATIVA", "LICENCIADO", "LIC", "CC", "FIRMA",
    "PRESENTE", "PRESENTES", "TURNO", "DIRECTO", "FRACCION", "FRACCIÓN",
    "PARRAFO", "PÁRRAFO", "PODER", "JUDICIAL", "ORGANICA", "ORGÁNICA",
    "EXPEDIENTE", "PRINCIPAL", "CEDULA", "CÉDULA", "PROFESIONAL", "NUMERO",
    "NÚMERO", "USUARIO", "DOMICILIO", "COLONIA", "CIUDAD", "CALLE",
    "MEXICANA", "MEXICANO", "BAJA", "CALIFORNIA", "PRIMERA", "SEGUNDA",
    "TERCERA", "REGIONAL", "ARTICULO", "ARTÍCULO", "CONSTITUCION",
    "CONSTITUCIÓN", "POLITICA", "POLÍTICA", "UNIDOS", "MEXICANOS",
}

SENTENCE_END = tuple(".!?:;\u2026")  # includes ellipsis


# --- Data classes --------------------------------------------------------

@dataclass
class CleanReport:
    source: Path
    pages: int = 0
    native_pages: int = 0
    ocr_pages: int = 0
    ocr_confidence: float | None = None
    raw_chars: int = 0
    clean_chars: int = 0
    headers_footers_removed: int = 0
    page_numbers_removed: int = 0
    signature_blocks_removed: int = 0
    watermarks_removed: int = 0
    custom_patterns_removed: int = 0
    ligatures_fixed: int = 0
    lines_joined: int = 0
    tables_resolved_pdfplumber: int = 0
    tables_resolved_psm6: int = 0
    tables_unresolved: int = 0
    patterns_found: dict[str, int] = field(default_factory=dict)

    def render(self) -> str:
        ratio = self.clean_chars / self.raw_chars if self.raw_chars else 0
        flag = "OK" if 0.55 <= ratio <= 0.92 else "WARN"
        lines = [
            "REPORTE DE EXTRACCIÓN",
            "─" * 40,
            f"Archivo: {self.source.name}",
            f"Formato: PDF",
            f"Páginas: {self.pages}  (nativas: {self.native_pages}, OCR: {self.ocr_pages})",
        ]
        if self.ocr_confidence is not None:
            lines.append(f"Confianza OCR promedio: {self.ocr_confidence:.1f}%")
        lines += [
            "",
            "ARTEFACTOS ELIMINADOS",
            f"  Headers/footers repetidos : {self.headers_footers_removed}",
            f"  Números de página         : {self.page_numbers_removed}",
            f"  Bloques de firma/sello    : {self.signature_blocks_removed}",
            f"  Marcas de agua            : {self.watermarks_removed}",
            f"  Patrones custom           : {self.custom_patterns_removed}",
            f"  Ligaduras corregidas      : {self.ligatures_fixed}",
            f"  Líneas unidas             : {self.lines_joined}",
        ]
        total_tables = (
            self.tables_resolved_pdfplumber
            + self.tables_resolved_psm6
            + self.tables_unresolved
        )
        if total_tables:
            resolved = self.tables_resolved_pdfplumber + self.tables_resolved_psm6
            lines += [
                "",
                "TABLAS",
                f"  Detectadas                  : {total_tables}",
                f"  Resueltas con pdfplumber    : {self.tables_resolved_pdfplumber}",
                f"  Resueltas con OCR --psm 6   : {self.tables_resolved_psm6}",
                f"  Sin capturar [TABLA]        : {self.tables_unresolved}",
                f"  Tasa de recuperacion        : {(resolved / total_tables * 100):.0f}%",
            ]
        lines += [
            "",
            "MÉTRICAS",
            f"  Chars entrada (bruto) : {self.raw_chars}",
            f"  Chars salida (limpio) : {self.clean_chars}",
            f"  Ratio de compresión   : {ratio:.2f} [{flag}]",
        ]
        if self.patterns_found:
            lines.append("")
            lines.append("PATRONES REPETIDOS DETECTADOS")
            for pat, count in sorted(self.patterns_found.items(), key=lambda x: -x[1])[:10]:
                preview = pat if len(pat) <= 60 else pat[:57] + "..."
                lines.append(f"  [{count}x] {preview}")
        return "\n".join(lines)


LOW_CONF_WORD_THRESHOLD = 50  # below this, wrap word as [?word?]

# --- Extraction ----------------------------------------------------------

def _ocr_config(tessdata_dir: str | None) -> str:
    # Set TESSDATA_PREFIX env var so tesseract finds language packs even when
    # the path contains spaces (--tessdata-dir CLI flag chokes on spaces on Windows).
    if tessdata_dir:
        os.environ["TESSDATA_PREFIX"] = tessdata_dir
    return "--psm 3"


def extract_pages(
    pdf_path: Path,
    lang: str,
    report: CleanReport,
    tessdata_dir: str | None = None,
    dpi: int = 300,
    workers: int = 1,
    mark_low_conf: bool = True,
    min_conf: int = LOW_CONF_WORD_THRESHOLD,
) -> tuple[list[str], list[dict]]:
    """Return (page_texts, page_meta). page_meta is a list of dicts per page with
    keys: page_num (1-indexed), was_ocr, avg_conf, low_conf_words, table_count, image_count.
    """
    doc = fitz.open(pdf_path)
    report.pages = len(doc)
    pages: list[str] = []
    confidences: list[float] = []
    ocr_page_indices: list[int] = []
    page_meta: list[dict] = []

    # Pre-pass: find image xrefs that repeat on many pages (court seals, letterhead
    # backgrounds). An image on > 30% of pages (min 2) is decorative — don't flag it.
    try:
        xref_counts: Counter = Counter(
            img[0]
            for page in doc
            for img in page.get_images(full=False)
        )
        decorative_xrefs = {
            xref for xref, cnt in xref_counts.items()
            if cnt >= max(2, len(doc) * 0.3)
        }
    except Exception:
        decorative_xrefs = set()

    for i, page in enumerate(doc):
        native = page.get_text("text") or ""
        # Detect tables and images on native pages — OCR pages don't have this info
        # since the whole page is a rasterized image.
        table_count = 0
        image_count = 0
        is_native = _looks_like_real_content(native)
        try:
            tf = page.find_tables()
            table_count = len(tf.tables) if hasattr(tf, "tables") else 0
        except Exception:
            table_count = 0
        if is_native:
            try:
                image_count = sum(
                    1 for img in page.get_images(full=False)
                    if img[0] not in decorative_xrefs
                )
            except Exception:
                image_count = 0

        if is_native:
            pages.append(native)
            report.native_pages += 1
            page_meta.append({
                "page_num": i + 1,
                "was_ocr": False,
                "avg_conf": None,
                "low_conf_words": 0,
                "table_count": table_count,
                "image_count": image_count,
            })
        else:
            pages.append("")  # filled by OCR below
            ocr_page_indices.append(i)
            report.ocr_pages += 1
            page_meta.append({
                "page_num": i + 1,
                "was_ocr": True,
                "avg_conf": None,        # filled after OCR
                "low_conf_words": 0,     # filled after OCR
                "table_count": table_count,
                "image_count": 0,
            })

    doc.close()

    if ocr_page_indices:
        if not OCR_AVAILABLE:
            print(
                f"[warn] {len(ocr_page_indices)} page(s) need OCR but pytesseract/"
                f"pdf2image are not installed. Those pages will be empty.",
                file=sys.stderr,
            )
        else:
            ocr_texts, per_conf, per_low = _ocr_pages(
                pdf_path, ocr_page_indices, lang, tessdata_dir,
                dpi=dpi, workers=workers, mark_low_conf=mark_low_conf, min_conf=min_conf,
            )
            for pos, idx in enumerate(ocr_page_indices):
                pages[idx] = ocr_texts[pos]
                page_meta[idx]["avg_conf"] = per_conf[pos]
                page_meta[idx]["low_conf_words"] = per_low[pos]
                if per_conf[pos]:
                    confidences.append(per_conf[pos])

    if confidences:
        report.ocr_confidence = sum(confidences) / len(confidences)

    report.raw_chars = sum(len(p) for p in pages)
    return pages, page_meta


def _looks_like_real_content(text: str) -> bool:
    """Decide if native-extracted text is real document content vs just signature/stamp noise.

    Many signed/sealed PDFs have 50–200 chars of annotation text per page (name, date,
    hex hash) but the actual body is a scanned image. We strip known-noise lines and
    require the remainder to cross NATIVE_TEXT_MIN_CHARS_PER_PAGE.
    """
    if not text:
        return False
    kept = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        # Signature / timestamp / hex / page-number patterns
        if re.match(r"^[A-Fa-f0-9]{20,}$", line):  # hex hash
            continue
        if re.match(r"^\d{1,2}[/-]\d{1,2}[/-]\d{2,4}(\s+\d{1,2}:\d{2}(:\d{2})?)?$", line):
            continue
        if re.match(r"^-?\s*\d{1,4}\s*-?$", line):  # lone page number
            continue
        if re.match(r"^p[aá]gina\s+\d+\s+(de|of)\s+\d+$", line, re.IGNORECASE):
            continue
        if len(line) < 3:
            continue
        kept.append(line)
    # Require real word content — not just ALL-CAPS name fragments
    body = " ".join(kept)
    alpha = sum(c.isalpha() for c in body)
    if alpha < NATIVE_TEXT_MIN_CHARS_PER_PAGE:
        return False
    # If every kept line is ALL CAPS (often header/signature names), likely not real content
    if kept and all(line == line.upper() for line in kept):
        return False
    return True




def _reconstruct_text_from_data(
    data: dict, mark_low_conf: bool = True, min_conf: int = LOW_CONF_WORD_THRESHOLD
) -> tuple[str, int]:
    """Reassemble Tesseract output text from image_to_data dict.

    Avoids a second Tesseract invocation (image_to_string) per page. If
    mark_low_conf is True, words with confidence below min_conf are wrapped as
    [?word?]. Returns (text, low_conf_word_count).
    """
    n = len(data.get("text", []))
    if n == 0:
        return "", 0
    lines: dict[tuple, list[str]] = {}
    order: list[tuple] = []
    low_conf = 0
    for i in range(n):
        try:
            level = int(data["level"][i])
        except (ValueError, KeyError):
            continue
        if level != 5:  # word-level
            continue
        word = data["text"][i]
        if not word or not word.strip():
            continue
        # Word-level confidence
        try:
            conf = int(data["conf"][i])
        except (ValueError, KeyError):
            conf = -1
        if mark_low_conf and 0 <= conf < min_conf:
            word = f"[?{word}?]"
            low_conf += 1
        key = (
            int(data["block_num"][i]),
            int(data["par_num"][i]),
            int(data["line_num"][i]),
        )
        if key not in lines:
            lines[key] = []
            order.append(key)
        lines[key].append(word)
    out: list[str] = []
    prev_par: tuple | None = None
    for block, par, line in order:
        par_key = (block, par)
        if prev_par is not None and par_key != prev_par:
            out.append("")  # blank line between paragraphs
        out.append(" ".join(lines[(block, par, line)]))
        prev_par = par_key
    return "\n".join(out), low_conf


def _ocr_single_page(args: tuple) -> tuple[int, str, float, int, float]:
    """Worker function — OCR one PDF page. Returns (page_idx, text, avg_conf, low_conf_words, elapsed_s).

    Self-contained so it runs in a child process via ProcessPoolExecutor.
    """
    import time as _time
    (
        pdf_path_str,
        page_idx,
        lang,
        dpi,
        cfg,
        tesseract_cmd,
        tessdata_prefix,
        mark_low_conf,
        min_conf,
    ) = args

    if tesseract_cmd:
        pytesseract.pytesseract.tesseract_cmd = tesseract_cmd
    if tessdata_prefix:
        os.environ["TESSDATA_PREFIX"] = tessdata_prefix

    start = _time.monotonic()
    doc = fitz.open(pdf_path_str)
    try:
        page = doc[page_idx]
        matrix = fitz.Matrix(dpi / 72, dpi / 72)
        pix = page.get_pixmap(matrix=matrix, alpha=False)
        img = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    finally:
        doc.close()

    # Auto-rotate: use Tesseract OSD to detect and correct page orientation.
    try:
        osd = pytesseract.image_to_osd(img, config="--psm 0")
        m = re.search(r"Rotate:\s*(\d+)", osd)
        if m:
            angle = int(m.group(1))
            if angle != 0:
                img = img.rotate(-angle, expand=True)
    except Exception:
        pass

    img = _preprocess_for_ocr(img)
    data = pytesseract.image_to_data(
        img, lang=lang, config=cfg, output_type=pytesseract.Output.DICT
    )
    text, low_conf = _reconstruct_text_from_data(data, mark_low_conf=mark_low_conf, min_conf=min_conf)
    confs = [int(c) for c in data["conf"] if str(c).lstrip("-").isdigit() and int(c) >= 0]
    avg = sum(confs) / len(confs) if confs else 0.0
    return page_idx, text, avg, low_conf, _time.monotonic() - start


def _ocr_pages(
    pdf_path: Path,
    page_indices: list[int],
    lang: str,
    tessdata_dir: str | None = None,
    dpi: int = 300,
    workers: int = 1,
    mark_low_conf: bool = True,
    min_conf: int = LOW_CONF_WORD_THRESHOLD,
) -> tuple[list[str], list[float], list[int]]:
    """OCR selected pages. Returns (texts, per_page_avg_conf, per_page_low_conf_counts)."""
    cfg = _ocr_config(tessdata_dir)
    tesseract_cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", None)
    tessdata_prefix = os.environ.get("TESSDATA_PREFIX")
    tasks = [
        (str(pdf_path), idx, lang, dpi, cfg, tesseract_cmd, tessdata_prefix, mark_low_conf, min_conf)
        for idx in page_indices
    ]
    total = len(tasks)
    results: list[tuple[int, str, float, int, float]] = []

    if workers <= 1 or total <= 1:
        # Serial path
        for i, args in enumerate(tasks, start=1):
            r = _ocr_single_page(args)
            results.append(r)
            _, _, conf, low, dur = r
            pct = (i / total) * 100
            print(
                f"    OCR page {i}/{total} ({pct:5.1f}%)  {dur:4.1f}s  conf={conf:4.1f}%  low-conf-words={low}",
                flush=True,
            )
    else:
        from concurrent.futures import ProcessPoolExecutor, as_completed
        done = 0
        with ProcessPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(_ocr_single_page, args) for args in tasks]
            for fut in as_completed(futures):
                r = fut.result()
                results.append(r)
                done += 1
                idx, _, conf, low, dur = r
                pct = (done / total) * 100
                print(
                    f"    OCR page {done}/{total} ({pct:5.1f}%)  {dur:4.1f}s  conf={conf:4.1f}%  low-conf-words={low}  [workers={workers}]",
                    flush=True,
                )

    # Sort back to original page order
    results.sort(key=lambda r: r[0])
    idx_to_pos = {idx: i for i, idx in enumerate(page_indices)}
    texts = [""] * total
    per_page_conf = [0.0] * total
    per_page_low = [0] * total
    for idx, text, conf, low, _ in results:
        pos = idx_to_pos[idx]
        texts[pos] = text
        per_page_conf[pos] = conf
        per_page_low[pos] = low
    return texts, per_page_conf, per_page_low


def _table_to_markdown(table: list[list]) -> str:
    if not table:
        return ""
    cols = max((len(r) for r in table), default=0)
    if cols < 2:
        return ""
    def cell(v):
        if v is None:
            return ""
        return str(v).replace("\n", " ").replace("|", "\\|").strip()
    norm = [[cell(c) for c in row] + [""] * (cols - len(row)) for row in table]
    header = "| " + " | ".join(norm[0]) + " |"
    sep = "| " + " | ".join(["---"] * cols) + " |"
    body = ["| " + " | ".join(row) + " |" for row in norm[1:]]
    return "\n".join([header, sep] + body)


_pdfplumber_warned = False


def _resolve_tables(
    pages: list[str],
    page_meta: list[dict],
    pdf_path: Path,
    lang: str,
    tessdata_dir: str | None,
    dpi: int,
    report: CleanReport,
    min_conf: int = LOW_CONF_WORD_THRESHOLD,
) -> None:
    """Recover content for pages flagged with [TABLA] before falling back to the marker.

    Native pages: pdfplumber → markdown. OCR pages: re-OCR with --psm 6 and keep
    the result if it captures more alphanumeric content. Mutates pages/page_meta.
    """
    global _pdfplumber_warned
    pdf_obj = None
    needs_pdfplumber = any(
        m["table_count"] > 0 and not m["was_ocr"] for m in page_meta
    )
    if needs_pdfplumber and not PDFPLUMBER_AVAILABLE and not _pdfplumber_warned:
        print(
            "[warn] pdfplumber no esta instalado — tablas en paginas nativas "
            "no se recuperaran. Instala con: pip install pdfplumber",
            file=sys.stderr,
        )
        _pdfplumber_warned = True

    for i, meta in enumerate(page_meta):
        if meta["table_count"] <= 0:
            continue

        if not meta["was_ocr"]:
            # MEJORA 1 — pdfplumber sobre páginas con texto nativo
            md_blocks: list[str] = []
            if PDFPLUMBER_AVAILABLE:
                if pdf_obj is None:
                    try:
                        pdf_obj = pdfplumber.open(pdf_path)
                    except Exception as e:
                        print(f"[warn] pdfplumber no pudo abrir {pdf_path.name}: {e}", file=sys.stderr)
                if pdf_obj is not None:
                    try:
                        tables = pdf_obj.pages[i].extract_tables() or []
                    except Exception:
                        tables = []
                    for tbl in tables:
                        md = _table_to_markdown(tbl)
                        if md:
                            md_blocks.append(md)
            if md_blocks:
                meta["table_markdown"] = "\n\n".join(md_blocks)
                meta["table_status"] = "pdfplumber"
                report.tables_resolved_pdfplumber += 1
            else:
                meta["table_status"] = "unresolved"
                report.tables_unresolved += 1
            continue

        # MEJORA 2 — re-OCR con --psm 6 sobre páginas escaneadas
        if not OCR_AVAILABLE:
            meta["table_status"] = "unresolved"
            report.tables_unresolved += 1
            continue
        try:
            tess_cmd = getattr(pytesseract.pytesseract, "tesseract_cmd", None)
            tess_prefix = os.environ.get("TESSDATA_PREFIX")
            args = (str(pdf_path), i, lang, dpi, "--psm 6", tess_cmd, tess_prefix, True, min_conf)
            _, text6, _, _, _ = _ocr_single_page(args)
        except Exception as e:
            print(f"[warn] re-OCR psm6 fallo en pagina {i + 1}: {e}", file=sys.stderr)
            text6 = ""

        orig_alnum = sum(c.isalnum() for c in pages[i])
        new_alnum = sum(c.isalnum() for c in text6)
        if text6.strip() and new_alnum > orig_alnum:
            pages[i] = text6
            meta["table_status"] = "psm6"
            report.tables_resolved_psm6 += 1
        else:
            meta["table_status"] = "unresolved"
            report.tables_unresolved += 1

    if pdf_obj is not None:
        try:
            pdf_obj.close()
        except Exception:
            pass


_TIMESTAMP_RE = re.compile(r"\d{1,2}/\d{1,2}/\d{2,4}\s+\d{1,2}:\d{2}")
_HASH_RE       = re.compile(r"[A-Fa-f0-9]{32,}")

def _collapse_signature_pages(
    pages: list[str],
    page_meta: list[dict],
    report: CleanReport,
) -> None:
    """Replace nearly-empty OCR pages that contain only signature/timestamp content
    with a single marker line. Mutates pages in place."""
    for i, meta in enumerate(page_meta):
        if not meta["was_ocr"]:
            continue
        text = pages[i]
        words = [w for w in text.split() if len(w) >= 2]
        if len(words) >= 30:
            continue
        has_timestamp = bool(_TIMESTAMP_RE.search(text))
        has_hash      = bool(_HASH_RE.search(text))
        if has_timestamp or has_hash:
            pages[i] = f"[PÁGINA {meta['page_num']} — FIRMA ELECTRÓNICA — contenido omitido]"
            meta["was_ocr"] = False   # suppress further OCR flags for this page
            meta["avg_conf"] = None
            meta["low_conf_words"] = 0
            report.signature_blocks_removed += 1


# Roman numeral chars that OCR commonly confuses
_ROMAN_NOISE = re.compile(r"[IVXLCDM][IVXLCDM!l|]{0,7}[IVXLCDM!l|]")

def _fix_roman(token: str) -> str:
    return token.replace("!", "I").replace("l", "I").replace("|", "I")

_DAYS_OF_WEEK = r"LUNES\s+MARTES\s+MI[EÉ]RCOLES\s+JUEVES\s+VIERNES\s+S[AÁ]BADO\s+DOMINGO"

def _fix_legal_patterns(text: str) -> str:
    """Post-OCR corrections for common errors in Mexican judicial documents."""
    # Fix ! and | as I inside Roman numeral sequences
    text = _ROMAN_NOISE.sub(lambda m: _fix_roman(m.group()), text)

    # Fix ordinal zero in citation keys: "20.P.A" → "2o.P.A"
    text = re.sub(r"(\d)0\.(?=[A-Z])", r"\1o.", text)

    # Fix low-conf fraction markers: "fracción [?1?]" → "fracción I" etc.
    frac_map = {"1": "I", "11": "II", "111": "III", "1V": "IV", "V1": "VI",
                "V11": "VII", "V111": "VIII", "1X": "IX", "X1": "XI"}
    def _fix_frac(m: re.Match) -> str:
        inner = m.group(1).strip()
        return f"fracción {frac_map.get(inner, f'[?{inner}?]')}"
    text = re.sub(
        r"fracc(?:i[oó]n|\.)\s+\[\?([IVXivx1lL|!]{1,6})\?\]",
        _fix_frac, text, flags=re.IGNORECASE,
    )

    # Semantic fix: "ser interior a [quantity]" → "ser inferior a" (4.2)
    text = re.sub(
        r"\bser\s+interior\s+a\s+(?=\d|dos|tres|cuatro|cinco)",
        "ser inferior a ", text, flags=re.IGNORECASE,
    )

    # Remove consecutive duplicate words: "del del" → "del" (4.4)
    text = re.sub(r"\b(\w{2,})\s+\1\b", r"\1", text, flags=re.IGNORECASE)

    # Mark calendar computation tables (3.3)
    text = re.sub(
        _DAYS_OF_WEEK + r".{0,600}?(?=\n\n|\Z)",
        "[TABLA: CÓMPUTO DE DÍAS — revisar en PDF original]",
        text, flags=re.IGNORECASE | re.DOTALL,
    )

    return text


def _preprocess_for_ocr(img: Image.Image) -> Image.Image:
    img = img.convert("L")               # grayscale
    img = ImageOps.autocontrast(img, cutoff=2)
    img = img.filter(ImageFilter.SHARPEN)
    return img


# --- Cleaning ------------------------------------------------------------

def _fingerprint(line: str) -> str:
    """Stable signature for fuzzy repeated-line detection.

    Sorted lowercase letters only — catches the same header/footer even when
    OCR produces slight character variations across pages, and catches rotated
    signature text that appears mirrored per page.
    """
    return "".join(sorted(c.lower() for c in line if c.isalnum()))


def detect_repeated_lines(pages: list[str], threshold: float = 0.4) -> tuple[set[str], set[str]]:
    """Returns (exact_repeats, fingerprint_repeats) — lines to drop.

    A line on >threshold fraction of pages is a header/footer. We track both
    exact matches and sorted-letter fingerprints to catch OCR-drifted repeats.
    """
    if len(pages) < 3:
        return set(), set()
    exact: Counter[str] = Counter()
    fps: Counter[str] = Counter()
    for page in pages:
        seen_exact: set[str] = set()
        seen_fp: set[str] = set()
        for raw in page.splitlines():
            line = raw.strip()
            if not (3 <= len(line) <= 120):
                continue
            if line not in seen_exact:
                exact[line] += 1
                seen_exact.add(line)
            fp = _fingerprint(line)
            # Only fingerprint substantive lines (avoid tiny/empty fingerprints)
            if len(fp) >= 8 and fp not in seen_fp:
                fps[fp] += 1
                seen_fp.add(fp)
    min_count = max(3, int(len(pages) * threshold))
    exact_set = {line for line, c in exact.items() if c >= min_count}
    fp_set = {fp for fp, c in fps.items() if c >= min_count}
    return exact_set, fp_set


LOW_CONF_PAGE_THRESHOLD = 75  # below this, mark page as "confianza baja"


def _build_attention_summary(page_meta: list[dict]) -> tuple[str, list[int]]:
    """Return (summary_block, flagged_page_nums). Empty string if no issues."""
    lines: list[str] = []
    flagged: list[int] = []
    for meta in page_meta:
        issues: list[str] = []
        if meta["was_ocr"] and meta["avg_conf"] is not None and meta["avg_conf"] < LOW_CONF_PAGE_THRESHOLD:
            low = meta["low_conf_words"]
            if low:
                issues.append(f"confianza OCR {meta['avg_conf']:.0f}% ({low} palabras dudosas)")
            else:
                issues.append(f"confianza OCR {meta['avg_conf']:.0f}%")
        if meta["table_count"] and meta.get("table_status") not in ("pdfplumber", "psm6"):
            word = "tabla sin capturar" if meta["table_count"] == 1 else "tablas sin capturar"
            issues.append(f"{meta['table_count']} {word}")
        if meta["image_count"]:
            word = "imagen/grafico" if meta["image_count"] == 1 else "imagenes/graficos"
            issues.append(f"{meta['image_count']} {word} en la pagina")
        if issues:
            flagged.append(meta["page_num"])
            lines.append(f"  p.{meta['page_num']:<3} - {'; '.join(issues)}")
    if not lines:
        return "", []
    header = "=" * 60
    out = [
        header,
        "  PAGINAS QUE REQUIEREN ATENCION (revisar en PDF original)",
        header,
        *lines,
        header,
        "",
    ]
    return "\n".join(out), flagged


def _build_ai_instructions(flagged: list[int], source_name: str) -> str:
    """Meta-block directing any AI that ingests this file as context.

    Flips the burden from reactive flagging (which has blind spots — the AI
    can't flag content it can't see) to proactive disclosure at the start of
    the conversation.
    """
    flagged_str = ", ".join(f"p.{n}" for n in flagged) if flagged else "(ninguna detectada)"
    lines = [
        "=" * 68,
        "  INSTRUCCIONES PARA IA QUE LEA ESTE DOCUMENTO COMO CONTEXTO",
        "=" * 68,
        "",
        f"Archivo fuente: {source_name}",
        "Este texto fue extraido automaticamente de un PDF con OCR y puede",
        "contener imprecisiones o contenido no capturado (tablas, imagenes,",
        "regiones con OCR dudoso).",
        "",
        "PROTOCOLO OBLIGATORIO al iniciar cualquier discusion sobre este",
        "documento con el usuario:",
        "",
        f"  1. AVISA al usuario que las siguientes paginas tienen contenido",
        f"     potencialmente incompleto o dudoso: {flagged_str}",
        "",
        "  2. ADVIERTE que cualquier pregunta del usuario podria tocar",
        "     contenido NO capturado en esas paginas (una tabla cuyo contenido",
        "     se perdio, una imagen con texto, palabras OCR erroneas).",
        "",
        "  3. REGLA CLAVE: NO interpretes la ausencia de un tema en el texto",
        "     extraido como ausencia en el documento original. En paginas",
        "     marcadas, el silencio puede ser contenido no capturado.",
        "     Recomienda SIEMPRE verificar en el PDF original antes de",
        "     afirmar con certeza que el documento 'no dice' o 'no contiene'",
        "     algo relativo a esas paginas.",
        "",
        "MARCADORES QUE VERAS EN EL TEXTO:",
        "  [?palabra?]              = palabra con baja confianza OCR (posible error)",
        "  [!] CONFIANZA OCR BAJA   = pagina con OCR dudoso en su mayoria",
        "  [TABLA]                  = pagina contiene tabla cuya estructura se perdio",
        "  [IMAGEN]                 = pagina contiene imagen/grafico no extraido",
        "  === Pagina N ===         = marcador de pagina (referencia al PDF original)",
        "",
        "=" * 68,
        "",
    ]
    return "\n".join(lines)


def _page_attention_marker(meta: dict) -> str:
    """Inline marker placed after a page header, flagging issues on that page."""
    flags: list[str] = []
    if meta["was_ocr"] and meta["avg_conf"] is not None and meta["avg_conf"] < LOW_CONF_PAGE_THRESHOLD:
        flags.append(f"[!] CONFIANZA OCR BAJA {meta['avg_conf']:.0f}% - revisar")
    status = meta.get("table_status")
    if status == "pdfplumber" and meta.get("table_markdown"):
        flags.append("[TABLA capturada con pdfplumber]")
        flags.append(meta["table_markdown"])
    elif status == "psm6":
        flags.append("[TABLA recuperada con OCR --psm 6 - texto integrado en la pagina]")
    elif meta["table_count"]:
        flags.append(f"[TABLA] {meta['table_count']} tabla(s) sin capturar - revisar estructura en PDF")
    if meta["image_count"]:
        flags.append(f"[IMAGEN] {meta['image_count']} imagen(es)/grafico(s) en la pagina - revisar en PDF")
    return "\n".join(flags)


def clean_text(
    pages: list[str],
    extra_patterns: list[str],
    report: CleanReport,
    page_meta: list[dict] | None = None,
    add_markers: bool = True,
    source_name: str = "",
) -> str:
    repeated, repeated_fps = detect_repeated_lines(pages, threshold=0.2)
    if repeated:
        for line in repeated:
            report.patterns_found[line] = sum(p.count(line) for p in pages)

    signature_re = re.compile("|".join(SIGNATURE_LINE_PATTERNS), re.IGNORECASE)
    standalone_re = re.compile("|".join(STANDALONE_ARTIFACT_PATTERNS), re.IGNORECASE)
    extra_res = [re.compile(p, re.IGNORECASE) for p in extra_patterns]

    cleaned_pages: list[str] = []
    for page in pages:
        lines = page.splitlines()
        kept: list[str] = []
        skip_block = 0  # lines remaining to skip after a signature trigger

        for raw in lines:
            stripped = raw.strip()

            if skip_block > 0 and stripped:
                # Drop lines that look like signature metadata continuation
                if _looks_like_signature_meta(stripped):
                    skip_block -= 1
                    report.signature_blocks_removed += 1
                    continue
                skip_block = 0

            if not stripped:
                kept.append("")
                continue

            if stripped in repeated:
                report.headers_footers_removed += 1
                continue

            if _fingerprint(stripped) in repeated_fps:
                report.headers_footers_removed += 1
                continue

            if standalone_re.match(stripped):
                if re.match(r"^-?\s*\d", stripped) or "/" in stripped or "pagina" in stripped.lower() or "page" in stripped.lower():
                    report.page_numbers_removed += 1
                else:
                    report.custom_patterns_removed += 1
                continue

            if _is_watermark_line(stripped):
                report.watermarks_removed += 1
                continue

            if _is_ocr_gibberish(stripped):
                report.watermarks_removed += 1
                continue

            if signature_re.search(stripped):
                report.signature_blocks_removed += 1
                skip_block = 6  # consume up to 6 follow-on metadata lines
                continue

            dropped_by_custom = False
            for rx in extra_res:
                if rx.search(stripped):
                    report.custom_patterns_removed += 1
                    dropped_by_custom = True
                    break
            if dropped_by_custom:
                continue

            kept.append(raw.rstrip())

        cleaned_pages.append("\n".join(kept))

    # Join pages with a unique sentinel so cleanup passes don't touch the boundary.
    # We substitute real page headers + attention markers after all cleanup.
    sentinel_tpl = "\n\n__OCR_PAGE_BREAK_{idx}__\n\n"
    joined_parts: list[str] = []
    for i, pg in enumerate(cleaned_pages):
        if i > 0:
            joined_parts.append(sentinel_tpl.format(idx=i))
        joined_parts.append(pg)
    text = "".join(joined_parts)

    text, n_sigs = _drop_isolated_rotated_signatures(text)
    report.watermarks_removed += n_sigs

    text, n_lig = _fix_ligatures(text)
    report.ligatures_fixed = n_lig

    text, n_joined = _join_broken_lines(text)
    report.lines_joined = n_joined

    text = _fix_legal_patterns(text)

    text = _collapse_whitespace(text)

    # Replace sentinels with page headers + per-page attention markers.
    if add_markers and page_meta:
        # The text starts with page 1. Prepend its header.
        first_header = f"=== Pagina {page_meta[0]['page_num']} ===\n"
        first_marker = _page_attention_marker(page_meta[0])
        prefix = first_header
        if first_marker:
            prefix += first_marker + "\n"
        prefix += "\n"
        text = prefix + text.lstrip("\n")

        def _sub(m: "re.Match") -> str:
            idx = int(m.group(1))
            meta = page_meta[idx] if idx < len(page_meta) else None
            if not meta:
                return "\n\n"
            header = f"\n\n=== Pagina {meta['page_num']} ===\n"
            marker = _page_attention_marker(meta)
            if marker:
                header += marker + "\n"
            return header + "\n"

        text = re.sub(r"__OCR_PAGE_BREAK_(\d+)__", _sub, text)

        summary, flagged = _build_attention_summary(page_meta)
        if summary:
            text = summary + "\n" + text
        # Prepend the AI instructions block so any model loading this file as
        # context gets the proactive-disclosure protocol.
        ai_block = _build_ai_instructions(flagged, source_name)
        text = ai_block + text
    else:
        # Markers disabled — just strip sentinels, preserving the blank line.
        text = re.sub(r"__OCR_PAGE_BREAK_\d+__", "", text)
        text = re.sub(r"\n{3,}", "\n\n", text)

    report.clean_chars = len(text)
    return text


def _looks_like_signature_meta(line: str) -> bool:
    low = line.lower()
    triggers = (
        "certificado", "fecha:", "hora:", "folio", "serie",
        "razon", "razón", "ubicación", "ubicacion",
        "@", "rfc:", "curp:", "docusign", "envelope",
    )
    if any(t in low for t in triggers):
        return True
    # long hex / base64 fragments often appear inside signature blocks
    if re.match(r"^[A-Za-z0-9+/=\-]{40,}$", line):
        return True
    return False


def _is_ocr_gibberish(line: str) -> bool:
    """Detect rotated-signature noise and hash fragments that OCR produces.

    These appear at the top/bottom of signed pages — each instance is slightly
    different due to OCR noise so exact-match de-duplication misses them.
    """
    s = line.strip()
    if not s or len(s) > 80:
        return False
    # Long digit runs with no spaces — hash/signature IDs
    if " " not in s and sum(c.isdigit() for c in s) >= 8:
        return True
    # Heavy non-language punctuation (quotes, slashes, backslashes mixed in)
    noise = sum(1 for c in s if not c.isalnum() and c not in " .,:;¿?¡!()-/'\u2013\u2014")
    if len(s) >= 10 and noise / len(s) > 0.25:
        return True
    # ALL-CAPS lines of moderate length where no token resembles a real word
    # (rotated signature text tends to produce jumbled uppercase fragments).
    if 12 <= len(s) <= 60 and s.isupper():
        tokens = [t for t in s.split() if len(t) >= 3]
        if tokens:
            # Real Spanish/English words almost always have at least one vowel
            # and a reasonable vowel ratio. Jumbled rotated text often has
            # tokens with lopsided vowel distribution or improbable bigrams.
            odd = 0
            for tok in tokens:
                alpha = [c for c in tok if c.isalpha()]
                if not alpha:
                    odd += 1
                    continue
                vowels = sum(1 for c in alpha if c in "AEIOU")
                ratio = vowels / len(alpha)
                if ratio < 0.15 or ratio > 0.75:
                    odd += 1
            if odd >= max(1, len(tokens) // 2 + 1):
                return True
    return False


def _looks_like_rotated_signature(line: str) -> bool:
    """True for short ALL-CAPS lines whose tokens don't resemble Spanish words.

    The caller must ensure the line is isolated (blank lines above/below) to
    avoid dropping legitimate all-caps headings that happen to contain
    uncommon words.
    """
    s = line.strip()
    if not (12 <= len(s) <= 60):
        return False
    alpha = [c for c in s if c.isalpha()]
    if len(alpha) < 8:
        return False
    # "Mostly uppercase" — tolerate OCR noise that lowercases a few letters
    upper_ratio = sum(1 for c in alpha if c.isupper()) / len(alpha)
    if upper_ratio < 0.75:
        return False
    tokens = [t.strip(".,;:").upper() for t in s.split() if len(t) >= 2]
    if len(tokens) < 2:
        return False
    hits = sum(1 for t in tokens if t in SPANISH_SANITY_TOKENS)
    # If no tokens matched any common Spanish/legal word, likely gibberish.
    return hits == 0


def _is_watermark_line(line: str) -> bool:
    # Short, all-caps, single-word-ish fragments matching known tokens
    up = line.upper().strip()
    if up in WATERMARK_TOKENS:
        return True
    if len(line) <= 40 and line.isupper():
        if any(tok in up for tok in WATERMARK_TOKENS):
            # Avoid killing headings that happen to contain "COPIA DE..."
            return len(up.split()) <= 3
    return False


def _drop_isolated_rotated_signatures(text: str) -> tuple[str, int]:
    """Remove ALL-CAPS gibberish lines that are isolated between blanks.

    Run after page-level cleaning so we can check neighboring-line context.
    """
    lines = text.split("\n")
    out: list[str] = []
    removed = 0
    for i, line in enumerate(lines):
        prev_blank = i == 0 or not lines[i - 1].strip()
        next_blank = i == len(lines) - 1 or not lines[i + 1].strip()
        if prev_blank and next_blank and _looks_like_rotated_signature(line):
            removed += 1
            continue
        out.append(line)
    return "\n".join(out), removed


def _fix_ligatures(text: str) -> tuple[str, int]:
    count = 0
    for bad, good in LIGATURE_MAP.items():
        c = text.count(bad)
        if c:
            text = text.replace(bad, good)
            count += c
    text = unicodedata.normalize("NFKC", text)
    return text, count


def _join_broken_lines(text: str) -> tuple[str, int]:
    # Join hyphen-broken words: "pala-\nbra" → "palabra"
    text, n1 = re.subn(r"(\w)-\n(\w)", r"\1\2", text)

    # Join mid-sentence line breaks: if line doesn't end with sentence punctuation
    # and next line starts lowercase, join with a space.
    out_lines: list[str] = []
    joined = 0
    for line in text.split("\n"):
        if out_lines and out_lines[-1] and not out_lines[-1].rstrip().endswith(SENTENCE_END):
            prev = out_lines[-1].rstrip()
            if line and line[:1].islower() and len(prev) > 20:
                out_lines[-1] = prev + " " + line.lstrip()
                joined += 1
                continue
        out_lines.append(line)
    return "\n".join(out_lines), n1 + joined


def _collapse_whitespace(text: str) -> str:
    # Collapse runs of spaces/tabs, but preserve newlines.
    text = re.sub(r"[ \t]+", " ", text)
    # Collapse 3+ blank lines to 2.
    text = re.sub(r"\n{3,}", "\n\n", text)
    # Strip trailing whitespace per line.
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return text.strip() + "\n"


# --- Output --------------------------------------------------------------

def write_outputs(clean: str, report: CleanReport, source: Path, out_dir: Path) -> tuple[Path, Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = source.stem
    txt_path = out_dir / f"{stem}_limpio.txt"
    md_path = out_dir / f"{stem}_skill_ref.md"
    report_path = out_dir / f"{stem}_reporte.txt"

    txt_path.write_text(clean, encoding="utf-8")

    today = datetime.now().strftime("%Y-%m-%d")
    md = (
        f"## Referencia: {stem}\n"
        f"*Fuente: {source.name} | Formato: PDF | Páginas: {report.pages} | "
        f"Extraído: {today}*\n\n{clean}"
    )
    md_path.write_text(md, encoding="utf-8")
    report_path.write_text(report.render(), encoding="utf-8")
    return txt_path, md_path, report_path


# --- CLI -----------------------------------------------------------------

def _prompt_markers() -> bool:
    """Ask whether to include attention markers + AI instructions. True = include."""
    if not sys.stdin or not sys.stdin.isatty():
        return True  # safe default for non-interactive runs
    print()
    print("¿Incluir marcadores de atencion e instrucciones para IA en el texto extraido?")
    print("  1) Si - con marcadores [TABLA], [IMAGEN], [?palabra?] e instrucciones de verificacion  [default]")
    print("  2) No - texto limpio sin marcadores ni instrucciones")
    while True:
        try:
            choice = input("Elige [1-2, Enter = 1]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return True
        if choice == "" or choice == "1":
            return True
        if choice == "2":
            return False
        print("Opcion invalida, intenta de nuevo.")


def _prompt_language() -> str:
    """Ask the user which language(s) to OCR. Falls back to spa+eng if non-interactive."""
    if not sys.stdin or not sys.stdin.isatty():
        return "spa+eng"
    print()
    print("¿En qué idioma(s) están los PDFs?")
    print("  1) Español")
    print("  2) Inglés")
    print("  3) Ambos / mezclado  [default]")
    print("  4) Otro (especificar código Tesseract, ej. 'fra', 'por+spa')")
    while True:
        try:
            choice = input("Elige [1-4, Enter = 3]: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return "spa+eng"
        if choice == "" or choice == "3":
            return "spa+eng"
        if choice == "1":
            return "spa"
        if choice == "2":
            return "eng"
        if choice == "4":
            try:
                custom = input("Codigo(s) Tesseract (separa varios con '+'): ").strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return "spa+eng"
            if custom:
                return custom
        print("Opcion invalida, intenta de nuevo.")


def _collect_pdfs(inputs: list[Path], recursive: bool) -> list[Path]:
    """Resolve a mix of files, directories, and globs into a sorted list of PDFs."""
    found: list[Path] = []
    for item in inputs:
        # Glob patterns
        s = str(item)
        if any(ch in s for ch in "*?[]"):
            matches = [Path(p) for p in sorted(__import__("glob").glob(s, recursive=recursive))]
            found.extend(m for m in matches if m.is_file() and m.suffix.lower() == ".pdf")
            continue
        if item.is_dir():
            pattern = "**/*.pdf" if recursive else "*.pdf"
            found.extend(sorted(item.glob(pattern)))
            continue
        if item.is_file() and item.suffix.lower() == ".pdf":
            found.append(item)
    # Dedupe preserving order
    seen: set[Path] = set()
    unique: list[Path] = []
    for p in found:
        resolved = p.resolve()
        if resolved not in seen:
            seen.add(resolved)
            unique.append(p)
    return unique


def process_one(
    pdf: Path,
    lang: str,
    extra_patterns: list[str],
    output_dir: Path,
    tessdata_dir: str | None,
    dpi: int = 300,
    workers: int = 1,
    add_markers: bool = True,
    min_conf: int = LOW_CONF_WORD_THRESHOLD,
) -> CleanReport:
    report = CleanReport(source=pdf)
    pages, page_meta = extract_pages(
        pdf, lang, report, tessdata_dir, dpi=dpi, workers=workers,
        mark_low_conf=add_markers, min_conf=min_conf,
    )
    _collapse_signature_pages(pages, page_meta, report)
    _resolve_tables(pages, page_meta, pdf, lang, tessdata_dir, dpi, report, min_conf=min_conf)
    clean = clean_text(
        pages, extra_patterns, report,
        page_meta=page_meta, add_markers=add_markers, source_name=pdf.name,
    )
    write_outputs(clean, report, pdf, output_dir)
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description="Extract clean text from PDFs (native, scanned, or hybrid).")
    ap.add_argument(
        "inputs",
        type=Path,
        nargs="+",
        help="One or more inputs: PDF files, directories, or glob patterns (e.g. '*.pdf').",
    )
    ap.add_argument(
        "--lang",
        default=None,
        help="Tesseract language(s), e.g. 'spa', 'eng', 'spa+eng'. If omitted, prompts interactively.",
    )
    ap.add_argument("--output-dir", type=Path, default=Path("./out"), help="Output directory")
    ap.add_argument("--recursive", "-r", action="store_true", help="Recurse into subdirectories when a directory is given.")
    ap.add_argument(
        "--extra-pattern",
        action="append",
        default=[],
        help="Extra regex pattern to strip (repeatable).",
    )
    ap.add_argument(
        "--tesseract-cmd",
        default=None,
        help="Path to tesseract.exe if not on PATH. Also honored via env TESSERACT_CMD.",
    )
    ap.add_argument(
        "--tessdata-dir",
        default=None,
        help="Custom tessdata directory (for language packs installed outside the default).",
    )
    ap.add_argument(
        "--continue-on-error",
        action="store_true",
        default=True,
        help="Keep processing remaining PDFs if one fails (default: on).",
    )
    ap.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Also write console output to this file (tee).",
    )
    ap.add_argument(
        "--workers",
        type=int,
        default=0,
        help="Parallel OCR workers (0 = auto, min(4, cpu_count())). Set 1 to disable parallelism.",
    )
    ap.add_argument(
        "--fast",
        action="store_true",
        help="Fast mode: OCR at 200 DPI instead of 300 (faster, slight quality trade-off).",
    )
    ap.add_argument(
        "--dpi",
        type=int,
        default=None,
        help="Explicit OCR DPI (overrides --fast).",
    )
    ap.add_argument(
        "--min-conf",
        type=int,
        default=LOW_CONF_WORD_THRESHOLD,
        metavar="N",
        help=f"Words with OCR confidence below N are marked as [?word?] (default: {LOW_CONF_WORD_THRESHOLD}).",
    )
    ap.add_argument(
        "--no-markers",
        dest="no_markers",
        action="store_const",
        const=True,
        default=None,
        help="Disable attention markers and AI instructions block. If omitted, prompts interactively.",
    )
    ap.add_argument(
        "--markers",
        dest="no_markers",
        action="store_const",
        const=False,
        help="Force markers ON (skip interactive prompt).",
    )
    args = ap.parse_args()

    # Make stdout safe for Windows consoles that default to cp1252.
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    # Tee: if --log-file, mirror stdout to a file.
    log_fp = None
    if args.log_file:
        try:
            log_fp = open(args.log_file, "w", encoding="utf-8")
            _original_stdout = sys.stdout

            class _Tee:
                def write(self, s):
                    _original_stdout.write(s)
                    log_fp.write(s)
                    log_fp.flush()
                def flush(self):
                    _original_stdout.flush()
                    log_fp.flush()

            sys.stdout = _Tee()
            sys.stderr = _Tee()
            print(f"Log file: {args.log_file}")
            print(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
            print(f"Inputs: {[str(p) for p in args.inputs]}")
            print()
        except Exception as e:
            print(f"[warn] Could not open log file {args.log_file}: {e}", file=sys.stderr)

    pdfs = _collect_pdfs(args.inputs, args.recursive)
    if not pdfs:
        print("No PDFs found in the given inputs.", file=sys.stderr)
        return 2

    if args.tesseract_cmd and OCR_AVAILABLE:
        pytesseract.pytesseract.tesseract_cmd = args.tesseract_cmd

    # Resolve language — prompt if not specified on the command line.
    lang = args.lang if args.lang else _prompt_language()
    print(f"Idioma OCR: {lang}")

    # Resolve markers — prompt if neither --markers nor --no-markers was given.
    if args.no_markers is None:
        add_markers = _prompt_markers()
    else:
        add_markers = not args.no_markers
    print(f"Marcadores de atencion: {'si' if add_markers else 'no'}")

    # Resolve DPI and worker count
    if args.dpi is not None:
        dpi = args.dpi
    elif args.fast:
        dpi = 200
    else:
        dpi = 300
    if args.workers and args.workers > 0:
        workers = args.workers
    else:
        cpu = os.cpu_count() or 1
        workers = max(1, min(4, cpu))

    print(f"Queued {len(pdfs)} PDF(s). Output → {args.output_dir}  (dpi={dpi}, workers={workers})")

    reports: list[CleanReport] = []
    failures: list[tuple[Path, str]] = []
    start = datetime.now()

    for i, pdf in enumerate(pdfs, start=1):
        tag = f"[{i}/{len(pdfs)}]"
        print(f"\n{tag} {pdf.name}", flush=True)
        try:
            r = process_one(
                pdf, lang, args.extra_pattern, args.output_dir, args.tessdata_dir,
                dpi=dpi, workers=workers, add_markers=add_markers, min_conf=args.min_conf,
            )
            reports.append(r)
            ocr_info = f"OCR:{r.ocr_pages}" if r.ocr_pages else "native"
            conf = f" conf={r.ocr_confidence:.1f}%" if r.ocr_confidence is not None else ""
            print(f"  OK — {r.pages}p ({ocr_info}){conf}  →  {r.clean_chars} chars", flush=True)
        except Exception as e:
            failures.append((pdf, str(e)))
            print(f"  FAIL — {e}", file=sys.stderr, flush=True)
            if not args.continue_on_error:
                break

    elapsed = (datetime.now() - start).total_seconds()
    print("\n" + "=" * 60)
    print(f"Done in {elapsed:.1f}s — {len(reports)} OK, {len(failures)} failed")
    if reports:
        total_pages = sum(r.pages for r in reports)
        total_chars = sum(r.clean_chars for r in reports)
        print(f"Totals: {total_pages} pages → {total_chars:,} clean chars")
    if failures:
        print("\nFailures:")
        for pdf, err in failures:
            print(f"  - {pdf.name}: {err}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
