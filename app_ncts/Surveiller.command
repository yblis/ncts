#!/bin/bash
# ULIX — annonce d'arrivée NCTS : surveillance automatique des dépôts.
#
# Double-cliquer ce fichier : le programme surveille les dossiers
# « data/Dépôts unique » et « data/Dépôts multiple ». Dès qu'un PDF y est
# déposé, il est traité et l'annonce apparaît dans « data/Annonces d'arrivées ».
# Rien d'autre à faire : l'utilisateur n'a plus qu'à déposer ses fichiers.
#
# Laisser cette fenêtre ouverte (elle peut rester en arrière-plan).
# Pour arrêter la surveillance : fermer la fenêtre ou appuyer sur Ctrl+C.

cd "$(dirname "$0")" || exit 1

PY=".venv/bin/python3"
if [ ! -x "$PY" ]; then
    PY="$(command -v python3)"
fi

if [ -z "$PY" ]; then
    echo "Python 3 est introuvable. Installez-le depuis https://www.python.org/downloads/"
    read -r -p "Appuyez sur Entrée pour fermer…" _
    exit 1
fi

exec "$PY" lancer.py --surveiller "$@"
