"""Guetteur de dépôts — rend l'outil transparent pour les utilisateurs.

L'utilisateur dépose ses PDF dans `data/Dépôts unique/` ou
`data/Dépôts multiple/` ; le traitement part tout seul. C'est le mode d'exploitation
documenté pour la mise en place chez les utilisateurs.

Principes retenus (et pourquoi) :

* **Stabilité avant traitement.** Un dépôt par glisser-déposer ou par le Finder
  n'est pas atomique : un gros PDF apparaît tronqué puis grossit. Traiter tout de
  suite produirait une annonce incomplète. On attend donc que la taille et la
  date de modification ne bougent plus pendant `stabilite_s` secondes.
* **Fichiers temporaires ignorés.** Le Finder, le navigateur et la messagerie
  laissent des `.part`, `.crdownload`, `.download`, `.tmp`, `~$…` : les traiter
  échouerait. On les écarte, ainsi que les fichiers cachés.
* **Lot regroupé.** Plusieurs PDF déposés dans la même fenêtre (copie multiple)
  sont traités en un seul passage : en dépôt multiple ils forment une seule
  annonce, il faut donc les voir ensemble.
* **Dépôt multiple = dépôt complet.** Les fichiers de « Dépots multiple » ne sont
  traités que lorsque le lot est stable ; un lot d'un seul fichier reste traité
  (l'utilisateur peut ne déposer qu'un complément), le rapport le signalant.
* **Aucun doublon.** Un fichier déjà traité (archivé) n'est pas retraité : les
  PDF partent dans `data/Archive/` après traitement, et le guetteur ne regarde que les
  dossiers de dépôt.
"""

from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path

# extensions et suffixes à ignorer : fichiers en cours de copie ou temporaires
SUFFIXES_TEMPORAIRES = (".part", ".crdownload", ".download", ".tmp", ".partial",
                        ".filepart", ".opdownload", ".!ut", ".swp")


def _pdf_complet(pdf: Path) -> bool:
    """Le PDF est-il complet, et pas une copie encore en cours d'écriture ?

    Un fichier tronqué s'ouvre très bien (l'en-tête ``%PDF`` est en tête) mais il
    ne contient pas le marqueur de fin ``%%EOF``. Le distinguer de la taille seule
    est indispensable : une copie réseau ou un gros fichier déposé depuis un
    partage peut marquer une pause de plusieurs secondes, et traiter ce fichier
    produirait une annonce vide — avant de l'archiver, donc de perdre le dépôt.
    """
    try:
        st = pdf.stat()
        if st.st_size < 64:
            return False
        with pdf.open("rb") as f:
            f.seek(max(0, st.st_size - 2048))
            return b"%%EOF" in f.read()
    except OSError:
        return False


def _est_pdf_stable(pdf: Path, stabilite_s: float, maintenant: float) -> bool:
    try:
        st = pdf.stat()
    except OSError:
        return False            # fichier disparu (renommé/déplacé) : on repasse
    if st.st_size == 0:
        return False            # encore vide : la copie n'a pas commencé
    return (maintenant - st.st_mtime) >= stabilite_s


def _est_pdf(pdf: Path) -> bool:
    """Filtre les PDF plausibles, y compris ceux qui n'ont pas d'extension."""
    nom = pdf.name
    if nom.startswith(".") or nom.startswith("~$"):
        return False
    if nom.lower().endswith(SUFFIXES_TEMPORAIRES):
        return False
    if pdf.suffix.lower() != ".pdf":
        return False
    try:
        with pdf.open("rb") as f:
            return f.read(5).startswith(b"%PDF")
    except OSError:
        return False


def pdf_prets(dossier: Path, stabilite_s: float = 3.0) -> list[Path]:
    """PDF déposés, terminés d'être copiés, dans l'ordre d'arrivée.

    Trois conditions : l'extension/en-tête PDF, la stabilité de la date de
    modification, ET le marqueur de fin de fichier (``%%EOF``). Ce dernier point
    est celui qui évite de traiter — donc d'archiver puis de perdre — un PDF
    encore en cours de copie depuis un partage réseau lent.
    """
    if not dossier.is_dir():
        return []
    maintenant = time.time()
    prets = [p for p in dossier.iterdir()
             if p.is_file() and _est_pdf(p) and _pdf_complet(p)
             and _est_pdf_stable(p, stabilite_s, maintenant)]
    return sorted(prets, key=lambda p: p.stat().st_mtime)


def _signature(fichiers: list[Path]) -> tuple:
    """Empreinte du lot : nom, taille et date de chaque fichier."""
    marques = []
    for f in sorted(fichiers, key=lambda x: x.name):
        try:
            st = f.stat()
            marques.append((f.name, st.st_size, st.st_mtime_ns))
        except OSError:
            marques.append((f.name, -1, -1))
    return tuple(marques)


def attendre_lot(depot_unique: Path, depot_multiple: Path, stabilite_s: float = 3.0,
                 echo=print, ignores=None) -> tuple[list[Path], list[Path], datetime]:
    """Attend qu'un lot complet soit déposé et stabilisé, puis le renvoie.

    Bloque jusqu'à ce que les deux dossiers soient stables ET que la composition
    du lot ne change plus (plusieurs fichiers copiés en parallèle arrivent dans le
    désordre). Renvoie (uniques, multiples, horodatage).
    """
    ignores = ignores or set()
    def candidats(rep):
        if not rep.is_dir():
            return []
        return sorted(p for p in rep.iterdir() if p.is_file() and not p.name.startswith(".")
                      and not p.name.startswith("~$"))

    while True:
        tous_unique, tous_multiple = candidats(depot_unique), candidats(depot_multiple)
        uniques = pdf_prets(depot_unique, stabilite_s)
        multiples = pdf_prets(depot_multiple, stabilite_s)
        # En dépôt multiple, un fichier incomplet ou temporaire bloque le lot.
        if set(tous_multiple) != set(multiples):
            multiples = []
        uniques = [p for p in uniques if (str(p), _signature([p])) not in ignores]
        if multiples and all((str(p), _signature([p])) in ignores for p in multiples):
            multiples = []
        if not uniques and not multiples:
            time.sleep(1.0)
            continue
        # le lot doit être identique d'un tour à l'autre : une copie multiple est
        # vue d'abord partiellement, il faut laisser arriver les fichiers suivants
        signature = (_signature(tous_unique), _signature(tous_multiple))
        time.sleep(max(1.0, stabilite_s / 2))
        uniques2 = pdf_prets(depot_unique, stabilite_s)
        multiples2 = pdf_prets(depot_multiple, stabilite_s)
        if (_signature(candidats(depot_unique)), _signature(candidats(depot_multiple))) != signature:
            continue            # le lot bouge encore : on attend le tour suivant
        uniques2 = [p for p in uniques2 if p in uniques]
        multiples2 = [p for p in multiples2 if p in multiples]
        if uniques2 or multiples2:
            echo(f"\n[{datetime.now():%Y-%m-%d %H:%M:%S}] dépôt détecté — "
                 f"{len(uniques2)} fichier(s) en dépôt unique, "
                 f"{len(multiples2)} en dépôt multiple")
            for f in uniques2:
                echo(f"    unique   : {f.name}")
            for f in multiples2:
                echo(f"    multiple : {f.name}")
            return uniques2, multiples2, datetime.now()
