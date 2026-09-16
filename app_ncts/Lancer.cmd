@echo off
rem ULIX - annonce d'arrivee NCTS : traitement a la demande.
rem
rem Double-cliquer ce fichier : les PDF deposes dans "Depots unique" et
rem "Depots multiple" sont traites et les annonces d'arrivee apparaissent dans
rem "Annonces d'arrivees".
rem
rem Pour le mode automatique (deposer un fichier suffit), utiliser Surveiller.cmd.
rem
rem NOTE : fichier volontairement en ASCII sans accents (voir Installer.cmd).

setlocal
cd /d "%~dp0"

rem console en UTF-8 : sans cela, les accents francais s'affichent en charabia
chcp 65001 >nul

set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

"%PY%" lancer.py %*
set CODE=%ERRORLEVEL%

echo.
if "%CODE%"=="0" (
    echo Traitement termine. Les annonces sont dans "Annonces d'arrivees".
) else (
    echo Le traitement s'est arrete avec le code %CODE% (voir le message ci-dessus).
)
pause
exit /b %CODE%
