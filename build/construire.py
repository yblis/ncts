#!/usr/bin/env python3
"""Construction des paquets distribuables (Windows, macOS, Linux).

Pas une étape du pipeline métier : ce script produit l'exécutable figé
(PyInstaller, mode dossier) puis assemble le dossier « ULIX NCTS » prêt à
l'emploi, avec les dépôts vides en attente de fichiers, les lanceurs et le
`.env` initial. Il est appelé par `.github/workflows/construire.yml`, mais se
lance aussi à la main :

    cd hermes
    python3 build/construire.py --version 1.2.0                # paquet du système courant
    python3 build/construire.py --poppler DIR --tesseract DIR  # Windows : binaires livrés
    python3 build/construire.py --embarquer-brew               # macOS : poppler/tesseract Homebrew

Sorties dans `dist/` :

    Windows : ULIX-NCTS-<v>-windows-portable.zip  + ULIX-NCTS-<v>-windows-installateur.exe (Inno Setup)
    macOS   : ULIX-NCTS-<v>-macos.zip             + ULIX-NCTS-<v>-macos.pkg
    Linux   : ULIX-NCTS-<v>-linux-portable.tar.gz + ulix-ncts_<v>_amd64.deb (dépend de poppler-utils, tesseract-ocr)

Disposition livrée (identique à `hermes/` en développement) :

    ULIX NCTS/
    ├── Dépôts unique/  Dépôts multiple/  Annonces d'arrivées/  Archive/
    ├── .env (créé au premier lancement depuis app/.env.example)
    ├── Lancer.*  Surveiller.*  LISEZMOI.txt
    └── app/            <- exécutable + _internal/ (Python, reportlab, gabarit) + bin/ (poppler, tesseract)
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent       # hermes/
APP = RACINE / "app_ncts"
BUILD = RACINE / "build"
NOM = "ULIX NCTS"
BINAIRES_POPPLER = ("pdfinfo", "pdftotext", "pdftoppm")
DOSSIERS_TRAVAIL = ("Dépôts unique", "Dépôts multiple", "Annonces d'arrivées", "Archive")


def dire(msg: str) -> None:
    print(f"[construire] {msg}", flush=True)


def lancer(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    dire("$ " + " ".join(str(c) for c in cmd))
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def version_par_defaut() -> str:
    sys.path.insert(0, str(APP))
    from ulix_ncts import __version__
    return __version__


def systeme() -> str:
    return {"Windows": "windows", "Darwin": "macos", "Linux": "linux"}.get(platform.system(), "autre")


# ---------------------------------------------------------------------------
# 1. exécutable PyInstaller
# ---------------------------------------------------------------------------

def construire_executable(dist: Path) -> Path:
    travail = dist / "_pyinstaller"
    shutil.rmtree(travail, ignore_errors=True)
    lancer([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--distpath", travail / "dist", "--workpath", travail / "travail",
            BUILD / "ulix_ncts.spec"], cwd=APP)
    app = travail / "dist" / "app"
    exe = app / ("ulix-ncts.exe" if systeme() == "windows" else "ulix-ncts")
    if not exe.is_file():
        raise SystemExit(f"exécutable absent après PyInstaller : {exe}")
    return app


# ---------------------------------------------------------------------------
# 2. binaires externes (poppler, tesseract)
# ---------------------------------------------------------------------------

def copier_dossier_binaires(source: Path, cible: Path, nom: str) -> None:
    """Copie un dossier d'installation Windows (poppler `Library/bin`, `Tesseract-OCR`)."""
    source = Path(source)
    if (source / "Library" / "bin").is_dir():
        source = source / "Library" / "bin"
    if not source.is_dir():
        raise SystemExit(f"dossier {nom} introuvable : {source}")
    shutil.copytree(source, cible, dirs_exist_ok=True)
    dire(f"{nom} copié depuis {source} ({sum(1 for _ in cible.rglob('*'))} fichiers)")


def _dependances_dylib(fichier: Path) -> list[str]:
    out = subprocess.run(["otool", "-L", str(fichier)], capture_output=True, text=True, check=True).stdout
    deps = []
    for ligne in out.splitlines()[1:]:
        chemin = ligne.strip().split(" (")[0]
        if chemin and not chemin.startswith(("/usr/lib/", "/System/")):
            deps.append(chemin)
    return deps


