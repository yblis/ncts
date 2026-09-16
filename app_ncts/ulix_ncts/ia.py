"""Repli IA (vision) — lecture des pages que l'extraction déterministe rate.

Principe « cheap-first » du skill : le chemin normal reste `pdftotext` +
`tesseract` (déterministe, ~11 % du temps de traitement, gratuit, hors ligne).
Ce module n'est appelé **que** pour les dossiers que le déterministe n'a pas su
renseigner — typiquement :

* les SAD dont la couche texte confond lettres et chiffres (l/1, S/5, O/0) ;
* les TCH sans waybill, où la seule désignation est une facture proforma dont le
  tableau est illisible pour l'OCR classique.

Le modèle est celui configuré pour l'agent (`deepseek-v4.1-flash`) via Ollama.
Les appels ne bloquent jamais le traitement : toute erreur fait retomber sur le
résultat déterministe déjà obtenu, avec un avertissement dans le rapport.

Aucun journal, aucun message et aucun fichier produit ne contient la clé d'API.
"""

from __future__ import annotations

import copy
import hashlib
import base64
import json
import os
import re
import urllib.error
import urllib.request
from pathlib import Path

from . import extract, pdfio, plateforme

# Fichier privé du poste : propre à l'outil, hors du dossier du projet pour ne
# jamais partir avec une copie du dossier, et hors de la configuration de
# l'agent Hermes. Créé en droits 600 (voir `enregistrer_cle`).
CHEMIN_PRIVE = Path.home() / ".ulix_ncts_ia.json"

# ------------------------------------------------------------------ consigne
CONSIGNE_SYSTEME = """Tu transcris des documents douaniers et de transport \
(déclaration de transit NCTS/TAD, T1, TCH suisse, lettre de voiture) scannés.

Tu reçois l'image d'UNE page. Tu rends un objet JSON strictement conforme à ce \
schéma, et RIEN d'autre (pas de texte avant, pas de commentaire après) :

{
  "document": {"type": "transit|facture|waybill|autre", "reference": "", "mrn": "", "awb": "", "page": null, "pages": null},
  "articles": [
    {"designation": "", "code_nc": "", "brut": "", "net": "", "colis": "",
     "doc_prec": ""}
  ],
  "parties": [{"role": "", "nom": "", "adresse": ""}],
  "transport": [{"libelle": "", "valeur": ""}],
  "total_colis": "",
  "total_brut": "",
  "confiance": "haute|moyenne|faible",
  "commentaire": ""
}

Règles impératives :
- "document" : recopie la référence du document, MRN et AWB tels qu'imprimés.
  "page" et "pages" sont la pagination IMPRIMÉE (exemple 2 sur 3), sinon null.
  Ne déduis jamais ces références du contexte fourni. Ne mélange pas les totaux
  d'une facture et d'un transit. Ne transforme pas une quantité commerciale en colis.
- Recopie EXACTEMENT ce qui est écrit, sans corriger ni interpréter, même si la
  graphie paraît fautive : c'est une donnée douanière.
- N'invente JAMAIS. Un champ que tu ne lis pas avec certitude reste "".
- N'écris JAMAIS "0" pour une masse, un nombre de colis ou une quantité : si la
  valeur n'est pas lisible ou n'est pas imprimée, laisse "". Une masse de 0 kg
  n'existe pas sur une déclaration de transit, et un "0" se lit comme une donnée
  saisie alors qu'il ne l'est pas.
- "designation" : la désignation de la marchandise telle qu'imprimée. Si la page
  ne porte qu'un tableau de facture (description/quantité/poids), transcris-en
  les lignes : c'est ce qu'on attend.
- "brut"/"net" : masse brute et nette en kg, chiffres seuls, point décimal.
- "colis" : nombre de colis de la ligne, chiffres seuls.
- "code_nc" : code marchandise à 8 chiffres (ou code SH/HS sur la facture).
  Ne le recopie PAS dans "designation" si tu le mets déjà ici.
- "parties" : rôles possibles — Expéditeur, Destinataire, Titulaire,
  Transporteur, Importateur. Adresse sur une seule ligne.
- "transport" : libellés utiles (Véhicule / mode, Scellés, Nbre de colis,
  Masse brute totale, Pays de destination, Terme ultime, Garantie, Bureau de
  départ, Bureau de destination).
- "confiance" : "haute" si l'image est nette et la transcription sûre,
  "faible" si tu doutes (page floue, inclinée, masquée).
- Si la page ne porte aucune donnée exploitable (photo, page blanche, enveloppe),
  rends {"articles": [], "confiance": "faible", "commentaire": "page sans donnée"}.
"""


