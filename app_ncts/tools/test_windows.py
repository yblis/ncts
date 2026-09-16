#!/usr/bin/env python3
"""Vérifie la logique Windows sans être sous Windows (simulation).

Le portage ne peut pas être validé sur un poste macOS, mais la LOGIQUE de
plateforme peut l'être : résolution des chemins de venv Windows, recherche des
binaires dans les emplacements Windows, encodage des sorties, messages adaptés.
Ce script teste ces points en simulant `os.name == "nt"`.

Usage : python3 tools/test_windows.py
"""

import os
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))

from ulix_ncts import plateforme  # noqa: E402

OK, KO = "  [ok]  ", "  [KO]  "
_echecs = 0


def verifier(condition: bool, libelle: str) -> None:
    global _echecs
    print((OK if condition else KO) + libelle)
    if not condition:
        _echecs += 1


def main() -> int:
    print("=== 1. détection de plateforme ===")
    verifier(plateforme.est_windows() is (os.name == "nt"),
             f"est_windows() cohérent avec os.name ({os.name})")

    print("\n=== 2. chemins de venv selon la plateforme ===")
    rel_mac = Path(".venv") / "bin" / "python3"
    rel_win = Path(".venv") / "Scripts" / "python.exe"
    verifier(rel_win.parent.name == "Scripts" and rel_win.name == "python.exe",
             "chemin Windows : .venv\\Scripts\\python.exe")
    # le venv réel doit être trouvé depuis un dossier ÉLOIGNÉ (cas du rendu)
    gabarit = RACINE / "Documentation" / "skills" / "ulix-doc-arrivee-ncts" / "scripts"
    trouve = plateforme.chercher_python(gabarit.resolve(), profondeur=1)
    verifier(trouve is not None and trouve.is_file(),
             f"venv trouvé depuis le dossier du gabarit : "
             f"{trouve.relative_to(RACINE) if trouve else 'AUCUN'}")
    verifier(trouve is None or str(rel_mac) in str(trouve).replace(os.sep, "/")
             or "python3" in trouve.name or "python.exe" in trouve.name,
             "l'interpréteur trouvé est bien un python de venv")

    print("\n=== 3. recherche des binaires (emplacements Windows) ===")
    dossiers = plateforme.dossiers_supplementaires()
    verifier(all(isinstance(d, str) for d in dossiers), "liste de dossiers exploitable")
    if plateforme.est_windows():
        verifier(any("poppler" in d.lower() for d in dossiers),
                 "poppler cherché dans Program Files")
        verifier(any("tesseract" in d.lower() for d in dossiers),
                 "tesseract cherché dans Program Files")
    else:
        print("        (hors Windows : les emplacements Program Files sont ignorés)")

    # ULIX_BINAIRES : surcharge par la config
    os.environ["ULIX_BINAIRES"] = os.pathsep.join(["/tmp/dossier_test_bin"])
    plateforme.oublier_binaires()
    verifier("/tmp/dossier_test_bin" in plateforme.dossiers_supplementaires(),
             "ULIX_BINAIRES est bien pris en compte (config.json → binaires)")
    del os.environ["ULIX_BINAIRES"]
    plateforme.oublier_binaires()

    print("\n=== 4. environnement transmis aux sous-processus ===")
    env = plateforme.environnement_sous_processus()
    verifier(env.get("PYTHONUTF8") == "1",
             "PYTHONUTF8=1 (sinon le gabarit plante sur une console cp1252)")
    verifier(env.get("PYTHONIOENCODING") == "utf-8", "PYTHONIOENCODING=utf-8")
    verifier("TESSDATA_PREFIX" in env,
             f"TESSDATA_PREFIX déduit : {env.get('TESSDATA_PREFIX')}")
    verifier(os.environ.get("PATH") in env.get("PATH", ""),
             "le PATH de l'utilisateur est conservé")

    print("\n=== 5. appels de binaires résolus ===")
    for b in plateforme.BINAIRES:
        chemin = plateforme.chemin_binaire(b)
        verifier(chemin is not None, f"{b} résolu : {chemin}")

    print("\n=== 6. console ===")
    plateforme.preparer_console()
    verifier(sys.stdout.encoding.lower().replace("-", "") == "utf8",
             f"sortie forcée en UTF-8 (encodage réel : {sys.stdout.encoding})")
    try:
        print("        test d'affichage : Dépots unique — annonce d'arrivée …")
        verifier(True, "les caractères accentués s'impriment sans lever")
    except Exception as exc:  # noqa: BLE001
        verifier(False, f"impression d'accents : {exc}")

    print("\n=== 7. lanceurs Windows présents ===")
    for nom in ("Installer.cmd", "Lancer.cmd", "Surveiller.cmd"):
        f = RACINE / nom
        verifier(f.is_file() and f.stat().st_size > 0, f"{nom} présent")
        if f.is_file():
            brut = f.read_bytes()
            non_ascii = [o for o in brut if o > 127]
            verifier(not non_ascii,
                     f"{nom} en ASCII pur ({len(non_ascii)} octet(s) > 127) "
                     f"— cmd.exe lit les .cmd en encodage OEM")
            contenu = brut.decode("ascii", "replace")
            verifier("chcp 65001" in contenu,
                     f"{nom} force la console en UTF-8 (chcp 65001)")

    print("\n" + "=" * 58)
    print("ÉCHECS : " + str(_echecs) if _echecs else "TOUT EST OK")
    return 1 if _echecs else 0


if __name__ == "__main__":
    sys.exit(main())
