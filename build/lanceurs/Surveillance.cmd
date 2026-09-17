@echo off
rem ULIX - annonce d'arrivee NCTS : surveillance des depots EN ARRIERE-PLAN.
rem
rem   Surveillance.cmd                 demarre la surveillance (fenetre invisible)
rem   Surveillance.cmd --cargowise     idem, options transmises au programme
rem   Surveillance.cmd --kill          arrete la surveillance
rem   Surveillance.cmd --statut        indique si elle tourne
rem   Surveillance.cmd --journal       affiche la fin du journal
rem
rem Le journal est ecrit dans Surveillance.log, l'identifiant du processus dans
rem Surveillance.pid. Pour une fenetre visible, utiliser Surveiller.cmd.
rem
rem NOTE : fichier volontairement en ASCII sans accents (voir Installer.cmd).

setlocal
cd /d "%~dp0"
set "EXE=%~dp0app\ulix-ncts.exe"
set "PIDF=%~dp0Surveillance.pid"
set "LOG=%~dp0Surveillance.log"

if /i "%~1"=="--kill"    goto :kill
if /i "%~1"=="--stop"    goto :kill
if /i "%~1"=="--statut"  goto :statut
if /i "%~1"=="--status"  goto :statut
if /i "%~1"=="--journal" goto :journal
if /i "%~1"=="--log"     goto :journal
if /i "%~1"=="--aide"    goto :aide
if /i "%~1"=="--help"    goto :aide
if /i "%~1"=="-h"        goto :aide
goto :demarrer

:demarrer
if not exist "%EXE%" (
    echo Programme introuvable : %EXE%
    exit /b 1
)
call :actif && (
    echo La surveillance tourne deja ^(PID %PID%^). Utiliser --kill pour l'arreter.
    exit /b 0
)
rem Start-Process : fenetre cachee, sortie redirigee vers le journal, PID conserve.
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$p = Start-Process -FilePath '%EXE%' -ArgumentList '--surveiller --sans-couleur %*' -WorkingDirectory '%~dp0.' -WindowStyle Hidden -RedirectStandardOutput '%LOG%' -RedirectStandardError '%~dp0Surveillance.err.log' -PassThru; [IO.File]::WriteAllText('%PIDF%', [string]$p.Id); Write-Host ('Surveillance demarree en arriere-plan (PID ' + $p.Id + ').')"
if errorlevel 1 (
    echo Echec du demarrage.
    exit /b 1
)
echo Journal : %LOG%
echo Arreter : %~nx0 --kill
exit /b 0

:kill
call :actif || (
    echo Aucune surveillance en cours.
    if exist "%PIDF%" del "%PIDF%"
    exit /b 0
)
rem /t arrete aussi le rendu du gabarit lance par le programme lui-meme.
taskkill /pid %PID% /t /f >nul 2>&1
if errorlevel 1 (
    echo Impossible d'arreter le processus %PID%.
    exit /b 1
)
del "%PIDF%" >nul 2>&1
echo Surveillance arretee ^(PID %PID%^).
exit /b 0

:statut
call :actif && (
    echo Surveillance active ^(PID %PID%^). Journal : %LOG%
    exit /b 0
)
echo Surveillance arretee.
exit /b 3

:journal
if not exist "%LOG%" (
    echo Aucun journal ^(%LOG%^).
    exit /b 0
)
powershell -NoProfile -Command "Get-Content -Tail 40 '%LOG%'"
exit /b 0

:aide
for /f "tokens=* delims=" %%L in ('findstr /b "rem   " "%~f0"') do echo %%L
exit /b 0

rem --- le processus du PID enregistre existe-t-il encore et est-ce bien le notre ?
:actif
set "PID="
if not exist "%PIDF%" exit /b 1
set /p PID=<"%PIDF%"
if "%PID%"=="" exit /b 1
tasklist /fi "PID eq %PID%" /fi "IMAGENAME eq ulix-ncts.exe" 2>nul | find /i "ulix-ncts.exe" >nul
exit /b %errorlevel%