def configuration(cfg: dict) -> dict:
    """Paramètres IA effectifs, sans aucune dépendance à l'agent Hermes.

    Ordre de résolution (le premier trouvé gagne) :

    1. variables d'environnement ``OLLAMA_API_KEY`` / ``OLLAMA_BASE_URL`` ;
    2. fichier privé du poste ``~/.ulix_ncts_ia.json`` (droits 600) ;
    3. section ``ia`` de ``config.json``.

    La clé n'est jamais écrite dans `config.json` (fichier visible et copiable) :
    elle vit dans le fichier privé ou dans l'environnement.
    """
    prive = _config_privee()
    section = cfg.get("ia") or {}
    cle = (os.environ.get("OLLAMA_API_KEY")
           or prive.get("api_key", "")
           or section.get("api_key", ""))
    url = (os.environ.get("OLLAMA_BASE_URL")
           or prive.get("base_url", "")
           or section.get("base_url", "")
           or "https://ollama.com/v1").rstrip("/")
    modele = (os.environ.get("ULIX_IA_MODELE")
              or prive.get("modele", "")
              or section.get("modele", "")
              or "deepseek-v4.1-flash:cloud")
    return {
        "cle": cle,
        "url": url,
        "modele": modele,
        "source": ("environnement" if os.environ.get("OLLAMA_API_KEY")
                   else f"fichier privé {CHEMIN_PRIVE.name}" if prive.get("api_key")
                   else "config.json" if section.get("api_key") else "aucune"),
        "timeout": int(section.get("timeout_s", 180)),
        "max_pages": int(section.get("max_pages", 12)),
        "max_tokens": int(section.get("max_tokens", 4096)),
        "dpi": int(section.get("dpi", 150)),
    }


