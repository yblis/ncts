"""Accès disque robuste : normalisation Unicode et insensibilité aux accents.

Deux pièges rencontrés sur macOS :

1. Le système de fichiers stocke les noms en NFD (formes décomposées) : un
   chemin écrit en NFC (« Dépôts ») peut ne pas exister vu de Python alors que
   ``ls`` l'affiche normalement.
2. Les dossiers de dépôt sont renommés à la main par les utilisateurs : les
   accents varient (« Dépots unique », « Dépôts unique », « Depots unique »).

``resoudre()`` essaie donc, pour chaque composant du chemin : la forme exacte,
puis NFD/NFC, puis une comparaison insensible aux accents et à la casse.
"""

from __future__ import annotations

import os
import unicodedata
from pathlib import Path


def cle(nom: str) -> str:
    """Clé de comparaison : sans accents, sans casse, espaces normalisés."""
    n = unicodedata.normalize("NFD", str(nom))
    n = "".join(c for c in n if unicodedata.category(c) != "Mn")
    return " ".join(n.casefold().split())


def _variantes(nom: str) -> list[str]:
    variantes = [nom]
    for forme in ("NFD", "NFC"):
        n = unicodedata.normalize(forme, nom)
        if n not in variantes:
            variantes.append(n)
    return variantes


def _chercher_dans(parent: Path, nom: str) -> Path | None:
    """Retrouve un enfant de `parent` dont le nom équivaut à `nom`."""
    if not parent.is_dir():
        return None
    cible = cle(nom)
    for enfant in parent.iterdir():
        if cle(enfant.name) == cible:
            return enfant
    return None


def resoudre(base: Path, nom_ou_chemin: str | Path) -> Path:
    """Résout un chemin (absolu ou relatif à `base`) en tolérant NFD et accents."""
    p = Path(nom_ou_chemin).expanduser()
    if not p.is_absolute():
        p = base / p
    p = Path(os.path.normpath(str(p)))       # supprime les « .. » internes
    if p.exists():
        return p
    courant = Path(p.anchor) if p.is_absolute() else Path()
    for partie in (p.parts[1:] if p.is_absolute() else p.parts):
        if partie in ("", "."):
            continue
        candidat = courant / partie
        if candidat.exists():
            courant = candidat
            continue
        trouve = next((courant / v for v in _variantes(partie)
                       if (courant / v).exists()), None)
        courant = trouve or _chercher_dans(courant, partie) or candidat
    return courant


def dossier(base: Path, nom: str | Path, creer: bool = False) -> Path:
    """Résout (et crée au besoin) un dossier de travail."""
    p = resoudre(base, nom)
    if creer:
        p.mkdir(parents=True, exist_ok=True)
    return p
