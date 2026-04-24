"""
ocr_review.py — Post-processor: extrae palabras inciertas de archivos _limpio.txt.

Lee uno o más archivos generados por ocr_extractor.py y produce un reporte
agrupado por página con todas las palabras marcadas como [?word?], listo para
revisión humana o para alimentar un segundo paso de corrección.

Uso:
    python ocr_review.py out/mi_documento_limpio.txt
    python ocr_review.py out/*.txt
    python ocr_review.py out/ --recursive
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

PAGE_HEADER_RE = re.compile(r"=== Pagina (\d+) ===")
UNCERTAIN_WORD_RE = re.compile(r"\[\?(.+?)\?\]")


def extract_uncertain(text: str) -> dict[int, list[str]]:
    """Return {page_num: [word, ...]} for all [?word?] occurrences."""
    result: dict[int, list[str]] = {}
    current_page = 0
    for line in text.splitlines():
        m = PAGE_HEADER_RE.search(line)
        if m:
            current_page = int(m.group(1))
            continue
        for word in UNCERTAIN_WORD_RE.findall(line):
            result.setdefault(current_page, []).append(word)
    return result


def review_file(src: Path, output_dir: Path) -> tuple[int, int]:
    """Process one _limpio.txt file. Returns (pages_with_uncertain, total_uncertain)."""
    text = src.read_text(encoding="utf-8", errors="replace")
    uncertain = extract_uncertain(text)

    if not uncertain:
        print(f"  Sin palabras inciertas en {src.name}")
        return 0, 0

    total = sum(len(v) for v in uncertain.values())
    out_path = output_dir / src.name.replace("_limpio.txt", "_inciertas.txt")
    if out_path == src:
        out_path = src.with_suffix(".inciertas.txt")

    lines: list[str] = [
        f"REPORTE DE PALABRAS INCIERTAS",
        f"Archivo fuente: {src.name}",
        f"Páginas con incertidumbre: {len(uncertain)}",
        f"Total palabras inciertas: {total}",
        "=" * 60,
        "",
    ]
    for page_num in sorted(uncertain):
        words = uncertain[page_num]
        lines.append(f"--- Página {page_num} ({len(words)} palabra(s) inciertas) ---")
        # Deduplicate while preserving order
        seen: set[str] = set()
        unique: list[str] = []
        for w in words:
            if w not in seen:
                seen.add(w)
                unique.append(w)
        lines.append("  " + ",  ".join(f"[?{w}?]" for w in unique))
        lines.append("")

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  {len(uncertain)} página(s), {total} palabras inciertas  →  {out_path}")
    return len(uncertain), total


def collect_inputs(inputs: list[Path], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for p in inputs:
        if p.is_file() and p.suffix == ".txt":
            files.append(p)
        elif p.is_dir():
            pattern = "**/*_limpio.txt" if recursive else "*_limpio.txt"
            files.extend(sorted(p.glob(pattern)))
        else:
            files.extend(sorted(p.parent.glob(p.name)))
    return [f for f in files if f.is_file()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Extrae palabras inciertas de archivos _limpio.txt.")
    ap.add_argument(
        "inputs",
        type=Path,
        nargs="+",
        help="Archivos _limpio.txt, directorios, o patrones glob.",
    )
    ap.add_argument(
        "--output-dir",
        type=Path,
        default=None,
        help="Carpeta de salida para los _inciertas.txt (default: misma carpeta que el fuente).",
    )
    ap.add_argument(
        "--recursive", "-r",
        action="store_true",
        help="Busca _limpio.txt recursivamente en subdirectorios.",
    )
    args = ap.parse_args()

    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    files = collect_inputs(args.inputs, args.recursive)
    if not files:
        print("No se encontraron archivos _limpio.txt en los inputs dados.", file=sys.stderr)
        return 2

    print(f"Procesando {len(files)} archivo(s)...\n")
    total_pages = 0
    total_words = 0
    for f in files:
        out_dir = args.output_dir if args.output_dir else f.parent
        pages, words = review_file(f, out_dir)
        total_pages += pages
        total_words += words

    print(f"\nTotal: {total_pages} página(s) con incertidumbre, {total_words} palabras marcadas")
    return 0


if __name__ == "__main__":
    sys.exit(main())