def _config_privee() -> dict:
    """Contenu de ``~/.ulix_ncts_ia.json``, ou {} si absent/illisible.

    Ce fichier est propre à l'outil : il ne dépend ni de l'agent Hermes ni d'un
    autre logiciel du poste, et reste hors du dossier du projet pour ne jamais
    partir avec une copie du dossier.
    """
    if not CHEMIN_PRIVE.is_file():
        return {}
    try:
        donnees = json.loads(CHEMIN_PRIVE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(donnees, dict):
        return {}
    return {k: str(v).strip() for k, v in donnees.items()
            if k in ("api_key", "base_url", "modele") and v}


def enregistrer_cle(cle: str, url: str = "", modele: str = "") -> Path:
    """Écrit la clé dans le fichier privé du poste, en droits 600.

    Le fichier est créé avec des droits restrictifs **avant** de recevoir la clé,
    pour qu'il ne soit jamais lisible par un autre compte, même un instant.
    Retourne le chemin écrit.
    """
    CHEMIN_PRIVE.parent.mkdir(parents=True, exist_ok=True)
    donnees = {
        "_commentaire": "Clé d'accès au modèle IA ULIX (Ollama Cloud). Fichier "
                        "privé en droits 600 : ne pas le recopier dans "
                        "config.json ni le déposer dans un dossier partagé.",
        "api_key": cle.strip(),
    }
    if url:
        donnees["base_url"] = url.strip()
    if modele:
        donnees["modele"] = modele.strip()
    temporaire = CHEMIN_PRIVE.with_suffix(".tmp")
    descripteur = os.open(temporaire, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descripteur, "w", encoding="utf-8") as f:
        json.dump(donnees, f, ensure_ascii=False, indent=2)
    temporaire.replace(CHEMIN_PRIVE)
    plateforme.restreindre(CHEMIN_PRIVE)
    return CHEMIN_PRIVE


def verifier(cfg: dict) -> dict:
    """Contrôle l'accès au modèle : endpoint joignable, clé acceptée, modèle offert.

    Ne journalise ni ne renvoie jamais la clé — seulement sa présence et sa source.
    """
    conf = configuration(cfg)
    res = {"ok": False, "message": "", "url": conf["url"], "modele": conf["modele"],
           "cle": bool(conf["cle"]), "source": conf["source"]}
    if not conf["cle"]:
        res["message"] = ("aucune clé : la fournir par OLLAMA_API_KEY ou "
                          "--cle-ia")
        return res
    if not conf["url"].startswith("https://") and "127.0.0.1" not in conf["url"] \
            and "localhost" not in conf["url"]:
        # un endpoint distant en clair transmettrait la clé sans chiffrement
        res["message"] = (f"endpoint non chiffré ({conf['url']}) : utiliser "
                          f"https:// — la clé passerait en clair")
        return res
    try:
        req = urllib.request.Request(conf["url"] + "/models")
        req.add_header("Authorization", f"Bearer {conf['cle']}")
        with urllib.request.urlopen(req, timeout=30) as rep:
            offerts = [m.get("id", "") for m in json.loads(rep.read().decode())
                       .get("data", [])]
    except urllib.error.HTTPError as exc:
        res["message"] = f"HTTP {exc.code} sur /models (clé refusée ou endpoint erroné)"
        return res
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        res["message"] = f"endpoint injoignable : {type(exc).__name__}"
        return res
    base = conf["modele"].split(":")[0]
    if not any(base in n for n in offerts):
        res["message"] = (f"le modèle {conf['modele']} n'est pas proposé "
                          f"({len(offerts)} modèle(s) accessibles)")
        return res
    res["ok"] = True
    res["message"] = f"modèle {conf['modele']} accessible ({len(offerts)} modèles)"
    return res


def disponible(cfg: dict) -> bool:
    """Le repli IA est-il activable (activé + endpoint et clé présents) ?"""
    section = cfg.get("ia") or {}
    if not section.get("active"):
        return False
    conf = configuration(cfg)
    return bool(conf["url"] and conf["cle"])


# ------------------------------------------------------------------ appel
def _poster(conf: dict, charge: dict, timeout: int) -> dict:
    corps = json.dumps(charge).encode("utf-8")
    req = urllib.request.Request(conf["url"] + "/chat/completions",
                                 data=corps, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {conf['cle']}")
    with urllib.request.urlopen(req, timeout=timeout) as rep:
        return json.loads(rep.read().decode("utf-8"))


def _extraire_json(texte: str) -> dict | None:
    """Récupère le premier objet JSON d'une réponse, même entourée de texte."""
    if not texte:
        return None
    texte = re.sub(r"^```(?:json)?|```$", "", texte.strip(), flags=re.MULTILINE)
    debut = texte.find("{")
    if debut < 0:
        return None
    profondeur = 0
    for i in range(debut, len(texte)):
        if texte[i] == "{":
            profondeur += 1
        elif texte[i] == "}":
            profondeur -= 1
            if profondeur == 0:
                try:
                    return json.loads(texte[debut:i + 1])
                except json.JSONDecodeError:
                    return None
    return None


def lire_page(image: Path, conf: dict, contexte: str = "") -> dict | None:
    """Fait lire une page par le modèle. Retourne le dict, ou None en échec.

    Certains modèles raisonneurs renvoient d'abord leur réflexion dans
    ``reasoning`` et peuvent laisser ``content`` vide si le budget de jetons est
    atteint : on retente une fois avec un budget double avant d'abandonner.
    """
    b64 = base64.b64encode(image.read_bytes()).decode("ascii")
    invite = ("Transcris cette page selon le schéma JSON demandé."
              + (f"\nContexte connu : {contexte}" if contexte else ""))
    for budget in (conf["max_tokens"], conf["max_tokens"] * 2):
        charge = {
            "model": conf["modele"],
            "max_tokens": budget,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": CONSIGNE_SYSTEME},
                {"role": "user", "content": [
                    {"type": "text", "text": invite},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/png;base64,{b64}"}}]},
            ],
        }
        try:
            reponse = _poster(conf, charge, conf["timeout"])
        except urllib.error.HTTPError as exc:
            try:
                detail = exc.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001
                detail = ""
            return {"_erreur": f"HTTP {exc.code} — {detail}"}
        except (urllib.error.URLError, OSError, TimeoutError) as exc:
            return {"_erreur": f"{type(exc).__name__} — {exc}"}
        try:
            message = reponse["choices"][0]["message"]
        except (KeyError, IndexError, TypeError):
            return {"_erreur": "réponse inattendue du modèle"}
        contenu = (message.get("content") or "").strip()
        if not contenu:
            # raisonnement seul : on retente avec plus de budget
            if message.get("reasoning"):
                continue
            return {"_erreur": "réponse vide du modèle"}
        lu = _extraire_json(contenu)
        if lu is None:
            return {"_erreur": f"JSON illisible : {contenu[:120]}"}
        return lu
    return {"_erreur": "le modèle n'a rendu que du raisonnement, sans réponse"}


# ------------------------------------------------------------------ fusion
def _nombre(valeur) -> float | None:
    return extract.nombre(valeur) if valeur else None


def _texte(valeur) -> str:
    """Valeur rendue par le modèle, nettoyée.

    Un « 0 » isolé est traité comme une absence : les modèles écrivent souvent 0
    pour un champ qu'ils n'ont pas su lire, alors qu'une masse ou un colis de 0
    n'existe pas sur une déclaration de transit. Sans ce filtre, `formater_kg(0)`
    affichait « 0,00 kg » dans le document, c'est-à-dire une valeur fausse
    présentée comme lue.
    """
    if valeur is None:
        return ""
    texte = str(valeur).strip()
    if texte in ("0", "0.0", "0.00", "0,0", "0,00", "-", "N/A", "n/a", "null",
                 "None", "aucun", "aucune"):
        return ""
    return texte


def _masse(valeur) -> str:
    """Masse rendue par le modèle, au même format que l'extraction déterministe."""
    if not _texte(valeur):
        return ""
    n = _nombre(valeur)
    return extract.formater_kg(n) if n else ""


# Libellés du bloc transport admis dans l'annonce (étape 5 du skill) : le modèle
# est ramené sur ces libellés canoniques, pour que le document reste homogène et
# qu'aucun champ de facture ne s'y glisse.
_LIBELLES_TRANSPORT = (
    (r"v[ée]hicule|mode|means of transport", "Véhicule / mode"),
    (r"scell[ée]|seal", "Scellés"),
    (r"pays de destination|country of destin", "Pays de destination"),
    (r"terme ultime|ultimate", "Terme ultime"),
    (r"garantie|guarantee", "Garantie"),
    (r"bureau de d[ée]part|office of departure", "Bureau de départ"),
    (r"bureau de destination|office of destin", "Bureau de destination"),
    (r"masse brute|gross mass|poids brut", "Masse brute totale"),
    (r"masse nette|net mass|poids net", "Masse nette totale"),
    (r"colis|package|parcel", "Nbre de colis"),
    (r"conteneur|container", "N° de conteneur"),
    (r"exp[ée]dition|shipment", "Réf. d'expédition"),
)


def _libelle_transport(propose: str) -> str:
    """Ramène un libellé proposé par le modèle sur un libellé admis, sinon ""."""
    texte = propose.strip().lower()
    for motif, libelle in _LIBELLES_TRANSPORT:
        if re.search(motif, texte):
            return libelle
    return ""


def appliquer(d: "extract.Dossier", lu: dict) -> bool:
    """Reporte une lecture IA sur un dossier. True si quelque chose a changé."""
    change = False

    # articles : l'IA comble (ou remplace) les lignes non désignées
    lus = [a for a in (lu.get("articles") or []) if isinstance(a, dict)]
    lus = [a for a in lus if _texte(a.get("designation"))]
    # on ignore les lignes manifestement inventées ou vides
    if lus:
        actuels = [a for a in d.articles
                   if a.designation and a.designation != extract.A_VERIFIER]
        if not actuels:
            d.articles = []
            for i, a in enumerate(lus, 1):
                code = _texte(a.get("code_nc"))
                designation = _texte(a.get("designation"))
                # le modèle ajoute parfois le code marchandise dans la désignation
                # (« Papierosy / cigarettes, tc: 24022090 ») : on le retire pour ne
                # pas le répéter dans la colonne code NC du document.
                if code and code in designation:
                    designation = re.sub(
                        r"[,;]?\s*(?:tc|t\.c|ta|code|hs|nc|sh)\s*[:.]?\s*" + re.escape(code),
                        "", designation, flags=re.IGNORECASE).strip(" ,;.-")
                d.articles.append(extract.Article(
                    no=_texte(a.get("no")) or str(i),
                    designation=designation or _texte(a.get("designation")),
                    code_nc=code,
                    brut=_masse(a.get("brut")),
                    net=_masse(a.get("net")),
                    colis=_texte(a.get("colis")),
                    doc_prec=_texte(a.get("doc_prec"))))
            d.source_marchandises = ("Lecture IA de la page — extraction "
                                     "automatique en échec (contrôle interne)")
            d.avertissements.append(
                f"désignations reprises par IA ({len(lus)} ligne(s)) — à contrôler")
            change = True
        else:
            # le déterministe a lu des lignes : on ne complète que les trous
            for actuel in actuels:
                correspondants = [a for a in lus if _texte(a.get("designation")).casefold() == actuel.designation.strip().casefold()]
                if len(correspondants) != 1:
                    continue
                vu = correspondants[0]
                for champ in ("code_nc", "brut", "net", "colis", "doc_prec"):
                    if not getattr(actuel, champ):
                        valeur = (_masse(vu.get(champ))
                                  if champ in ("brut", "net")
                                  else _texte(vu.get(champ)))
                        if valeur:
                            setattr(actuel, champ, valeur)
                            change = True

    if not d.parties and lu.get("parties"):
        for p in lu["parties"]:
            if isinstance(p, dict) and _texte(p.get("nom")):
                d.parties.append({"role": _texte(p.get("role")),
                                  "lignes": [_texte(p.get("nom")), _texte(p.get("adresse"))]})
                change = True

    # transport : uniquement les libellés attendus du document (étape 5 du
    # skill). Le modèle propose parfois des champs de la facture (« AWB No. »,
    # « Page », « Proforma Invoice No ») qui n'ont pas leur place dans l'annonce.
    connus = {lbl.lower() for lbl, _ in d.transport}
    for t in (lu.get("transport") or []):
        if not isinstance(t, dict):
            continue
        libelle, valeur = _texte(t.get("libelle")), _texte(t.get("valeur"))
        if not libelle or not valeur:
            continue
        retenu = _libelle_transport(libelle)
        if not retenu or retenu.lower() in connus:
            continue
        if retenu in ("Masse brute totale", "Masse nette totale"):
            valeur = _masse(valeur)          # même format que le déterministe
            if not valeur:
                continue
        elif retenu == "Véhicule / mode" and not re.search(
                r"(?i)route|rail|fer|mer|maritim|air|a[ée]rien|postal|"
                r"camion|wagon|navire|avion|routier", valeur):
            # le modèle range ici des références de documents (n° de waybill,
            # « DHL Express ») : ce n'est pas un mode de transport
            continue
        d.transport.append([retenu, valeur])
        connus.add(retenu.lower())
        change = True

    if not d.total.get("colis") and _texte(lu.get("total_colis")):
        chiffres = re.sub(r"\D", "", _texte(lu["total_colis"]))
        if chiffres:
            d.total["colis"] = f"{chiffres} colis"
            change = True
    if not d.total.get("brut") and _nombre(lu.get("total_brut")) is not None:
        d.total["brut"] = extract.formater_kg(_nombre(lu["total_brut"]))
        change = True

    if _texte(lu.get("commentaire")):
        d.avertissements.append(f"IA : {_texte(lu['commentaire'])[:160]}")
    return change


# Marqueurs d'un tableau de marchandises : c'est là que se trouvent la
# désignation, le code marchandise et les masses. On les cherche dans la couche
# texte (gratuit, instantané) pour soumettre d'abord les pages les plus riches.
_MOTIFS_TABLEAU = re.compile(
    r"(?i)\b(description|designation|quantit|qty|unit price|total|hs code|"
    r"tariff|commodity|goods|invoice|proforma|facture|marchandise|weight|"
    r"poids|gross|net)\b")


def _richesse_page(pdf: Path, page: int) -> int:
    """Score indicatif : la page porte-t-elle un tableau de marchandises ?"""
    try:
        texte = pdfio.couche_texte_layout(pdf, page)
    except Exception:  # noqa: BLE001
        return 0
    return len(set(m.group(0).lower() for m in _MOTIFS_TABLEAU.finditer(texte)))


def _pages_a_lire(an: "object", conf: dict) -> list[int]:
    """Pages à soumettre au modèle, de la plus prometteuse à la moins utile.

    Une page de transit passe avant tout (elle porte l'en-tête) ; ensuite on
    classe par richesse du tableau marchandises. Sur un TCH suisse, la page de
    transit ne porte aucune désignation et c'est la facture proforma en annexe
    qui l'apporte — la lire en premier évite de s'arrêter sur le waybill, qui
    donne une désignation sans code marchandise. Les enveloppes de pagination
    sont écartées : elles ne contiennent rien.
    """
    rang = {"TRANSIT_TAD": 0, "TRANSIT_TCH": 0, "TRANSIT_FR": 0,
            "ANNONCE_CW": 0, "ANNONCE_CW_INV": 0, "ANNONCE_CW_LISTE": 1, "TRANSIT_LISTE": 1}
    pages = [v for v in an.verdicts if v.famille not in {"ENVELOPPE", "EXPORT"}]
    pages.sort(key=lambda v: (rang.get(v.famille, 2),
                              -_richesse_page(an.pdf, v.page), v.page))
    return [v.page for v in pages[:conf["max_pages"]]]


# ------------------------------------------------------------------ qualité
def _score_lecture(lu: dict) -> int:
    """Nombre de champs utiles rendus par une lecture (pour choisir la meilleure)."""
    if not lu or lu.get("_erreur"):
        return -1
    lignes = [a for a in (lu.get("articles") or [])
              if isinstance(a, dict) and _texte(a.get("designation"))]
    if not lignes:
        return 0
    score = 1
    for champ in ("code_nc", "brut", "net", "colis"):
        if any(_texte(a.get(champ)) for a in lignes):
            score += 1
    return score


def _lecture_suffisante(lu: dict) -> bool:
    """Une lecture qui donne désignation + code marchandise + masse suffit."""
    lignes = [a for a in (lu.get("articles") or [])
              if isinstance(a, dict) and _texte(a.get("designation"))]
    if not lignes:
        return False
    return all(_texte(a.get("code_nc")) for a in lignes) and \
        any(_texte(a.get("brut")) or _texte(a.get("net")) for a in lignes)


def _besoin(dossier: "extract.Dossier") -> bool:
    """Reste-t-il une lacune essentielle (désignation, code ou masse) ?"""
    lisibles = [a for a in dossier.articles
                if a.designation and a.designation != extract.A_VERIFIER]
    if not lisibles:
        return True
    return all(not (a.code_nc or a.brut or a.net) for a in lisibles)


def _entier_page(valeur):
    if isinstance(valeur, bool):
        return None
    try:
        n = int(str(valeur))
        return n if n > 0 else None
    except (ValueError, TypeError):
        return None


def fusionner_lectures(dossier, lectures):
    """Regroupe uniquement les pages d'un document explicitement identifié.

    Les données IA restent à vérifier même après ces contrôles. Aucune fusion
    positionnelle entre deux documents ; pagination imprimée et références
    doivent être cohérentes. Les groupes ambigus restent dans la fiche interne.
    """
    groupes = {}
    for page, lu in lectures:
        meta = lu.get("document")
        if not isinstance(meta, dict):
            dossier.blocages.append(f"Page {page} IA : référence documentaire absente")
            continue
        typ, ref = _texte(meta.get("type")), _texte(meta.get("reference"))
        mrn = _texte(meta.get("mrn"))
        if mrn and mrn != dossier.mrn:
            dossier.blocages.append(f"Page {page} IA : MRN différent de la déclaration")
            continue
        if typ == "transit":
            ref = mrn
        elif mrn != dossier.mrn:
            # La référence d'envoi doit être portée par la déclaration, pas
            # simplement par une autre annexe du même PDF.
            awb = re.sub(r"\D", "", _texte(meta.get("awb")))
            references = [re.sub(r"\D", "", str(val)) for label, val in dossier.entete
                          if label in {"Référence déclaration", "AWB", "Waybill"}]
            if len(awb) < 8 or not any(awb == r or (len(r) > len(awb) and awb in r) for r in references):
                dossier.blocages.append(f"Page {page} IA : référence d'envoi non rapprochée de la déclaration")
                continue
        if not ref:
            dossier.blocages.append(f"Page {page} IA : document sans référence, association impossible")
            continue
        groupes.setdefault((typ, ref, _texte(meta.get("awb"))), []).append((page, lu))
    # Ne pas choisir la facture la plus riche parmi des envois potentiellement distincts.
    utiles = [g for g in groupes.values() if any(lu.get("articles") for _, lu in g)]
    if len(utiles) != 1:
        if utiles:
            dossier.blocages.append("Plusieurs documents IA porteurs de marchandises : rapprochement humain requis")
        return False
    groupe = utiles[0]
    annonces = {_entier_page(lu["document"].get("pages")) for _, lu in groupe}
    if None in annonces or len(annonces) != 1:
        dossier.blocages.append("Pagination IA absente ou contradictoire : complétude non établie")
        return False
    total = next(iter(annonces))
    numeros = [_entier_page(lu["document"].get("page")) for _, lu in groupe]
    if sorted(n for n in numeros if n is not None) != list(range(1, total + 1)):
        dossier.blocages.append("Pages manquantes ou dupliquées dans le document IA")
        return False
    fusion = {"articles": [], "parties": [], "transport": []}
    for page, lu in sorted(groupe, key=lambda pair: _entier_page(pair[1]["document"].get("page"))):
        arts = lu.get("articles", [])
        if not isinstance(arts, list) or any(not isinstance(a, dict) for a in arts):
            dossier.blocages.append(f"Page {page} IA : schéma articles invalide")
            return False
        fusion["articles"].extend(arts)
        if not fusion["parties"] and isinstance(lu.get("parties"), list):
            fusion["parties"] = lu["parties"]
        for i, art in enumerate(arts, 1):
            dossier.preuves.append({"methode": "IA, non validée", "page": page,
                                    "document": lu["document"], "article_page": i,
                                    "champs": dict(art)})
    for cle in ("total_brut", "total_colis"):
        valeurs = {_texte(lu.get(cle)) for _, lu in groupe if _texte(lu.get(cle))}
        if len(valeurs) > 1:
            dossier.blocages.append(f"{cle} contradictoire entre les pages IA")
        elif valeurs:
            fusion[cle] = next(iter(valeurs))
    return appliquer(dossier, fusion)


def completer_dossier(dossier, analyse, cfg, tmp, echo=print):
    """Lit toutes les pages candidates dans la limite du budget explicite.

    Aucune interruption anticipée sur une page « suffisante ». Le dépassement
    du budget et les lectures en échec sont des blocages de livraison.
    """
    conf = configuration(cfg)
    toutes = _pages_a_lire(analyse, {**conf, "max_pages": len(analyse.verdicts)})
    pages = toutes[:max(0, conf["max_pages"])]
    if len(pages) < len(toutes):
        dossier.blocages.append(f"Lecture IA limitée à {len(pages)}/{len(toutes)} pages candidates : complétude non vérifiée")
    dossier.ia_utilisee = True
    contexte = f"Dossier {dossier.dossier or dossier.mrn or '?'}, MRN {dossier.mrn or '?'}"
    lectures = []
    empreintes = set()
    for page in pages:
        try:
            image = pdfio.rendre_page_png(analyse.pdf, page, conf["dpi"], tmp, base=f"ia_{page}")
            if image is None:
                raise ValueError("image absente")
            # Copies strictement identiques : relire ne fournirait aucune preuve indépendante.
            from PIL import Image
            with Image.open(image) as im:
                empreinte = hashlib.sha256(im.convert("RGB").tobytes()).hexdigest()
            if empreinte in empreintes:
                dossier.lectures_ia.append({"page":page,"statut":"copie image identique ignorée"})
                continue
            empreintes.add(empreinte)
            lu = lire_page(image, conf, contexte)
            if not isinstance(lu, dict) or lu.get("_erreur"):
                raise ValueError((lu or {}).get("_erreur", "réponse IA absente") if isinstance(lu, dict) or lu is None else "schéma IA invalide")
            dossier.lectures_ia.append({"fichier":str(analyse.pdf.resolve()),"page":page,"lecture":lu})
            lectures.append((page, lu))
            echo(f"      IA : page {page} conservée pour rapprochement documentaire")
        except Exception as exc:
            dossier.blocages.append(f"Page {page} : lecture IA impossible ({exc})")
    # Une réponse mal formée ne doit pas détruire l'extraction déterministe.
    candidat = copy.deepcopy(dossier)
    try:
        change = fusionner_lectures(candidat, lectures)
    except Exception as exc:
        dossier.blocages.append(f"Fusion IA impossible : {exc}")
        return False
    dossier.__dict__.update(candidat.__dict__)
    if change:
        dossier.confiance = "moyenne"
    return change
