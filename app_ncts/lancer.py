#!/usr/bin/env python3
"""Annonce d'arrivée NCTS — génération depuis les PDF déposés.

Le script scanne « Dépots unique » et « Dépots multiple » (à côté de ce
fichier), classe les pages des PDF, lit les documents de transit et produit les
annonces d'arrivée (PDF 2 pages : annonce + liste d'inventaire, cadre CONTRÔLE
3140) dans « Annonces d'arrivées ».

Règle métier :
  * Dépots unique   : 1 fichier PDF  -> 1 annonce d'arrivée ;
  * Dépots multiple : N fichiers PDF -> 1 annonce d'arrivée unique.

Usage :
    python3 lancer.py                 # traite les deux dépôts
    python3 lancer.py --unique        # seulement « Dépots unique »
    python3 lancer.py --multiple      # seulement « Dépots multiple »
    python3 lancer.py --simulation    # analyse tout, n'écrit aucun PDF
    python3 lancer.py --garder        # ne pas déplacer les PDF traités
    python3 lancer.py --cargowise     # active l'enrichissement via le MCP CargoWise
    python3 lancer.py --depot-unique <dossier> ...   # chemins explicites

Ce script ne fait que des lectures ; le seul écrit est la génération des PDF
dans le dossier de sortie (et l'archivage des PDF traités dans « Archive/ »
sauf option --garder ou config trait.  deplacer_traite=false).

Rendu : le PDF est produit par le script déterministe du skill ULIX
(Documentation/skills/ulix-doc-arrivee-ncts/scripts/generate_doc.py) — gabarit
figé, aucun rendu improvisé.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

# Dossier du CODE. En exécutable figé (PyInstaller, voir build/), il n'y a pas de
# lancer.py : c'est le dossier de l'exécutable, et son parent reste le PROJET.
if getattr(sys, "frozen", False):
    RACINE = Path(sys.executable).resolve().parent
else:
    RACINE = Path(__file__).resolve().parent
    sys.path.insert(0, str(RACINE))

from ulix_ncts import config as cfgmod          # noqa: E402
from ulix_ncts import pdfio, pipeline, render    # noqa: E402
from ulix_ncts import ia, plateforme            # noqa: E402

VERT, ROUGE, JAUNE, GRIS, RAZ = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[0m"


def _commande() -> str:
    """Commande à afficher à l'utilisateur, adaptée à sa plateforme.

    Sur Windows, `python3` n'existe pas (le lanceur s'appelle `python` ou `py`) :
    afficher « python3 lancer.py » enverrait l'utilisateur dans le mur.
    """
    if plateforme.est_fige():
        return Path(sys.executable).name
    if plateforme.est_windows():
        return "python lancer.py"
    return "python3 lancer.py"


def _brancher_binaires(cfg: dict) -> None:
    """Renseigne `ULIX_BINAIRES` depuis la config (dossiers de poppler/tesseract).

    Sur Windows, ces outils sont souvent installés hors du PATH (archive extraite
    dans Program Files). Le lanceur transmet donc les dossiers déclarés avant que
    `plateforme` ne résolve les binaires : la recherche tient compte de la config
    de l'utilisateur, pas seulement des emplacements supposés.
    """
    dossiers = cfg.get("binaires") or []
    if isinstance(dossiers, str):
        dossiers = [dossiers]
    if dossiers:
        import os as _os
        _os.environ["ULIX_BINAIRES"] = _os.pathsep.join(str(d) for d in dossiers)
        plateforme.oublier_binaires()


def _couleur(actif: bool = True) -> None:
    if not actif:
        global VERT, ROUGE, JAUNE, GRIS, RAZ
        VERT = ROUGE = JAUNE = GRIS = RAZ = ""


def verifier_environnement(cfg: dict) -> list[str]:
    """Contrôles pré-vol : binaires PDF/OCR et script de rendu."""
    problemes = []
    manquants = pdfio.verifier_outils()
    if manquants:
        if plateforme.est_windows():
            remede = ("installer poppler et tesseract, puis renseigner leurs dossiers "
                      "dans config.json (section « binaires ») ou dans la variable "
                      "ULIX_BINAIRES — voir INSTALLATION-WINDOWS.md")
        else:
            remede = "installer poppler et tesseract, ex. `brew install poppler tesseract`"
        problemes.append("binaires absents : " + ", ".join(manquants) + "  (" + remede + ")")
    try:
        import reportlab  # noqa: F401
    except Exception:
        python_venv = plateforme.chercher_python(RACINE)
        if python_venv:
            try:
                subprocess.run([str(python_venv), "-c", "import reportlab"],
                               check=True, capture_output=True,
                               env=plateforme.environnement_sous_processus())
            except Exception:
                problemes.append("reportlab absent dans .venv "
                                 + ("(relancer Installer.cmd)" if plateforme.est_windows()
                                    else "(relancer installer.command)"))
        else:
            problemes.append("reportlab absent — lancer "
                             + ("Installer.cmd" if plateforme.est_windows()
                                else "installer.command")
                             + " (ou `pip install reportlab pillow`)")
    if not render.trouver_gabarit(RACINE) and not plateforme.est_fige():
        problemes.append("generate_doc.py (gabarit ULIX) introuvable — vérifier que "
                         "le dossier Documentation/ est bien présent dans app_ncts/")
    elif not render.trouver_gabarit(RACINE):
        problemes.append("gabarit generate_doc.py absent de l'exécutable — reconstruire "
                         "le paquet (build/construire.py)")
    return problemes


def _rendu_gabarit(arguments: list[str]) -> int:
    """Exécute generate_doc.py dans ce processus (exécutable figé).

    L'exécutable se relance lui-même avec ``--rendu-gabarit GABARIT JSON SORTIE``
    depuis `render.generer` : le gabarit tourne alors avec le reportlab embarqué,
    exactement comme s'il était appelé par un interpréteur. Aucun autre chemin
    de rendu n'est introduit.
    """
    import runpy
    if len(arguments) != 3:
        print("usage interne : --rendu-gabarit GABARIT DATA.json SORTIE.pdf")
        return 1
    gabarit, entree, sortie = arguments
    sys.argv = [gabarit, entree, sortie]
    try:
        runpy.run_path(gabarit, run_name="__main__")
    except SystemExit as exc:
        return int(exc.code or 0) if isinstance(exc.code, int) or exc.code is None else 1
    return 0


def preparer_projet(cfg: dict, racine: Path, echo=None) -> list[str]:
    """Crée les dossiers de travail manquants et le `.env` initial.

    Après installation, l'utilisateur trouve ainsi les dépôts prêts à recevoir
    des fichiers sans rien créer à la main. Le `.env` n'est écrit que s'il
    n'existe pas, à partir de `.env.example` (livré à côté du code).
    """
    faits = []
    for cle in ("depot_unique", "depot_multiple", "sortie", "archive"):
        dossier = Path(cfg["dossiers"][cle])
        if not dossier.exists():
            try:
                dossier.mkdir(parents=True, exist_ok=True)
                faits.append(f"dossier créé : {dossier}")
            except OSError as exc:
                faits.append(f"dossier non créé : {dossier} ({exc})")
    projet = Path(cfg["_projet"])
    env = projet / cfgmod.NOM_ENV
    if not env.exists():
        for modele in (racine / ".env.example", projet / ".env.example",
                       racine.parent / ".env.example"):
            if modele.is_file():
                try:
                    shutil.copyfile(modele, env)
                    faits.append(f"fichier créé : {env} (à compléter : clé IA)")
                except OSError as exc:
                    faits.append(f"fichier non créé : {env} ({exc})")
                break
    if echo:
        for f in faits:
            echo(f"  {f}")
    return faits


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] == "--rendu-gabarit":
        return _rendu_gabarit(argv[1:])
    ap = argparse.ArgumentParser(
        description="Génère les annonces d'arrivée NCTS à partir des PDF déposés.",
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--unique", action="store_true", help="traiter seulement « Dépots unique »")
    ap.add_argument("--multiple", action="store_true", help="traiter seulement « Dépots multiple »")
    ap.add_argument("--simulation", "--dry-run", dest="simulation", action="store_true",
                    help="analyser sans écrire de PDF ni archiver")
    ap.add_argument("--garder", action="store_true",
                    help="ne pas déplacer les PDF traités dans Archive/")
    ap.add_argument("--surveiller", action="store_true",
                    help="guetter les dépôts et traiter chaque lot automatiquement "
                         "(mode transparent : l'utilisateur dépose, tout part seul)")
    ap.add_argument("--une-fois", action="store_true",
                    help="avec --surveiller : traiter le lot présent puis quitter")
    ap.add_argument("--cargowise", action="store_true",
                    help="interroger le serveur MCP CargoWise (DM, date d'arrivée, dossier)")
    ap.add_argument("--autoriser", action="store_true",
                    help="ouvrir le navigateur pour autoriser l'accès OAuth au MCP CargoWise")
    ap.add_argument("--nouveau-client", action="store_true",
                    help="avec --autoriser : réenregistrer le client OAuth")
    ap.add_argument("--nct", action="append", default=[],
                    help="clé de déclaration NCT… à interroger dans CargoWise "
                         "(répétable ; à défaut, la clé est reprise du nom de fichier)")
    ap.add_argument("--statut-cargowise", action="store_true",
                    help="vérifier la connexion et l'autorisation CargoWise, puis quitter")
    ap.add_argument("--cle-cargowise", default="",
                    help="clé de déclaration à utiliser pour le diagnostic "
                         "--statut-cargowise (ou fournir --nct)")
    ap.add_argument("--cle-ia", default="",
                    help="enregistrer la clé du modèle IA dans le fichier privé du "
                         "poste (fichier privé de l'utilisateur, droits 600), puis quitter")
    ap.add_argument("--statut-ia", action="store_true",
                    help="vérifier l'accès au modèle IA, puis quitter")
    ap.add_argument("--projet", type=Path,
                    help="dossier PROJET contenant les dépôts, les annonces et l'archive "
                         "(défaut : variable ULIX_PROJET, sinon le parent du programme)")
    ap.add_argument("--preparer", action="store_true",
                    help="créer les dossiers de dépôt et le fichier .env s'ils manquent, puis quitter")
    ap.add_argument("--depot-unique", type=Path, help="dossier du dépôt unique")
    ap.add_argument("--depot-multiple", type=Path, help="dossier du dépôt multiple")
    ap.add_argument("--sortie", type=Path, help="dossier des annonces générées")
    ap.add_argument("--sans-couleur", action="store_true", help="sortie sans codes couleur")
    ap.add_argument("--format", choices=["docx", "pdf"], help="format de sortie (Word par défaut)")
    args = ap.parse_args(argv)

    plateforme.preparer_console()
    _couleur(sys.stdout.isatty() and not args.sans_couleur)

    projet = args.projet or (Path(os.environ["ULIX_PROJET"]) if os.environ.get("ULIX_PROJET") else None)
    projet = projet.expanduser().resolve() if projet else RACINE.parent
    # .env du poste (clé Ollama, modèle IA…) : PROJET d'abord, puis dossier du code
    cfgmod.charger_env(projet, RACINE)
    cfg = cfgmod.charger(RACINE, projet)
    if args.format:
        cfg["document"]["format_sortie"] = args.format
    _brancher_binaires(cfg)
    if args.depot_unique:
        cfg["dossiers"]["depot_unique"] = str(args.depot_unique.expanduser().resolve())
    if args.depot_multiple:
        cfg["dossiers"]["depot_multiple"] = str(args.depot_multiple.expanduser().resolve())
    if args.sortie:
        cfg["dossiers"]["sortie"] = str(args.sortie.expanduser().resolve())
    if args.garder or args.simulation:
        cfg["traitement"]["deplacer_traite"] = False
    if args.cargowise or args.autoriser or args.statut_cargowise or args.nct:
        cfg["cargowise"]["active"] = True
    if args.autoriser:
        cfg["cargowise"]["autorisation_interactive"] = True

    # --- dossiers de travail prêts à recevoir les dépôts -----------------------
    faits = preparer_projet(cfg, RACINE)
    if args.preparer:
        print(f"{GRIS}ULIX — annonce d'arrivée NCTS : préparation du dossier projet{RAZ}")
        print(f"  projet : {cfg['_projet']}")
        for f in faits:
            print(f"  {f}")
        if not faits:
            print("  rien à faire : dossiers et .env déjà en place")
        return 0

    # --- autorisation OAuth / diagnostic CargoWise, avant tout traitement ----
    if args.autoriser:
        from ulix_ncts import cw_client
        ok, message = cw_client.autoriser_maintenant(cfg, nouveau_client=args.nouveau_client)
        print((f"{VERT}{message}{RAZ}" if ok else f"{ROUGE}{message}{RAZ}"))
        return 0 if ok else 5
    if args.statut_cargowise:
        from ulix_ncts import cw_client
        # Le diagnostic ne doit pas interroger un dossier codé en dur.
        cle = args.cle_cargowise or (args.nct[0] if args.nct else "")
        if not cle:
            ap.error("--statut-cargowise nécessite --cle-cargowise ou --nct")
        res_cw = cw_client.interroger(cfg, [cle])
        etat = f"{VERT}opérationnel{RAZ}" if res_cw.ok else f"{JAUNE}non exploitable{RAZ}"
        print(f"CargoWise : {etat} — {res_cw.message}")
        if res_cw.ok:
            entete = res_cw.entete.get(cle, {})
            print(f"  clé testée : {cle}")
            for champ in ("mrn", "lrn", "statut_douane", "arrivee", "bureau"):
                if entete.get(champ):
                    libelle = {"mrn": "MRN", "lrn": "DM", "statut_douane": "statut",
                               "arrivee": "arrivée", "bureau": "bureau"}[champ]
                    print(f"  {libelle:8} : {entete[champ]}")
            print(f"  {len(res_cw.outils)} outils exposés par le serveur")
        for a in res_cw.avertissements:
            print(f"  ! {a}")
        if res_cw.autorisation_requise:
            print(f"{JAUNE}Autoriser l'accès : {_commande()} --autoriser{RAZ}")
            return 6
        return 0 if res_cw.ok else 5

    # --- clé et diagnostic du modèle IA ---------------------------------------
    if args.cle_ia:
        chemin = ia.enregistrer_cle(args.cle_ia)
        print(f"{VERT}Clé IA enregistrée{RAZ} dans {chemin} (droits 600).")
        print("Elle n'apparaît jamais dans le dossier du projet.")
        return 0
    if args.statut_ia:
        res_ia = ia.verifier(cfg)
        etat = f"{VERT}opérationnel{RAZ}" if res_ia["ok"] else f"{ROUGE}en échec{RAZ}"
        print(f"Modèle IA : {etat} — {res_ia['message']}")
        print(f"  endpoint : {res_ia['url']}")
        print(f"  modèle   : {res_ia['modele']}")
        print(f"  clé      : {'présente' if res_ia['cle'] else 'ABSENTE'}"
              f" (source : {res_ia['source']})")
        if not res_ia["cle"]:
            print(f"{JAUNE}Enregistrer la clé : "
                  f"{_commande()} --cle-ia VOTRE_CLE{RAZ}")
        return 0 if res_ia["ok"] else 7

    if not args.surveiller:
        print(f"{GRIS}ULIX — annonce d'arrivée NCTS{RAZ}")
        print(f"  dépôt unique   : {cfg['dossiers']['depot_unique']}")
        print(f"  dépôt multiple : {cfg['dossiers']['depot_multiple']}")
        print(f"  sortie         : {cfg['dossiers']['sortie']}")
        print(f"  CargoWise      : {'activé' if cfg['cargowise']['active'] else 'désactivé'}"
              + ("   (simulation)" if args.simulation else ""))
        print(f"  IA (repli)     : "
              + (f"{VERT}activée{RAZ}" if ia.disponible(cfg)
                 else f"{GRIS}désactivée{RAZ}"))
        print()

    problemes = verifier_environnement(cfg)
    if problemes:
        print(f"{ROUGE}Environnement incomplet :{RAZ}")
        for p in problemes:
            print(f"  - {p}")
        if any("gabarit ULIX" in p for p in problemes):
            return 4
        return 4

    mode = "unique" if args.unique and not args.multiple else (
        "multiple" if args.multiple and not args.unique else None)

    # --- mode guetteur : l'utilisateur dépose, le traitement part tout seul ---
    if args.surveiller:
        return _surveiller(cfg, args, mode)

    res = pipeline.executer(cfg, mode=mode, dry_run=args.simulation,
                            enrichir_cw=cfg["cargowise"]["active"],
                            cles_nct=args.nct)

    if not res.depots:
        print(f"{JAUNE}Aucun PDF à traiter.{RAZ} Déposer les fichiers dans "
              f"« {cfg['dossiers']['depot_unique']} » (1 fichier = 1 annonce) ou "
              f"« {cfg['dossiers']['depot_multiple']} » (plusieurs fichiers = 1 annonce).")
        return 2

    _afficher(res, args)
    if res.echecs or (not res.sorties and not res.modifiables and res.depots):
        print(f"{ROUGE}Traitement incomplet — fichiers non traités conservés dans le dépôt.{RAZ}")
        return 3
    return 0


def _afficher(res, args) -> None:
    """Compte rendu d'un passage : pages retenues, dossiers, fichiers produits."""
    nb_dossiers = sum(len(a.dossiers) for a in res.analyses)
    print(f"{GRIS}--- analyse ------------------------------------------------{RAZ}")
    for an in res.analyses:
        transit = ", ".join(str(p) for p in an.pages_transit) or "AUCUNE"
        ecartees = ", ".join(f"p{v.page}:{v.famille}" for v in an.pages_ecartees) or "aucune"
        print(f"  {an.pdf.name}")
        print(f"    pages transit retenues : {transit}")
        print(f"    pages écartées         : {ecartees}")
        for d in an.dossiers:
            conf = f"{VERT}haute{RAZ}" if d.confiance == "haute" else f"{JAUNE}{d.confiance}{RAZ}"
            print(f"    dossier {d.mrn or '?'} — DM {d.dm or '?'} — {len(d.articles)} article(s) "
                  f"— confiance {conf}")
            for a in d.avertissements:
                print(f"      {JAUNE}!{RAZ} {a}")
            if d.ecart:
                print(f"      {ROUGE}écart : {d.ecart}{RAZ}")
        if not an.dossiers:
            print(f"    {JAUNE}aucune donnée de transit exploitable{RAZ}")

    print(f"{GRIS}--- résultats ----------------------------------------------{RAZ}")
    if args.simulation:
        for s in res.sorties:
            print(f"  {GRIS}[simulation — aucun fichier écrit]{RAZ} {s.name}")
    else:
        for s in res.sorties:
            taille = s.stat().st_size / 1024 if s.exists() else 0
            print(f"  {VERT}PDF{RAZ} {s}  ({taille:.0f} Ko)")
    for s in res.modifiables:
        reserve = " — données incomplètes ou anomalies signalées" if s in res.modifiables_avec_reserves else ""
        print(f"  Word modifiable{' [simulation]' if args.simulation else ''}{reserve} : {s}")
    for s in res.a_verifier:
        print(f"  {JAUNE}À VÉRIFIER — NON VALIDÉ{RAZ} {s}")
    for fiche in res.fiches:
        print(f"  fiche interne : {fiche}")
    for r in res.rapports:
        print(f"  {GRIS}rapport{RAZ} {r}")
    for m in res.messages:
        if m.startswith("rapport"):
            continue
        print(f"  {JAUNE}{m}{RAZ}")

    print()
    bilan = [f"{nb_dossiers} dossier(s) de transit traité(s)"]
    if res.modifiables:
        bilan.append(f"{len(res.modifiables)} Word modifiable(s) généré(s), dont "
                     f"{len(res.modifiables_avec_reserves)} avec données incomplètes ou anomalies signalées")
    if res.sorties:
        bilan.append(f"{len(res.sorties)} PDF prêt(s) à remettre")
    if res.a_verifier:
        bilan.append(f"{len(res.a_verifier)} PDF à vérifier")
    print(", ".join(bilan) + ".")
    if res.modifiables:
        print("La génération Word ne vaut pas validation des données ; détails dans le rapport interne.")



