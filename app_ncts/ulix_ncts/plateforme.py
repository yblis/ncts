"""Différences de plateforme (macOS et Windows) : binaires, venv, console.

Le pipeline est identique sur les deux systèmes ; ce module isole les seuls
points qui changent réellement :

* **Les binaires externes** (poppler : pdfinfo/pdftotext/pdftoppm, et tesseract).
  Sur macOS, Homebrew les place dans le PATH. Sur Windows, l'archive de poppler
  est souvent extraite dans Program Files **sans être ajoutée au PATH**, et
  tesseract s'installe dans son propre dossier : `shutil.which` échoue alors que
  l'outil est bel et bien installé. On cherche donc aussi dans les emplacements
  habituels.
* **L'interpréteur du venv** : ``.venv/bin/python3`` sur macOS,
  ``.venv\\Scripts\\python.exe`` sur Windows.
* **La console** : la console Windows est en cp850/cp1252 et n'interprète pas les
  séquences ANSI. On force UTF-8 sur les sorties et on active le traitement ANSI.
  Ce n'est pas cosmétique : un ``print`` qui échoue (caractère non encodable)
  lève une exception et fait échouer la commande, y compris la génération du PDF
  quand elle est appelée en sous-processus.
"""

from __future__ import annotations

import glob
import os
import shutil
import sys
from pathlib import Path

# binaires requis par le pipeline (poppler + tesseract)
BINAIRES = ("pdfinfo", "pdftotext", "pdftoppm", "tesseract")

# Emplacements d'installation habituels sur Windows, hors PATH. Les installateurs
# (winget, installeur .exe de tesseract, archive de poppler) n'ajoutent pas
# toujours le dossier au PATH : sans cette recherche, l'outil est « introuvable »
# alors qu'il est installé.
_DIRS_WINDOWS = (
    r"C:\Program Files\poppler\Library\bin",
    r"C:\Program Files (x86)\poppler\Library\bin",
    r"C:\poppler\Library\bin",
    r"C:\Program Files\Tesseract-OCR",
    r"C:\Program Files (x86)\Tesseract-OCR",
    r"C:\Tesseract-OCR",
)
# archives extraites manuellement : poppler-24.08.0, poppler-23.11.0…
_MOTIFS_WINDOWS = (
    r"C:\Program Files\poppler-*\Library\bin",
    r"C:\Program Files (x86)\poppler-*\Library\bin",
    r"C:\poppler-*\Library\bin",
)

_RESOLUS: dict[str, str] = {}


def est_windows() -> bool:
    return os.name == "nt"


def est_fige() -> bool:
    """Vrai quand le programme tourne depuis un exécutable PyInstaller.

    Dans ce mode il n'y a ni ``lancer.py`` ni venv : le code, reportlab et le
    gabarit sont embarqués, et poppler/tesseract peuvent être livrés dans un
    sous-dossier ``bin/`` à côté de l'exécutable.
    """
    return bool(getattr(sys, "frozen", False))


def dossier_application() -> Path:
    """Dossier du CODE : celui de l'exécutable (figé) ou ``app_ncts/`` (source).

    C'est l'équivalent du dossier de ``lancer.py`` : son parent est le dossier
    PROJET (dépôts, annonces, archive).
    """
    if est_fige():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def dossier_ressources() -> Path:
    """Dossier des fichiers embarqués (gabarit) : ``_internal`` de PyInstaller
    en mode figé, le dossier du code sinon."""
    if est_fige():
        return Path(getattr(sys, "_MEIPASS", dossier_application()))
    return dossier_application()


def dossiers_binaires_embarques() -> list[str]:
    """Sous-dossiers ``bin/`` livrés avec l'exécutable (poppler, tesseract).

    Disposition produite par ``build/construire.py`` :
    ``app/bin/poppler/`` et ``app/bin/tesseract/`` (avec ``tessdata/``).
    On les fouille aussi en mode source, pour tester la disposition sans figer.
    """
    base = dossier_application() / "bin"
    if not base.is_dir():
        return []
    out = [str(base / "poppler"), str(base / "tesseract"), str(base)]
    for extra in ("Library/bin", "poppler/Library/bin"):
        cand = base / extra
        if cand.is_dir():
            out.append(str(cand))
    return [d for d in out if Path(d).is_dir()]


