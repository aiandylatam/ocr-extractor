# OCR Extractor

Extract clean text from native, scanned, and hybrid PDFs. Built for legal documents and reports that need to be fed into AI systems as context.

**[⬇️ Download latest release](https://github.com/aiandylatam/ocr-extractor/releases/latest)** — no Python required, just unzip and run.

---

## Features

- **Native, scanned & hybrid PDFs** — auto-detects which pages need OCR
- **Automatic cleanup** — removes electronic signatures, court seals, repeated headers/footers, watermarks, and OCR artifacts
- **Review markers** — flags tables, images, and low-confidence words for human review
- **Table recovery** — tries pdfplumber (native pages) and Tesseract PSM6 (scanned pages) before falling back to a `[TABLE]` marker
- **Auto-rotation** — corrects scanned pages with wrong orientation
- **Dark GUI** — modern interface with progress bar and real-time log
- **CLI available** — scriptable for batch automation
- **Drag & drop** — drag PDFs onto `OCR_Extractor.exe` to pre-load them

## Quick start (portable .exe)

1. Download `OCR_Extractor_vX.X.X.zip` from [Releases](https://github.com/aiandylatam/ocr-extractor/releases/latest)
2. Unzip anywhere
3. Open `OCR_Extractor.exe`
4. Add PDFs with the button or drag them onto the `.exe`
5. Click **Extract Text**

Output files are saved next to each PDF in an `out/` folder.

## Dev setup

```bash
pip install -r requirements.txt
```

Requires Tesseract installed or placed at `tesseract/tesseract.exe` next to the script.
Download: https://github.com/UB-Mannheim/tesseract/wiki

## GUI

```bash
python ocr_gui.py
```

## CLI

```bash
python ocr_extractor.py document.pdf
python ocr_extractor.py folder_with_pdfs/ --lang spa --dpi 300
python ocr_extractor.py *.pdf --lang spa+eng --min-conf 60 --no-markers
```

### CLI options

| Option | Default | Description |
|---|---|---|
| `--lang` | prompt | Tesseract language: `spa`, `eng`, `spa+eng`, etc. |
| `--dpi` | 300 | OCR resolution. 150–200 for speed, 300–400 for quality |
| `--min-conf` | 50 | Confidence threshold. Words below it are marked `[?word?]` |
| `--markers` / `--no-markers` | prompt | Toggle attention markers in output |
| `--fast` | — | Alias for `--dpi 200` |
| `--workers` | auto | Parallel OCR workers |
| `--output-dir` | `./out` | Output folder |
| `--extra-pattern` | — | Extra regex pattern to strip (repeatable) |

## Uncertainty review

```bash
python ocr_review.py out/document_clean.txt
```

Generates `out/document_uncertain.txt` with all `[?word?]` markers grouped by page.

## Build portable (PyInstaller)

```bash
pip install pyinstaller
pyinstaller --noconfirm build_portable.spec
```

Output in `dist/OCR_Extractor/` is self-contained. Copy that folder to any Windows 10/11 PC and run `OCR_Extractor.exe`.

## Output files

| File | Content |
|---|---|
| `[name]_limpio.txt` | Clean text with attention markers |
| `[name]_skill_ref.md` | Same text in Markdown format (ready for AI context) |

## Markers reference

| Marker | Meaning |
|---|---|
| `[?word?]` | Low OCR confidence — verify in original |
| `[TABLE]` | Table not captured — check structure in PDF |
| `[TABLE captured with pdfplumber]` | Table extracted as markdown |
| `[IMAGE]` | Image or graphic on page |
| `[!] LOW OCR CONFIDENCE` | Full page with poor OCR quality |

## Dependencies

```
pymupdf>=1.23
pytesseract>=0.3.10
pillow>=10.0
pdfplumber>=0.10
customtkinter>=5.2
```

---

*by Andrés M. · [@aiAndyLatam](https://github.com/aiandylatam)*