def _resoudre_dylib(dep: str, origine: Path, prefix_brew: Path) -> Path | None:
    """Chemin réel d'une dépendance déclarée par `origine` (binaire ou dylib brew).

    Homebrew déclare la plupart des dépendances en chemin absolu ; poppler et
    quelques bibliothèques utilisent @rpath/@loader_path, résolus ici depuis
    l'emplacement d'ORIGINE du fichier (pas de la copie), puis dans les `lib`
    de Homebrew.
    """
    if dep.startswith(("@rpath/", "@loader_path/", "@executable_path/")):
        nom = dep.split("/", 1)[1]
        candidats = [origine.parent / nom, origine.parent.parent / "lib" / nom, prefix_brew / "lib" / nom]
        candidats += sorted((prefix_brew / "opt").glob(f"*/lib/{nom}"))
        for cand in candidats:
            if cand.exists():
                return cand.resolve()
        return None
    chemin = Path(dep)
    return chemin.resolve() if chemin.exists() else None


def embarquer_macos(app: Path) -> None:
    """Rend poppler et tesseract de Homebrew autonomes dans app/bin/.

    Chaque exécutable est copié avec la fermeture transitive de ses dylib
    (otool -L), les chemins sont réécrits en @executable_path/lib puis les
    fichiers sont resignés ad hoc (obligatoire sur Apple Silicon après
    install_name_tool). tessdata (eng, osd) est copié à côté de tesseract.
    """
    prefix_brew = Path(subprocess.run(["brew", "--prefix"], capture_output=True, text=True,
                                      check=True).stdout.strip())
    groupes = {"poppler": BINAIRES_POPPLER, "tesseract": ("tesseract",)}
    for groupe, noms in groupes.items():
        cible = app / "bin" / groupe
        lib = cible / "lib"
        lib.mkdir(parents=True, exist_ok=True)
        binaires = []
        for nom in noms:
            src = shutil.which(nom)
            if not src:
                raise SystemExit(f"{nom} introuvable (brew install {groupe})")
            dst = cible / nom
            shutil.copy2(Path(src).resolve(), dst)
            os.chmod(dst, 0o755)
            binaires.append(dst)
        # fermeture transitive des bibliothèques : (copie, emplacement d'origine)
        origines: dict[Path, Path] = {b: Path(shutil.which(b.name)).resolve() for b in binaires}
        a_traiter = list(binaires)
        copies: dict[str, Path] = {}
        while a_traiter:
            fichier = a_traiter.pop()
            for dep in _dependances_dylib(fichier):
                nom_dep = Path(dep).name
                if nom_dep in copies:
                    continue
                reel = _resoudre_dylib(dep, origines[fichier], prefix_brew)
                if reel is None:
                    raise SystemExit(f"bibliothèque introuvable : {dep} (depuis {fichier.name})")
                dst = lib / nom_dep
                shutil.copy2(reel, dst)
                os.chmod(dst, 0o755)
                copies[nom_dep] = dst
                origines[dst] = reel
                a_traiter.append(dst)
        # réécriture des chemins
        for fichier in binaires + list(copies.values()):
            est_binaire = fichier in binaires
            for dep in _dependances_dylib(fichier):
                nom_dep = Path(dep).name
                if nom_dep not in copies:
                    continue
                nouveau = (f"@executable_path/lib/{nom_dep}" if est_binaire else f"@loader_path/{nom_dep}")
                subprocess.run(["install_name_tool", "-change", dep, nouveau, str(fichier)],
                               check=True, capture_output=True)
            if not est_binaire:
                subprocess.run(["install_name_tool", "-id", f"@loader_path/{fichier.name}", str(fichier)],
                               check=True, capture_output=True)
            subprocess.run(["codesign", "--force", "--sign", "-", str(fichier)], check=True, capture_output=True)
        dire(f"{groupe} : {len(binaires)} exécutable(s), {len(copies)} bibliothèque(s) embarquées")

    # modèles tesseract
    tessdata_src = None
    for cand in (prefix_brew / "share" / "tessdata", prefix_brew / "opt" / "tesseract" / "share" / "tessdata"):
        if cand.is_dir():
            tessdata_src = cand
            break
    if tessdata_src is None:
        raise SystemExit("tessdata introuvable dans Homebrew")
    tessdata = app / "bin" / "tesseract" / "tessdata"
    tessdata.mkdir(parents=True, exist_ok=True)
    for nom in ("eng.traineddata", "osd.traineddata", "pdf.ttf"):
        if (tessdata_src / nom).exists():
            shutil.copy2(tessdata_src / nom, tessdata / nom)
    for sous in ("configs", "tessconfigs"):
        if (tessdata_src / sous).is_dir():
            shutil.copytree(tessdata_src / sous, tessdata / sous, dirs_exist_ok=True)
    # fontconfig : configuration minimale vers les polices système (sans Homebrew)
    fonts = app / "bin" / "poppler" / "fonts.conf"
    fonts.write_text(
        '<?xml version="1.0"?>\n<!DOCTYPE fontconfig SYSTEM "fonts.dtd">\n<fontconfig>\n'
        '  <dir>/System/Library/Fonts</dir>\n  <dir>/Library/Fonts</dir>\n  <dir>~/Library/Fonts</dir>\n'
        '  <cachedir>~/.cache/fontconfig</cachedir>\n</fontconfig>\n', encoding="utf-8")


