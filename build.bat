@echo off
echo === LetMeSleep — Build ===
echo.

:: Vérifie que PyInstaller est installé
pip show pyinstaller >nul 2>&1
if errorlevel 1 (
    echo Installation de PyInstaller...
    pip install pyinstaller
)

echo.
echo Build en cours...
pyinstaller letmesleep.spec --clean -y

echo.
echo Done ! L'exe est dans : dist\LetMeSleep.exe
pause
