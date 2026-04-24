@echo off
setlocal
REM OCR Extractor wrapper — runs ocr_extractor.py with local Tesseract + tessdata paths.

if "%~1"=="" (
    echo.
    echo ========================================================
    echo   OCR Extractor - USO
    echo ========================================================
    echo.
    echo Este es un script de linea de comandos, no se ejecuta con doble-click.
    echo.
    echo Opciones para usarlo:
    echo.
    echo   1^) Arrastra uno o varios PDFs sobre este archivo extract.bat
    echo      y sueltalos. Los procesara todos.
    echo.
    echo   2^) Arrastra una CARPETA completa sobre extract.bat y procesara
    echo      todos los PDFs dentro.
    echo.
    echo   3^) Abre una terminal ^(cmd o PowerShell^), ve a la carpeta
    echo      donde tienes tus PDFs, y ejecuta:
    echo         "%~f0" "mi_archivo.pdf"
    echo         "%~f0" "carpeta_con_pdfs"
    echo.
    echo Los resultados se guardan en una carpeta 'out\' junto a los PDFs.
    echo.
    pause
    exit /b 1
)

python "%~dp0ocr_extractor.py" %* --tesseract-cmd "C:\Program Files\Tesseract-OCR\tesseract.exe" --tessdata-dir "%~dp0tessdata" --log-file "%~dp0last_run.log"

set "EXITCODE=%ERRORLEVEL%"
echo.
echo ========================================================
if "%EXITCODE%"=="0" (
    echo Listo. Codigo de salida: %EXITCODE%
) else (
    echo ERROR. Codigo de salida: %EXITCODE%
)
echo Log guardado en: %~dp0last_run.log
echo ========================================================
pause
exit /b %EXITCODE%
