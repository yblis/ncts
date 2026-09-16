@echo off
rem ULIX - annonce d'arrivee NCTS : traitement a la demande (version installee).
rem Les PDF deposes dans "Depots unique" et "Depots multiple" sont traites et
rem les annonces apparaissent dans "Annonces d'arrivees".
rem NOTE : fichier volontairement en ASCII sans accents.
setlocal
cd /d "%~dp0"
chcp 65001 >nul
"%~dp0app\ulix-ncts.exe" %*
set CODE=%ERRORLEVEL%
echo.
if "%CODE%"=="0" (
    echo Traitement termine. Les annonces sont dans "Annonces d'arrivees".
) else (
    echo Le traitement s'est arrete avec le code %CODE% (voir le message ci-dessus).
)
pause
exit /b %CODE%
