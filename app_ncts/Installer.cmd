@echo off
rem ULIX - annonce d'arrivee NCTS : installation de l'environnement Python.
rem
rem Double-cliquer ce fichier UNE FOIS apres avoir copie le dossier sur un poste
rem Windows : il cree un environnement Python local (.venv) et y installe
rem reportlab + Pillow, necessaires a la lecture des PDF et a la generation du
rem document.
rem
rem Les binaires poppler sont detectes automatiquement.
rem
rem NOTE : ce fichier est volontairement en ASCII sans accents.

setlocal enabledelayedexpansion
cd /d "%~dp0"

chcp 65001 >nul

echo ULIX - annonce d'arrivee NCTS : installation de l'environnement
echo.

rem --- 2. Detection de Python --------------------------------------------------

set "PY="

where py >nul 2>&1
if not errorlevel 1 (
    set "PY=py -3"
)

if not defined PY (
    where python >nul 2>&1
    if not errorlevel 1 (
        set "PY=python"
    )
)

if not defined PY (
    echo Python 3 est introuvable.
    echo.
    echo Installez Python puis relancez ce script :
    echo   winget install Python.Python.3.14
    echo.
    pause
    exit /b 1
)

echo Python utilise :
%PY% --version

if errorlevel 1 (
    echo.
    echo Impossible d'executer Python.
    pause
    exit /b 1
)

echo.

rem --- 3. Creation de l'environnement virtuel ---------------------------------

if not exist ".venv\Scripts\python.exe" (
    echo Creation de l'environnement local ^(.venv^)...

    %PY% -m venv ".venv"

    if errorlevel 1 (
        echo.
        echo La creation de l'environnement a echoue.
        pause
        exit /b 1
    )
) else (
    echo Environnement local .venv deja present.
)

echo.

rem --- 4. Installation / mise a jour de pip -----------------------------------

echo Mise a jour de pip...

".venv\Scripts\python.exe" -m pip install --upgrade pip

if errorlevel 1 (
    echo.
    echo La mise a jour de pip a echoue.
    pause
    exit /b 1
)

echo.

rem --- 5. Installation des bibliotheques Python -------------------------------

echo Installation des bibliotheques Python...

".venv\Scripts\python.exe" -m pip install -r requirements.txt

if errorlevel 1 (
    echo.
    echo L'installation des bibliotheques a echoue.
    echo Verifiez votre connexion reseau.
    pause
    exit /b 1
)

echo.

rem --- 6. Verification ---------------------------------------------------------

echo Verification de l'environnement...

".venv\Scripts\python.exe" -c "import reportlab, PIL, paddleocr, paddle; print('Bibliotheques Python : OK')"

if errorlevel 1 (
    echo.
    echo Une ou plusieurs bibliotheques Python ne fonctionnent pas.
    pause
    exit /b 1
)

".venv\Scripts\python.exe" -m ulix_ncts.ocr_paddle
if errorlevel 1 (
    echo Preparation PaddleOCR en echec.
    pause
    exit /b 1
)

rem Use the same discovery logic as the application, including config.json.
".venv\Scripts\python.exe" -c "import lancer; c=lancer.cfgmod.charger(lancer.RACINE); lancer._brancher_binaires(c); e=lancer.verifier_environnement(c); print('\n'.join(e) if e else 'Environnement : OK'); raise SystemExit(bool(e))"
if errorlevel 1 (
    echo Installation incomplete. Verifiez poppler, PaddleOCR et config.json.
    echo Poppler : winget install -e --id oschwartz10612.Poppler
    pause
    exit /b 1
)

echo.
echo ============================================================
echo Installation terminee avec succes.
echo ============================================================
echo.
echo Il reste a renseigner la cle du modele IA, une fois par poste :
echo.
echo     .venv\Scripts\python.exe lancer.py --cle-ia VOTRE_CLE
echo.
echo Pour utiliser l'outil, double-cliquez sur :
echo.
echo     Surveiller.cmd
echo.
echo Deposez ensuite un PDF dans le dossier surveille.
echo.

pause
endlocal
