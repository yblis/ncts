#!/bin/bash
# ULIX — annonce d'arrivée NCTS : lancement en double-clic.
#
# Double-cliquer ce fichier dans le Finder régénère les annonces d'arrivée à
# partir des PDF déposés dans « Dépots unique » et « Dépots multiple ».
# Le script utilise automatiquement l'environnement Python du dossier (.venv).

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

"$PY" lancer.py "$@"
CODE=$?

echo
if [ "$CODE" -eq 0 ]; then
    echo "Traitement terminé. Les annonces sont dans « Annonces d'arrivées »."
else
    echo "Le traitement s'est arrêté avec le code $CODE (voir le message ci-dessus)."
fi
read -r -p "Appuyez sur Entrée pour fermer…" _
exit "$CODE"
