@echo off
rem ULIX - annonce d'arrivee NCTS : surveillance automatique des depots.
rem Laisser cette fenetre ouverte : deposer un PDF suffit, l'annonce se genere seule.
rem NOTE : fichier volontairement en ASCII sans accents.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
"%~dp0app\ulix-ncts.exe" --surveiller %*
echo.
echo Surveillance arretee (code %ERRORLEVEL%).
pause
