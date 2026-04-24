# OCR Extractor

Extrae texto limpio de PDFs nativos, escaneados e híbridos. Diseñado para documentos legales y expedientes que se cargarán como contexto en sistemas de IA.

## Características

- **PDF nativo, escaneado e híbrido** — detecta automáticamente qué páginas necesitan OCR
- **Limpieza automática** — elimina firmas electrónicas, sellos, encabezados repetidos, marcas de agua y artefactos de OCR
- **Marcadores de revisión** — señala tablas, imágenes y palabras de baja confianza para revisión humana
- **Recuperación de tablas** — intenta extraer tablas con pdfplumber (páginas nativas) y Tesseract PSM6 (páginas escaneadas) antes de dejar un marcador `[TABLA]`
- **Auto-rotación** — corrige páginas escaneadas con orientación incorrecta
- **Bloque de instrucciones para IA** — cada archivo incluye un encabezado que advierte al modelo sobre secciones que pueden requerir verificación en el original
- **Interfaz gráfica** — GUI moderna con barra de progreso y log en tiempo real
- **CLI disponible** — también operable desde línea de comandos para automatización

## Estructura del proyecto

```
ocr_tool/
  ocr_gui.py            — Interfaz gráfica (entry point)
  ocr_extractor.py      — Backend CLI y lógica de extracción
  ocr_review.py         — Post-procesador: reportes de palabras inciertas
  tessdata/             — Modelos de idioma para Tesseract
    spa.traineddata
    eng.traineddata
    osd.traineddata
  requirements.txt      — Dependencias Python
  build_portable.spec   — Spec de PyInstaller para build portable
  extract.bat           — Wrapper CLI para Windows (drag & drop)
```

## Instalación (modo desarrollo)

```bash
pip install -r requirements.txt
```

Requiere Tesseract instalado en el sistema o en `tesseract/tesseract.exe` junto al script.
Descarga: https://github.com/UB-Mannheim/tesseract/wiki

## Uso — GUI

```bash
python ocr_gui.py
```

## Uso — CLI

```bash
python ocr_extractor.py documento.pdf
python ocr_extractor.py carpeta_con_pdfs/ --lang spa --dpi 300
python ocr_extractor.py *.pdf --lang spa+eng --min-conf 60 --no-markers
```

### Opciones CLI principales

| Opción | Default | Descripción |
|---|---|---|
| `--lang` | prompt | Idioma Tesseract: `spa`, `eng`, `spa+eng`, etc. |
| `--dpi` | 300 | Resolución OCR. 150–200 para velocidad, 300–400 para calidad |
| `--min-conf` | 50 | Umbral de confianza. Palabras por debajo quedan como `[?word?]` |
| `--markers` | prompt | Activa marcadores de atención en el texto |
| `--no-markers` | — | Desactiva marcadores |
| `--fast` | — | Alias para `--dpi 200` |
| `--workers` | auto | Workers paralelos para OCR (0 = auto) |
| `--output-dir` | `./out` | Carpeta de salida |
| `--extra-pattern` | — | Regex adicional a eliminar (repetible) |

## Revisión de palabras inciertas

```bash
python ocr_review.py out/documento_limpio.txt
```

Genera `out/documento_inciertas.txt` con todas las palabras marcadas como `[?word?]` agrupadas por página.

## Build portable (sin instalar Python)

```bash
pip install pyinstaller
pyinstaller build_portable.spec
```

El resultado en `dist/OCR_Extractor/` es autocontenido. Copia esa carpeta a cualquier PC con Windows 10/11 y ejecuta `OCR_Extractor.exe`.

Para incluir Tesseract en el bundle: copia la carpeta de instalación de Tesseract como `tesseract/` junto a `build_portable.spec` antes del build.

## Archivos generados por extracción

| Archivo | Contenido |
|---|---|
| `[nombre]_limpio.txt` | Texto limpio con marcadores de atención |
| `[nombre]_skill_ref.md` | Mismo texto en formato Markdown para contexto de IA |

## Marcadores en el texto de salida

| Marcador | Significado |
|---|---|
| `[?palabra?]` | Palabra con confianza OCR baja — verificar en original |
| `[TABLA]` | Tabla no capturada — revisar estructura en PDF |
| `[TABLA capturada con pdfplumber]` | Tabla extraída como markdown |
| `[IMAGEN]` | Imagen o gráfico en la página |
| `[!] CONFIANZA OCR BAJA` | Página completa con OCR de baja calidad |

## Dependencias

```
pymupdf>=1.23
pytesseract>=0.3.10
pillow>=10.0
pdfplumber>=0.10
customtkinter>=5.2
```
