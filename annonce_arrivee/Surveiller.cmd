@echo off
rem ULIX - annonce d'arrivee NCTS : surveillance automatique des depots.
rem
rem Double-cliquer ce fichier : le programme surveille les dossiers
rem "Depots unique" et "Depots multiple". Des qu'un PDF y est depose, il est
rem traite et l'annonce d'arrivee apparait dans "Annonces d'arrivees".
rem Rien d'autre a faire : l'utilisateur n'a plus qu'a deposer ses fichiers.
rem
rem Laisser cette fenetre ouverte (elle peut rester en arriere-plan, reduite).
rem Pour arreter la surveillance : fermer la fenetre ou appuyer sur Ctrl+C.
rem
rem NOTE : fichier volontairement en ASCII sans accents (voir Installer.cmd).

setlocal
cd /d "%~dp0"

rem console en UTF-8 : sans cela, les accents francais s'affichent en charabia
chcp 65001 >nul

set PY=.venv\Scripts\python.exe
if not exist "%PY%" set PY=python

"%PY%" lancer.py --surveiller
pause
