# PyInstaller spec — genera dist/OCR_Extractor/ (carpeta portable)
#
# Uso:
#   pip install pyinstaller
#   pyinstaller --noconfirm build_portable.spec
#
# La carpeta dist/OCR_Extractor/ es la distribución final y lista para distribuir.
# tessdata/ se incluye automáticamente si existe junto a este spec.
# Si quieres bundlear tesseract.exe también, copia la carpeta de instalación de
# Tesseract como tesseract/ junto al spec y agrégala en datas igual que tessdata.

import sys
from pathlib import Path

HERE = Path(SPECPATH)  # noqa: F821  (PyInstaller define SPECPATH en runtime)

# Archivos de datos a incluir dentro del bundle
datas = []

# tessdata si existe junto al spec
tessdata_dir = HERE / "tessdata"
if tessdata_dir.exists():
    datas.append((str(tessdata_dir), "tessdata"))

# Docs de usuario
for doc in ["INSTRUCCIONES.txt", "README.md"]:
    if (HERE / doc).exists():
        datas.append((str(HERE / doc), "."))

# customtkinter necesita sus assets (temas, imágenes)
try:
    import customtkinter
    ctk_path = Path(customtkinter.__file__).parent
    datas.append((str(ctk_path), "customtkinter"))
except ImportError:
    pass

a = Analysis(  # noqa: F821
    [str(HERE / "ocr_gui.py")],
    pathex=[str(HERE)],
    binaries=[],
    datas=datas,
    hiddenimports=[
        "ocr_extractor",
        "pytesseract",
        "PIL",
        "PIL.Image",
        "PIL.ImageOps",
        "PIL.ImageFilter",
        "fitz",
        "pdfplumber",
        "customtkinter",
        "tkinter",
        "tkinter.filedialog",
        "tkinter.messagebox",
        "concurrent.futures",
        "multiprocessing",
    ],
    hookspath=[],
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="OCR_Extractor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,          # sin ventana de consola (GUI puro)
    windowed=True,
    icon=None,              # pon aquí la ruta a un .ico si tienes
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    name="OCR_Extractor",
)