def dossiers_supplementaires() -> list[str]:
    """Dossiers fouillés en plus du PATH.

    `ULIX_BINAIRES` (chemins séparés par ``os.pathsep``) permet de pointer une
    installation particulière : c'est ce que renseigne la section `binaires` de
    `config.json`, branchée sur cette variable par le lanceur.
    """
    declare = os.environ.get("ULIX_BINAIRES", "")
    out = [d.strip() for d in declare.split(os.pathsep) if d.strip()]
    # binaires livrés avec l'exécutable : ils priment sur une installation du
    # poste, pour que tous les postes travaillent avec la même version
    out = dossiers_binaires_embarques() + out
    if not est_windows():
        return out
    out += list(_DIRS_WINDOWS)
    for motif in _MOTIFS_WINDOWS:
        out += sorted(glob.glob(motif), reverse=True)
    local = os.environ.get("LOCALAPPDATA", "")
    if local:
        out += [str(Path(local) / "Programs" / "Tesseract-OCR"),
                str(Path(local) / "Programs" / "poppler" / "Library" / "bin")]
    return out


def chemin_binaire(nom: str) -> str | None:
    """Chemin absolu d'un binaire externe, ou None s'il est introuvable.

    Le résultat est mémorisé : le pipeline appelle ces binaires des dizaines de
    fois, on ne refait pas la recherche à chaque appel.
    """
    if nom in _RESOLUS:
        return _RESOLUS[nom] or None
    trouve = None
    for dossier in dossiers_binaires_embarques():
        for candidat in (Path(dossier) / f"{nom}.exe", Path(dossier) / nom):
            if candidat.is_file():
                trouve = str(candidat)
                break
        if trouve:
            break
    if not trouve:
        trouve = shutil.which(nom)
    if not trouve:
        for dossier in dossiers_supplementaires():
            for candidat in (Path(dossier) / f"{nom}.exe", Path(dossier) / nom):
                if candidat.is_file():
                    trouve = str(candidat)
                    break
            if trouve:
                break
    _RESOLUS[nom] = trouve or ""
    return trouve or None


def oublier_binaires() -> None:
    """Vide le cache (après un changement de `ULIX_BINAIRES` dans la même session)."""
    _RESOLUS.clear()


def verifier_outils(requis=BINAIRES) -> list[str]:
    return [b for b in requis if chemin_binaire(b) is None]


def chercher_python(base: Path, profondeur: int = 1) -> Path | None:
    """Interpréteur du venv du projet, selon la plateforme.

    ``.venv/bin/python3`` sur macOS, ``.venv\\Scripts\\python.exe`` sur Windows.

    Deux recherches complémentaires, parce que le venv n'est pas toujours un
    ancêtre du dossier d'où l'on part :

    1. en remontant depuis `base` (cas du venv à la racine du projet) ;
    2. dans les sous-dossiers directs de chaque niveau, pour les installations
       dont le venv est dans un dossier voisin. Dans la structure courante,
       le gabarit et le venv sont tous deux sous ``app_ncts/``.

    L'appelant valide le candidat (``import reportlab``) : prendre un venv voisin
    sans les bonnes bibliothèques ne suffit pas.
    """
    relatifs = (Path(".venv") / "bin" / "python3",
                Path(".venv") / "Scripts" / "python.exe")

    def _fichier(chemin: Path) -> bool:
        # un dossier voisin non lisible (autre compte, /home/xxx sur un serveur)
        # ne doit pas faire échouer la recherche : il n'est simplement pas le venv
        try:
            return chemin.is_file()
        except OSError:
            return False

    for depart in (base, *base.parents):
        for rel in relatifs:
            candidat = depart / rel
            if _fichier(candidat):
                return candidat
        if profondeur <= 0:
            continue
        try:
            if not depart.is_dir():
                continue
            voisins = sorted(p for p in depart.iterdir()
                             if p.is_dir() and not p.name.startswith("."))
        except OSError:
            continue
        for voisin in voisins[:profondeur * 60]:
            for rel in relatifs:
                candidat = voisin / rel
                if _fichier(candidat):
                    return candidat
    return None


