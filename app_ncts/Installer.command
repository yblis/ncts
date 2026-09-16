#!/bin/bash
# ULIX — installation de l'environnement Python (une seule fois par poste).
#
# Double-cliquer ce fichier une fois après avoir copié le dossier sur un poste :
# il crée un environnement Python local (.venv) et y installe reportlab + Pillow,
# nécessaires à la lecture des PDF et à la génération du document.
# Aucun droit administrateur n'est requis et rien n'est installé dans le système.

cd "$(dirname "$0")" || exit 1

echo "ULIX — annonce d'arrivée NCTS : installation de l'environnement"
echo

# --- 1. binaires poppler / tesseract -----------------------------------------
MANQUANTS=""
for b in pdfinfo pdftotext pdftoppm tesseract; do
    command -v "$b" >/dev/null 2>&1 || MANQUANTS="$MANQUANTS $b"
done
if [ -n "$MANQUANTS" ]; then
    echo "Outils manquants :$MANQUANTS"
    if command -v brew >/dev/null 2>&1; then
        echo "Installation via Homebrew…"
        brew install poppler tesseract || exit 1
    else
        echo "Homebrew est introuvable."
        echo "Installez poppler et tesseract, puis relancez ce script :"
        echo "  1. https://brew.sh  (copier-coller la commande proposée dans le Terminal)"
        echo "  2. brew install poppler tesseract"
        read -r -p "Appuyez sur Entrée pour fermer…" _
        exit 1
    fi
else
    echo "Outils PDF et OCR : OK"
fi

# --- 2. environnement Python --------------------------------------------------
PY=""
for candidat in python3.12 python3.11 python3; do
    if command -v "$candidat" >/dev/null 2>&1; then PY="$candidat"; break; fi
done
if [ -z "$PY" ]; then
    echo "Python 3 est introuvable. Installez-le depuis https://www.python.org/downloads/"
    read -r -p "Appuyez sur Entrée pour fermer…" _
    exit 1
fi
echo "Python utilisé : $($PY --version)"

if [ -d .venv ] && ! .venv/bin/python -c 'import sys; assert sys.version_info >= (3, 11)' >/dev/null 2>&1; then
    mv .venv ".venv-sauvegarde-$(date +%Y%m%d-%H%M%S)" || exit 1
fi
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), "Python 3.11 minimum requis"' || exit 1
if [ ! -d .venv ]; then
    echo "Création de l'environnement local (.venv)…"
    "$PY" -m venv .venv || {
        echo "La création de l'environnement a échoué."
        read -r -p "Appuyez sur Entrée pour fermer…" _
        exit 1
    }
fi

echo "Installation des bibliothèques (reportlab, Pillow)…"
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet reportlab python-docx pillow "zxing-cpp>=2.2,<4" || {
    echo "L'installation des bibliothèques a échoué (vérifiez la connexion réseau)."
    read -r -p "Appuyez sur Entrée pour fermer…" _
    exit 1
}

echo
echo "Vérification…"
.venv/bin/python -c "import reportlab, PIL; print('reportlab et Pillow : OK')"

echo
echo "Installation terminée. Pour générer les annonces, double-cliquez sur"
echo "« Lancer.command »."
read -r -p "Appuyez sur Entrée pour fermer…" _
