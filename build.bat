@echo off
echo === LetMeSleep v3.0 — Build ===
echo.

:: Installe toutes les dependances
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
    echo.
    echo ==========================================
    echo   OK ! dist\LetMeSleep.exe est pret.
    echo   Double-clic dessus et c'est parti.
    echo ==========================================
) else (
    echo ERREUR : le build a echoue.
)
pause
