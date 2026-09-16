"""Configuration du générateur d'annonces d'arrivée NCTS.

Repères de chemin :
  * ``racine`` (``_racine``)  = dossier du script ``lancer.py`` (code) ;
  * ``projet`` (``_projet``)  = son parent = dossier métier qui contient
    « Dépots unique », « Dépots multiple », « Annonces d'arrivées », « Archive ».
  * ``Documentation/`` se trouve dans la racine du code, à côté de ``lancer.py``.

Les dossiers de travail sont résolus relativement au dossier PROJET (et non au
code), avec tolérance des variantes d'accents et du NFD macOS.

Toutes les valeurs ont un défaut : le script tourne sans fichier de config. Un
``config.json`` (à côté du script) ou ``~/.ulix_ncts.json`` peut surcharger ; les
variables d'environnement ``ULIX_*`` ont la priorité la plus haute.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path

from . import fsutil

DEFAULTS = {
    "dossiers": {
        # Relatifs au dossier PROJET si non absolus. La résolution tolère les
        # variantes d'accents (« Dépots » / « Dépôts ») et le NFD macOS.
        "depot_unique": "Dépôts unique",
        "depot_multiple": "Dépôts multiple",
        "sortie": "Annonces d'arrivées",
        "archive": "Archive",
    },
    "traitement": {
        "deplacer_traite": True,          # archiver les PDF traités dans Archive/
        "ecrire_data_json": True,         # écrire le data.json à côté du PDF
        "ecrire_rapport": True,           # écrire le rapport de passage (texte)
        "dpi_ocr": 200,                   # dpi pour les rendus/OCR
        "langue_ocr": "eng",              # seul "eng" est requis (chiffres + latin)
        "stabilite_s": 3,                 # attente avant de juger un dépôt terminé
        "intervalle_s": 10,               # pause entre deux lots (mode --surveiller)
    },
    "document": {
        "format_sortie": "docx",
        "numero_controle": "3140",        # n° d'autorisation du lieu agréé ULIX (FIXE)
        "societe": "ULIX SWISS SA",
        "pied_page": "V1.0 — ULIX SWISS SA — données CargoWise INSTANCE_EXEMPLE",
    },
    "ia": {
        # Repli IA (vision) pour les pages que l'extraction déterministe rate.
        # Le traitement n'appelle le modèle que sur les dossiers incomplets :
        # pdftotext/tesseract restent le chemin normal (rapide, gratuit, hors ligne).
        "active": True,
        "base_url": "",           # vide = relais Ollama local puis config de l'agent
        "modele": "",             # vide = modèle configuré pour l'agent
        "api_key": "",            # NE RIEN METTRE ICI : laisser vide (fichier visible)
        "timeout_s": 180,
        "max_pages": 12,           # pages relues au maximum par dossier
        "max_tokens": 4096,       # les modèles raisonneurs consomment du budget
        "dpi": 150,               # suffisant pour une page A4 de formulaire
    },
    "binaires": [
        # Dossiers contenant pdfinfo/pdftotext/pdftoppm/tesseract, si ces outils
        # ne sont pas dans le PATH (cas fréquent sur Windows : archive poppler
        # extraite dans Program Files). Exemple :
        #   "C:\\Program Files\\poppler\\Library\\bin",
        #   "C:\\Program Files\\Tesseract-OCR"
        # Sur macOS, laisser vide : Homebrew les met dans le PATH.
    ],
    "cargowise": {
        "active": False,                  # true = interroger le serveur MCP CargoWise
        "url": "",                        # ex. https://mcp.exemple.ch/mcp (jamais de secret ici)
        "token": "",                      # jeton Bearer explicite (si pas d'OAuth)
        # --- OAuth (serveur MCP distant protégé) ---
        "resource_metadata": "",          # laisser vide : découvert via le 401/well-known
        "client_id": "",                  # vide = enregistrement dynamique si proposé
        "client_secret": "",
        "token_endpoint": "",             # utile seulement en client_credentials
        "scopes": [],                     # vide = scopes_supported du serveur
        "autorisation_interactive": False,  # true = ouvre le navigateur si 401
        "timeout_s": 20,
        # noms d'outils recherchés (résolus dynamiquement dans tools/list)
        "outil_entete": ["cargowise_get_ncts", "get_ncts"],
        "outil_dossier": ["cargowise_get_shipment", "cargowise_get_record",
                          "get_shipment", "get_record"],
    },
}

_ENV_MAP = {
    "ULIX_DEPOT_UNIQUE": ("dossiers", "depot_unique"),
    "ULIX_DEPOT_MULTIPLE": ("dossiers", "depot_multiple"),
    "ULIX_SORTIE": ("dossiers", "sortie"),
    "ULIX_ARCHIVE": ("dossiers", "archive"),
    "CW_MCP_URL": ("cargowise", "url"),
    "CW_MCP_TOKEN": ("cargowise", "token"),
    "CW_OAUTH_CLIENT_ID": ("cargowise", "client_id"),
    "CW_OAUTH_CLIENT_SECRET": ("cargowise", "client_secret"),
    "CW_OAUTH_TOKEN_ENDPOINT": ("cargowise", "token_endpoint"),
    "CW_OAUTH_RESOURCE_METADATA": ("cargowise", "resource_metadata"),
    "CW_OAUTH_SCOPES": ("cargowise", "scopes"),
    "ULIX_IA_ACTIVE": ("ia", "active"),
    "ULIX_IA_MODELE": ("ia", "modele"),
    "ULIX_IA_URL": ("ia", "base_url"),
}

# Fichier `.env` : variables lues au démarrage, sans écraser l'environnement réel.
# Il vit dans le dossier PROJET (à côté des dépôts), jamais dans Git (`.gitignore`).
NOM_ENV = ".env"


def lire_dotenv(chemin: Path) -> dict[str, str]:
    """Paires ``CLE=valeur`` d'un fichier `.env` (commentaires et guillemets tolérés).

    Aucune interpolation : la valeur est prise telle quelle, guillemets simples
    ou doubles retirés s'ils entourent toute la valeur. Un fichier illisible
    donne un dictionnaire vide : l'absence de `.env` n'est jamais une erreur.
    """
    out: dict[str, str] = {}
    try:
        texte = Path(chemin).read_text(encoding="utf-8-sig")
    except OSError:
        return out
    for brute in texte.splitlines():
        ligne = brute.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        if ligne.lower().startswith("export "):
            ligne = ligne[7:].strip()
        cle, _, valeur = ligne.partition("=")
        cle = cle.strip()
        valeur = valeur.strip()
        if len(valeur) >= 2 and valeur[0] == valeur[-1] and valeur[0] in "\"'":
            valeur = valeur[1:-1]
        elif " #" in valeur:
            valeur = valeur.split(" #", 1)[0].rstrip()
        if cle and all(c.isalnum() or c == "_" for c in cle):
            out[cle] = valeur
    return out


def charger_env(*dossiers: Path) -> list[Path]:
    """Charge le premier `.env` trouvé dans `dossiers` dans ``os.environ``.

    Une variable déjà définie dans l'environnement garde sa valeur : le `.env`
    fournit des défauts de poste (clé Ollama, modèle), il n'impose rien à qui
    exporte ses variables lui-même. Renvoie les fichiers effectivement lus.
    """
    lus: list[Path] = []
    for dossier in dossiers:
        if not dossier:
            continue
        fichier = Path(dossier) / NOM_ENV
        if not fichier.is_file():
            continue
        for cle, valeur in lire_dotenv(fichier).items():
            if cle not in os.environ and valeur != "":
                os.environ[cle] = valeur
        lus.append(fichier)
        break
    return lus


def _deep_update(base: dict, patch: dict) -> dict:
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            _deep_update(base[k], v)
        else:
            base[k] = v
    return base


def _coerce(section: str, key: str, value):
    if section == "ia" and key == "active":
        return str(value).strip().lower() in ("1", "true", "oui", "yes", "on")
    if section == "cargowise" and key == "active":
        return str(value).strip().lower() in ("1", "true", "oui", "yes", "on")
    if section == "cargowise" and key == "autorisation_interactive":
        return str(value).strip().lower() in ("1", "true", "oui", "yes", "on")
    if section == "cargowise" and key == "scopes":
        if isinstance(value, (list, tuple)):
            return [str(v).strip() for v in value if str(v).strip()]
        return [s.strip() for s in str(value).split(",") if s.strip()]
    if section == "traitement" and key in ("dpi_ocr",):
        return int(value)
    return value


def charger(racine: Path | None = None, projet: Path | None = None) -> dict:
    """Charge la configuration (défauts < fichier < environnement).

    ``racine`` = dossier du code (où peut vivre config.json) ;
    ``projet`` = dossier métier où se trouvent les dossiers de dépôt (par défaut
    le parent de ``racine``).
    """
    racine = Path(racine).resolve() if racine else Path(__file__).resolve().parent.parent
    projet = Path(projet).resolve() if projet else racine.parent
    cfg = copy.deepcopy(DEFAULTS)

    for candidat in (racine / "config.json", projet / "config.json",
                     Path.home() / ".ulix_ncts.json"):
        if candidat.is_file():
            try:
                _deep_update(cfg, json.loads(candidat.read_text(encoding="utf-8")))
            except Exception as exc:      # config illisible : on garde les défauts
                print(f"! config {candidat} ignorée ({exc})")

    for env, (section, key) in _ENV_MAP.items():
        if os.environ.get(env):
            cfg[section][key] = _coerce(section, key, os.environ[env])

    if os.environ.get("CW_MCP_URL") or os.environ.get("ULIX_CARGOWISE_ACTIVE"):
        cfg["cargowise"]["active"] = _coerce(
            "cargowise", "active", os.environ.get("ULIX_CARGOWISE_ACTIVE", "true"))

    cfg["_racine"] = str(racine)
    cfg["_projet"] = str(projet)
    for k, v in list(cfg["dossiers"].items()):
        p = Path(v)
        chemin = p if p.is_absolute() else (projet / v)
        cfg["dossiers"][k] = str(fsutil.resoudre(projet, chemin))
    return cfg