def _surveiller(cfg: dict, args, mode: str | None) -> int:
    """Guetteur : attend qu'un lot soit déposé, le traite, puis recommence.

    C'est le mode d'exploitation « transparent » : l'utilisateur dépose ses PDF
    et n'a plus rien à lancer. Chaque lot détecté est traité puis les PDF sont
    archivés, donc un fichier n'est jamais traité deux fois.
    """
    from ulix_ncts import surveillance

    depot_unique = Path(cfg["dossiers"]["depot_unique"])
    depot_multiple = Path(cfg["dossiers"]["depot_multiple"])
    stabilite = float(cfg["traitement"].get("stabilite_s", 3))
    intervalle = float(cfg["traitement"].get("intervalle_s", 10))

    print(f"{GRIS}ULIX — annonce d'arrivée NCTS : surveillance des dépôts{RAZ}")
    print(f"  dépôt unique   : {depot_unique}")
    print(f"  dépôt multiple : {depot_multiple}")
    print(f"  sortie         : {cfg['dossiers']['sortie']}")
    print(f"  CargoWise      : {'activé' if cfg['cargowise']['active'] else 'désactivé'}")
    print(f"  IA (repli)     : "
          + (f"{VERT}activée{RAZ}" if ia.disponible(cfg)
             else f"{GRIS}désactivée{RAZ}"))
    print(f"  déposer un PDF suffit : le traitement démarre seul "
          f"(attente de {stabilite:.0f} s après la fin de la copie)")
    if args.simulation:
        print(f"  {JAUNE}simulation : aucun fichier ne sera écrit ni archivé{RAZ}")
    print(f"{GRIS}Interrompre : Ctrl+C{RAZ}\n")

    passages = 0
    ignores = set()
    try:
        while True:
            lot = surveillance.attendre_lot(
                depot_unique if mode != "multiple" else depot_unique / ".inactif",
                depot_multiple if mode != "unique" else depot_multiple / ".inactif",
                stabilite_s=stabilite, echo=print, ignores=ignores)
            uniques, multiples, _ = lot
            res = None
            signatures = {(str(p), surveillance._signature([p])) for p in uniques + multiples}
            try:
                res = pipeline.executer(cfg, mode=mode, dry_run=args.simulation,
                                        enrichir_cw=cfg["cargowise"]["active"],
                                        cles_nct=args.nct,
                                        lot=(uniques, multiples))
                _afficher(res, args)
                passages += 1
            except Exception as exc:  # noqa: BLE001
                # un lot défectueux ne doit jamais arrêter la surveillance
                print(f"{ROUGE}Échec du traitement de ce lot : {type(exc).__name__} "
                      f"— {exc}{RAZ}")
                print(f"{JAUNE}Les fichiers restent dans le dépôt ; corriger puis "
                      f"les redéposer.{RAZ}")
            # Ne pas retraiter indéfiniment un échec, --garder ou une simulation.
            # Une modification du fichier autorise un nouvel essai.
            ignores.update(signatures)
            if args.une_fois:
                return 3 if res is None or res.echecs else 0
            print(f"{GRIS}En attente du prochain dépôt ({passages} lot(s) traité(s))…{RAZ}")
            time.sleep(intervalle)
    except KeyboardInterrupt:
        print(f"\n{GRIS}Surveillance arrêtée — {passages} lot(s) traité(s).{RAZ}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