def verifier_binaires_embarques(app: Path) -> None:
    """Chaque binaire livré doit démarrer depuis le dossier assemblé."""
    suffixe = ".exe" if systeme() == "windows" else ""
    env = dict(os.environ)
    tess = app / "bin" / "tesseract"
    if (tess / "tessdata").is_dir():
        env["TESSDATA_PREFIX"] = str(tess / "tessdata")
    if (app / "bin" / "poppler" / "fonts.conf").exists():
        env["FONTCONFIG_FILE"] = str(app / "bin" / "poppler" / "fonts.conf")
    for groupe, noms in (("poppler", BINAIRES_POPPLER), ("tesseract", ("tesseract",))):
        for nom in noms:
            exe = app / "bin" / groupe / (nom + suffixe)
            if not exe.is_file():
                raise SystemExit(f"binaire embarqué absent : {exe}")
            cp = subprocess.run([str(exe), "-v" if nom != "tesseract" else "--version"],
                                capture_output=True, text=True, env=env, timeout=60)
            sortie = (cp.stdout + cp.stderr).strip().splitlines()
            dire(f"{nom} : {sortie[0] if sortie else 'aucune sortie'}")
            if cp.returncode not in (0, 99) and not sortie:   # pdfinfo -v sort en 99
                raise SystemExit(f"{nom} ne démarre pas (code {cp.returncode})")


# ---------------------------------------------------------------------------
# 3. assemblage du dossier « ULIX NCTS »
# ---------------------------------------------------------------------------

def assembler(app_source: Path, dist: Path, os_cible: str) -> Path:
    dossier = dist / NOM
    shutil.rmtree(dossier, ignore_errors=True)
    dossier.mkdir(parents=True)
    shutil.copytree(app_source, dossier / "app", symlinks=True)
    shutil.copy2(RACINE / ".env.example", dossier / "app" / ".env.example")
    shutil.copy2(BUILD / "lanceurs" / "LISEZMOI.txt", dossier / "LISEZMOI.txt")
    lanceurs = {"windows": ("Lancer.cmd", "Surveiller.cmd", "Surveillance.cmd"),
                "macos": ("Lancer.command", "Surveiller.command"),
                "linux": ()}[os_cible]
    for nom in lanceurs:
        shutil.copy2(BUILD / "lanceurs" / nom, dossier / nom)
        os.chmod(dossier / nom, 0o755)
    if os_cible == "windows":
        # le paquet portable est autonome : dépôts vides prêts à recevoir les fichiers
        for nom in DOSSIERS_TRAVAIL:
            (dossier / nom).mkdir()
            (dossier / nom / "Déposer les PDF ici.txt").write_text(
                "Ce dossier reçoit les PDF à traiter ; ce fichier peut être supprimé.\n"
                if nom.startswith("Dépots") else
                "Dossier géré par le programme ; ce fichier peut être supprimé.\n", encoding="utf-8")
        shutil.copy2(RACINE / ".env.example", dossier / ".env")
    return dossier


