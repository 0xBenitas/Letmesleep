@echo off
echo === LetMeSleep v2.0 — Build ===
echo.

:: Installe toutes les dépendances
echo Installation des dependances...
pip install -r requirements.txt
if errorlevel 1 (
    echo ERREUR : pip install a echoue.
    pause
    exit /b 1
)

echo.
echo Build en cours...
pyinstaller letmesleep.spec --clean -y

echo.
if exist "dist\LetMeSleep.exe" (
    echo OK ! L'exe est dans : dist\LetMeSleep.exe
) else (
    echo ERREUR : le build a echoue.
)
pause