def python_systeme() -> str | None:
    """Interpréteur de secours, hors venv (`python3` sur macOS, `python` sur Windows)."""
    for nom in (("python", "python3", "py") if est_windows()
                else ("python3", "python")):
        trouve = shutil.which(nom)
        if trouve:
            return trouve
    return None


def restreindre(chemin: Path) -> None:
    """Restreint un fichier à son propriétaire (droits 600).

    Sur Windows, ``chmod`` ne gère pas les droits POSIX : l'appel est sans effet
    mais reste inoffensif. Le fichier de clé y est protégé par les droits du
    profil utilisateur ; sur un poste partagé, le placer dans le dossier du
    compte reste la bonne pratique.
    """
    try:
        os.chmod(chemin, 0o600)
    except OSError:
        pass


def preparer_console() -> None:
    """Sorties en UTF-8 et codes couleur ANSI, y compris sur Windows."""
    for flux in (sys.stdout, sys.stderr):
        try:
            flux.reconfigure(encoding="utf-8", errors="replace")
        except Exception:  # flux sans reconfigure (rare) : on continue
            pass
    if est_windows():
        try:
            import ctypes
            noyau = ctypes.windll.kernel32
            # 7 = ENABLE_PROCESSED_OUTPUT | ENABLE_WRAP_AT_EOL_OUTPUT |
            #     ENABLE_VIRTUAL_TERMINAL_PROCESSING (couleurs ANSI dans cmd.exe)
            for poignee in (-11, -12):        # sortie standard, erreur standard
                noyau.SetConsoleMode(noyau.GetStdHandle(poignee), 7)
        except Exception:
            pass


def environnement_sous_processus() -> dict:
    """Environnement transmis aux sous-processus Python (gabarit de rendu).

    Forcer `PYTHONUTF8` est indispensable : le gabarit imprime des caractères
    non-Latin1 (« OK → … »). Sur une console Windows en cp1252, ce `print` lève
    une exception, le script sort en erreur et le PDF n'est jamais produit — un
    rendu qui fonctionne sur macOS échouerait donc sur Windows sans ce réglage.

    `TESSDATA_PREFIX` est déduit du binaire tesseract trouvé : certains
    installateurs Windows ne le positionnent pas, et tesseract refuse alors de
    démarrer (« Failed loading language 'eng' »).
    """
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    if est_fige():
        # PyInstaller positionne LD_LIBRARY_PATH sur ses propres bibliothèques :
        # un poppler/tesseract du système chargerait alors la mauvaise libstdc++.
        # On restitue l'environnement d'origine pour les sous-processus.
        for var in ("LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH"):
            orig = os.environ.get(var + "_ORIG")
            if orig is not None:
                env[var] = orig
            else:
                env.pop(var, None)
    if "FONTCONFIG_FILE" not in env:
        # poppler embarqué (macOS) : configuration fontconfig livrée avec lui,
        # sinon pdftoppm cherche celle de Homebrew, absente des postes clients
        fonts = dossier_application() / "bin" / "poppler" / "fonts.conf"
        if fonts.is_file():
            env["FONTCONFIG_FILE"] = str(fonts)
    if "TESSDATA_PREFIX" not in env:
        tess = chemin_binaire("tesseract")
        if tess:
            dossier = Path(tess).parent
            for cand in (dossier / "tessdata",
                         dossier.parent / "share" / "tessdata",
                         dossier.parent / "tessdata"):
                if cand.is_dir():
                    env["TESSDATA_PREFIX"] = str(cand)
                    break
    return env