# ---------------------------------------------------------------------------
# 4. paquets
# ---------------------------------------------------------------------------

def zipper(dossier: Path, cible: Path) -> None:
    with zipfile.ZipFile(cible, "w", zipfile.ZIP_DEFLATED) as z:
        for chemin in sorted(dossier.rglob("*")):
            arc = Path(dossier.name) / chemin.relative_to(dossier)
            if chemin.is_dir():
                z.writestr(str(arc) + "/", "")
            else:
                z.write(chemin, str(arc))
    dire(f"archive : {cible} ({cible.stat().st_size / 1e6:.0f} Mo)")


def paquet_windows(dossier: Path, dist: Path, version: str, exiger: bool) -> None:
    zipper(dossier, dist / f"ULIX-NCTS-{version}-windows-portable.zip")
    iscc = shutil.which("iscc") or shutil.which("ISCC")
    for cand in (r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe", r"C:\Program Files\Inno Setup 6\ISCC.exe"):
        if not iscc and Path(cand).is_file():
            iscc = cand
    if not iscc:
        msg = "Inno Setup (ISCC.exe) introuvable : installateur non produit"
        if exiger:
            raise SystemExit(msg)
        dire(msg)
        return
    lancer([iscc, f"/DVersion={version}", f"/DSource={dossier}", f"/DSortie={dist}",
            BUILD / "installateur_windows.iss"])


def paquet_macos(dossier: Path, dist: Path, version: str, exiger: bool) -> None:
    zipper(dossier, dist / f"ULIX-NCTS-{version}-macos.zip")
    if not shutil.which("pkgbuild"):
        if exiger:
            raise SystemExit("pkgbuild introuvable")
        return
    racine_pkg = dist / "_pkg_root"
    shutil.rmtree(racine_pkg, ignore_errors=True)
    shutil.copytree(dossier, racine_pkg / NOM, symlinks=True)
    scripts = dist / "_pkg_scripts"
    shutil.rmtree(scripts, ignore_errors=True)
    scripts.mkdir()
    post = scripts / "postinstall"
    post.write_text(
        "#!/bin/bash\n"
        "# Prépare le dossier de travail de l'utilisateur qui installe (~/ULIX NCTS).\n"
        "UTILISATEUR=\"${USER:-$(stat -f %Su /dev/console)}\"\n"
        "MAISON=$(dscl . -read \"/Users/$UTILISATEUR\" NFSHomeDirectory 2>/dev/null | awk '{print $2}')\n"
        "[ -n \"$MAISON\" ] || exit 0\n"
        f"sudo -u \"$UTILISATEUR\" env ULIX_PROJET=\"$MAISON/ULIX NCTS\" \"/Applications/{NOM}/app/ulix-ncts\" --preparer || true\n"
        "exit 0\n", encoding="utf-8")
    os.chmod(post, 0o755)
    pkg = dist / f"ULIX-NCTS-{version}-macos.pkg"
    lancer(["pkgbuild", "--root", racine_pkg, "--scripts", scripts,
            "--identifier", "ch.ulix.ncts", "--version", version,
            "--install-location", "/Applications", pkg])
    dire(f"paquet : {pkg}")


def paquet_linux(dossier: Path, dist: Path, version: str, exiger: bool) -> None:
    with tarfile.open(dist / f"ULIX-NCTS-{version}-linux-portable.tar.gz", "w:gz") as t:
        t.add(dossier, arcname=NOM)
    if not shutil.which("dpkg-deb"):
        if exiger:
            raise SystemExit("dpkg-deb introuvable")
        return
    version_deb = version.replace("-", "~")
    racine_deb = dist / "_deb"
    shutil.rmtree(racine_deb, ignore_errors=True)
    opt = racine_deb / "opt" / "ulix-ncts"
    shutil.copytree(dossier / "app", opt, symlinks=True)
    usr_bin = racine_deb / "usr" / "bin"
    usr_bin.mkdir(parents=True)
    shutil.copy2(BUILD / "lanceurs" / "ulix-ncts.sh", usr_bin / "ulix-ncts")
    os.chmod(usr_bin / "ulix-ncts", 0o755)
    applications = racine_deb / "usr" / "share" / "applications"
    applications.mkdir(parents=True)
    shutil.copy2(BUILD / "lanceurs" / "ulix-ncts.desktop", applications / "ulix-ncts.desktop")
    doc = racine_deb / "usr" / "share" / "doc" / "ulix-ncts"
    doc.mkdir(parents=True)
    shutil.copy2(dossier / "LISEZMOI.txt", doc / "LISEZMOI.txt")
    debian = racine_deb / "DEBIAN"
    debian.mkdir()
    taille_ko = sum(f.stat().st_size for f in racine_deb.rglob("*") if f.is_file()) // 1024
    controle = (BUILD / "deb" / "control").read_text(encoding="utf-8")
    (debian / "control").write_text(controle.replace("{VERSION}", version_deb)
                                    .replace("{TAILLE}", str(taille_ko)), encoding="utf-8")
    for nom in ("postinst",):
        src = BUILD / "deb" / nom
        if src.exists():
            shutil.copy2(src, debian / nom)
            os.chmod(debian / nom, 0o755)
    deb = dist / f"ulix-ncts_{version_deb}_amd64.deb"
    lancer(["dpkg-deb", "--build", "--root-owner-group", racine_deb, deb])
    dire(f"paquet : {deb}")


# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--version", default=None, help="version affichée (défaut : ulix_ncts.__version__)")
    ap.add_argument("--sortie", type=Path, default=RACINE / "dist", help="dossier de sortie (défaut : dist/)")
    ap.add_argument("--poppler", type=Path, help="Windows : dossier Library/bin de poppler à livrer")
    ap.add_argument("--tesseract", type=Path, help="Windows : dossier Tesseract-OCR à livrer (avec tessdata)")
    ap.add_argument("--embarquer-brew", action="store_true",
                    help="macOS : embarquer poppler/tesseract installés par Homebrew")
    ap.add_argument("--sans-paquet", action="store_true", help="assembler le dossier sans zip/installateur")
    ap.add_argument("--exiger-installateur", action="store_true",
                    help="échouer si l'outil d'installateur (ISCC, pkgbuild, dpkg-deb) manque")
    args = ap.parse_args(argv)

    os_cible = systeme()
    if os_cible == "autre":
        raise SystemExit(f"système non pris en charge : {platform.system()}")
    version = args.version or version_par_defaut()
    dist = args.sortie.resolve()
    dist.mkdir(parents=True, exist_ok=True)
    dire(f"version {version} — {os_cible} — sortie {dist}")

    app = construire_executable(dist)
    if args.poppler:
        copier_dossier_binaires(args.poppler, app / "bin" / "poppler", "poppler")
    if args.tesseract:
        copier_dossier_binaires(args.tesseract, app / "bin" / "tesseract", "tesseract")
    if args.embarquer_brew:
        if os_cible != "macos":
            raise SystemExit("--embarquer-brew n'a de sens que sur macOS")
        embarquer_macos(app)
    if (app / "bin").is_dir():
        verifier_binaires_embarques(app)

    dossier = assembler(app, dist, os_cible)
    dire(f"dossier assemblé : {dossier}")
    # l'exécutable assemblé doit au moins démarrer et trouver son gabarit
    exe = dossier / "app" / ("ulix-ncts.exe" if os_cible == "windows" else "ulix-ncts")
    essai = dist / "_essai_projet"
    shutil.rmtree(essai, ignore_errors=True)
    lancer([exe, "--projet", essai, "--preparer"])
    for nom in DOSSIERS_TRAVAIL:
        if not (essai / nom).is_dir():
            raise SystemExit(f"--preparer n'a pas créé {essai / nom}")
    if not (essai / ".env").is_file():
        raise SystemExit("--preparer n'a pas créé le .env")
    shutil.rmtree(essai, ignore_errors=True)

    if args.sans_paquet:
        return 0
    {"windows": paquet_windows, "macos": paquet_macos, "linux": paquet_linux}[os_cible](
        dossier, dist, version, args.exiger_installateur or bool(os.environ.get("CI")))
    return 0


if __name__ == "__main__":
    sys.exit(main())
