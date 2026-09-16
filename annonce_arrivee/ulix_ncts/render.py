"""Rendu PDF — passe EXCLUSIVEMENT par le script déterministe du skill.

``Documentation/skills/ulix-doc-arrivee-ncts/scripts/generate_doc.py`` est le
seul chemin de rendu autorisé (gabarit figé : fond blanc, accents, code-barres
Code 128 du MRN, cadre CONTRÔLE 3140 sur la dernière page). Ce module ne fait
que traduire les objets ``Dossier`` extraits vers le schéma JSON attendu par ce
script, puis l'invoquer.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import os
import tempfile
from pathlib import Path

from . import plateforme
from .extract import A_VERIFIER, Dossier, formater_kg
from .extract import nombre as _nombre

GABARIT_REL = Path("Documentation/skills/ulix-doc-arrivee-ncts/scripts/generate_doc.py")

# métadonnées communes à plusieurs MRN : écrites une seule fois en mode multiple
_LIBELLES_COMMUNS = {"Annonce DA", "Référence", "Date acceptation", "Déclarant",
                     "Dossier", "Statut douane"}


def trouver_gabarit(depuis: Path) -> Path | None:
    """Cherche generate_doc.py en remontant l'arborescence."""
    for base in [depuis, *depuis.parents]:
        for rel in (GABARIT_REL,
                    Path("ulix-ncts-arrivee/skills/ulix-doc-arrivee-ncts/scripts/generate_doc.py"),
                    Path("skills/ulix-doc-arrivee-ncts/scripts/generate_doc.py")):
            cand = base / rel
            if cand.is_file():
                return cand
    return None


def _entete(d: Dossier, mrn_affiche: str) -> list[list[str]]:
    lignes = [["MRN", mrn_affiche]]
    deja = {lbl.lower() for lbl, _ in d.entete}
    for lbl, val in d.entete:
        if lbl.lower() not in deja or True:
            lignes.append([lbl, val])
    # dédoublonne MRN si déjà porté
    vus, out = set(), []
    for lbl, val in lignes:
        cle = (lbl.lower(), str(val))
        if cle in vus:
            continue
        vus.add(cle)
        out.append([lbl, str(val)])
    return out


def dossiers_vers_data(dossiers: list[Dossier], cfg: dict) -> dict:
    """Traduit 1..N dossiers extraits vers le schéma de generate_doc.py."""
    principal = dossiers[0]
    multiple = len(dossiers) > 1
    mrns = [d.mrn for d in dossiers if d.mrn]
    mrn_barcode = " / ".join(mrns) if mrns else (principal.dm or A_VERIFIER)
    dm = principal.dm or A_VERIFIER
    dossier_str = principal.dossier or principal.mrn or ""

    # --- en-tête page 1 : un bloc par dossier ---------------------------------
    # En mode multiple, les libellés restent COURTS (pas de préfixe MRN : il
    # provoquerait un chevauchement label/valeur) ; le MRN est porté sur sa
    # propre ligne, et les métadonnées communes (annonce, date) ne sont écrites
    # qu'une seule fois. Deux MRN partageant la même valeur (même bureau de
    # destination, même référence) ne l'affichent qu'une fois.
    entete: list[list[str]] = []
    valeurs_vues: set[tuple[str, str]] = set()
    for d in dossiers:
        if d.mrn:
            entete.append(["MRN", d.mrn])
        for lbl, val in d.entete:
            if lbl == "MRN":
                continue
            if multiple and (lbl, str(val)) in valeurs_vues:
                continue
            valeurs_vues.add((lbl, str(val)))
            entete.append([lbl, str(val)])
    if not entete:
        entete = [["MRN", mrn_barcode]]

    # Toutes les parties, identifiées par déclaration en mode multiple.
    parties = []
    for d in dossiers:
        for partie in d.parties:
            item = dict(partie)
            if multiple:
                item["role"] = f"{item.get('role', 'Partie')} [{d.mrn or A_VERIFIER}]"
            parties.append(item)

    # --- transport : récapitulatif cumulé (colis, masse, articles) ---------
    # Les valeurs individuelles gardent leur MRN ; les totaux sont distincts.
    transport: list[list[str]] = []
    vus: set[tuple[str, str, str]] = set()
    for d in dossiers:
        for lbl, val in d.transport:
            cle = (lbl, str(val), d.mrn if multiple else "")
            if cle in vus:
                continue
            vus.add(cle)
            transport.append([lbl, f"{val} [{d.mrn}]" if multiple else str(val)])
    colis_total = _somme(d.total.get("colis") for d in dossiers)
    masse_total = _somme_nombre(d.total.get("brut") for d in dossiers)
    nb_articles = sum(len(d.articles) for d in dossiers)
    # lignes de synthèse : on n'ajoute une ligne que si elle n'est pas déjà
    # portée à l'identique par le transport du dossier (évite les doublons)
    def _ajouter(libelle: str, valeur: str) -> None:
        if valeur and not any(l == libelle and v == valeur for l, v in transport):
            transport.append([libelle, valeur])

    if nb_articles:
        _ajouter("Nbre d'articles", str(nb_articles))
    if colis_total:
        _ajouter("Nbre de colis", str(colis_total))
    if masse_total is not None:
        _ajouter("Masse brute totale", formater_kg(masse_total))
    if multiple:
        _ajouter("MRN du dépôt", ", ".join(mrns) or A_VERIFIER)

    # --- articles : concaténés, renumérotés, MRN rappelé si multiple --------
    articles = []
    for d in dossiers:
        for a in d.articles:
            item = {"no": str(len(articles) + 1), "designation": a.designation or A_VERIFIER,
                    "code_nc": a.code_nc or A_VERIFIER, "brut": a.brut or A_VERIFIER, "net": a.net or A_VERIFIER, "colis": a.colis or A_VERIFIER}
            if a.marques:
                item["marques"] = a.marques
            if a.doc_prec:
                item["doc_prec"] = a.doc_prec
            if a.justif:
                item["justif"] = a.justif
            if multiple and d.mrn:
                item["designation"] = f"{item['designation']} [{d.mrn}]".strip()
            articles.append(item)

    total: dict = {"brut": A_VERIFIER, "colis": A_VERIFIER}
    if masse_total is not None:
        total["brut"] = formater_kg(masse_total)
    if colis_total:
        total["colis"] = f"{colis_total} colis"

    nets = [_nombre(d.total.get("net")) for d in dossiers]
    if nets and all(n is not None for n in nets):
        total["net"] = formater_kg(sum(nets))

    # Provenance documentaire et méthode de lecture restent distinctes dans
    # le JSON interne. Le gabarit ne les imprime pas sur le document client.
    _TECHNIQUE = ("lecture ia", "extraction", "en échec", "repli ia", "échec")
    sources = [d.source_marchandises for d in dossiers if d.source_marchandises]
    clients = [s for s in sources if not any(t in s.lower() for t in _TECHNIQUE)]
    techniques = [s for s in sources if any(t in s.lower() for t in _TECHNIQUE)]
    source_client = " | ".join(dict.fromkeys(clients))
    source_interne = " | ".join(dict.fromkeys(techniques))
    if multiple and len(dossiers) > 1:
        # mention factuelle, utile pour un dépôt regroupant plusieurs déclarations
        source_client = (f"Dépôt multiple : {len(dossiers)} déclarations de transit. " + source_client)
    ecarts = list(dict.fromkeys(d.ecart for d in dossiers if d.ecart))
    avertissements = [f"{d.mrn or '?'} : {a}" for d in dossiers for a in d.avertissements]

    data: dict = {
        "ncts_key": dm or mrn_barcode,
        "mrn": mrn_barcode,
        # liste des MRN, pour dessiner UN code-barres par déclaration : en dépôt
        # multiple, concaténer les MRN dans un seul code-barres le rendait
        # indécodable par un lecteur.
        "mrns": mrns,
        "codes_barres": list(dict.fromkeys(code for d in dossiers
            for code in (d.codes_annonce if d.annonce_originale else [d.mrn]) if code)),
        "type": principal.type or "",
        "dm": dm,
        "dossier": dossier_str,
        "date": principal.date or "",
        "entete": entete,
        "parties": parties,
        "transport": transport,
        "articles": articles,
        "total": total,
        "source_marchandises": source_client,
        "controle": {
            "numero": cfg["document"]["numero_controle"],
            "dossier": dossier_str,
            "dm": dm,
            "ref_transit": " / ".join(mrns) if multiple else (principal.mrn or ""),
        },
    }
    if source_interne:
        data["source_interne"] = source_interne
    if ecarts:
        data["ecart"] = " | ".join(ecarts)
    if any(not d.total.get("brut") or not d.total.get("colis") for d in dossiers):
        avertissements.append("Totaux incomplets : aucune somme partielle n'est présentée comme un total.")
    if avertissements:
        data["avertissements"] = avertissements
    return data


def _somme(valeurs) -> int:
    total = 0
    for v in valeurs:
        m = re.fullmatch(r"\s*(\d+)\s*(?:colis|[A-Z]{2,3})?\s*", str(v or ""))
        if not m:
            return 0
        total += int(m.group(1))
    return total


def _somme_nombre(valeurs) -> float | None:
    total, vu = 0.0, False
    for v in valeurs:
        n = _nombre(v)
        if n is None:
            return None
        total += n
        vu = True
    return total if vu else None


def generer(data: dict, sortie: Path, gabarit: Path,
            dossier_data: Path | None = None) -> tuple[bool, str]:
    """Appelle generate_doc.py (seul chemin de rendu autorisé).

    Le script du skill requiert reportlab : on privilégie l'interpréteur du venv
    du projet (créé par installer.command) pour que le rendu fonctionne quel que
    soit le python courant.

    Le `data.json` est le fichier d'échange lu par le gabarit : il est écrit dans
    `dossier_data` quand celui-ci est fourni, pour ne pas encombrer le dossier des
    annonces, qui ne doit contenir que les PDF remis au client.
    """
    dossier_data = dossier_data or sortie.parent
    dossier_data.mkdir(parents=True, exist_ok=True)
    json_path = dossier_data / (sortie.stem + ".json")
    json_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    python = _python_du_projet(gabarit)
    with tempfile.TemporaryDirectory(prefix=".rendu-", dir=sortie.parent) as td:
        temporaire = Path(td) / sortie.name
        try:
            cp = subprocess.run([python, str(gabarit), str(json_path), str(temporaire)],
                                capture_output=True, text=True, errors="replace", timeout=120,
                                env=plateforme.environnement_sous_processus())
        except (OSError, subprocess.TimeoutExpired) as exc:
            return False, str(exc)
        ok = cp.returncode == 0 and temporaire.is_file() and temporaire.read_bytes()[:5] == b"%PDF-"
        if ok:
            os.replace(temporaire, sortie)
        return ok, (cp.stderr or cp.stdout or "").strip()


def _python_du_projet(gabarit: Path) -> str:
    """Interpréteur à utiliser : le venv du projet s'il a reportlab, sinon un système.

    Le chemin du venv diffère selon la plateforme (``bin/python3`` sur macOS,
    ``Scripts\\python.exe`` sur Windows) : la résolution est déléguée à
    `plateforme`, qui regarde les deux et remonte l'arborescence.
    """
    env = plateforme.environnement_sous_processus()
    for base in (gabarit, *gabarit.parents):
        for candidat in _candidats_python(base):
            try:
                cp = subprocess.run([str(candidat), "-c", "import reportlab"],
                                    capture_output=True, env=env)
                if cp.returncode == 0:
                    return str(candidat)
            except OSError:
                pass
    return plateforme.python_systeme() or sys.executable


def _candidats_python(base: Path):
    """Interpréteurs candidats, du plus probable au plus général.

    1. le venv à côté de CE module (``annonce_arrivee/.venv``) : c'est le cas
       normal, et le seul qui ne dépende pas de l'endroit d'où l'on appelle ;
    2. le venv trouvé en remontant depuis `base` ;
    3. les interpréteurs du système.

    Le rendu teste chaque candidat avec `import reportlab` : on ne retient que
    celui qui sait réellement produire le PDF.
    """
    ici = Path(__file__).resolve().parent.parent          # annonce_arrivee/
    for depart in (ici, base, *base.parents):
        trouve = plateforme.chercher_python(depart, profondeur=0)
        if trouve:
            yield trouve
    if base != ici:
        trouve = plateforme.chercher_python(base, profondeur=1)
        if trouve:
            yield trouve
    for nom in ("python3", "python", "py"):
        exe = shutil.which(nom)
        if exe:
            yield Path(exe)


def verifier_rendu(pdf: Path, dpi: int = 110, data: dict | None = None) -> dict:
    """Contrôle visuel automatique minimal (étape 9 du skill) : fond blanc sans
    aplat, accents présents, pas de dépassement de marge."""
    rapport = {"pages": 0, "accents": False, "aplat": False, "ok": False, "erreurs": []}
    try:
        from PIL import Image
    except Exception:
        rapport["erreurs"].append("Pillow absent : validation du rendu impossible")
        return rapport

    import tempfile

    from . import pdfio

    with tempfile.TemporaryDirectory() as td:
        d = Path(td)
        n = pdfio.nombre_pages(pdf)
        rapport["pages"] = n
        for p in range(1, n + 1):
            png = pdfio.rendre_page_png(pdf, p, dpi, d, base=f"v{p}")
            if not png:
                rapport["erreurs"].append(f"page {p} non rendue")
                continue
            img = Image.open(png).convert("RGB")
            w, h = img.size
            # aplat de couleur : bord haut entièrement non blanc
            bord = [img.getpixel((x, 3)) for x in range(0, w, max(w // 40, 1))]
            if sum(1 for px in bord if sum(px) < 600) > len(bord) * 0.8:
                rapport["aplat"] = True
        texte = pdfio.couche_texte(pdf, 1)
        rapport["accents"] = bool(("é" in texte) or ("è" in texte) or ("à" in texte))
        import xml.etree.ElementTree as ET
        textes = [pdfio.couche_texte(pdf, p) for p in range(1, n + 1)]
        normaliser = lambda s: re.sub(r"\s+", "", str(s))
        # -raw conserve l'ordre des tracés : le mode lecture entrelace les
        # colonnes numériques avec les désignations sur plusieurs lignes.
        brut = pdfio._txt(pdfio._run(["pdftotext", "-raw", str(pdf), "-"]))
        tout = normaliser(brut)
        if n < 2:
            rapport["erreurs"].append("moins de deux pages")
        if "CONTRÔLE" not in (textes[-1] if textes else ""):
            rapport["erreurs"].append("cadre contrôle absent de la dernière page")
        if data:
            attendus = [data.get("dm", ""), *data.get("mrns", [])]
            attendus += [a.get("designation", "") for a in data.get("articles", [])]
            for attendu in attendus:
                if attendu and normaliser(attendu) not in tout:
                    rapport["erreurs"].append(f"texte absent : {attendu}")
        for p in range(1, n + 1):
            try:
                arbre = ET.fromstring(pdfio.texte_bbox(pdf, p))
                for page in arbre.iter():
                    if page.tag.rsplit("}", 1)[-1] != "page":
                        continue
                    w, h = float(page.attrib["width"]), float(page.attrib["height"])
                    for mot in page.iter():
                        if mot.tag.rsplit("}", 1)[-1] == "word" and (
                            float(mot.attrib["xMin"]) < 0 or float(mot.attrib["yMin"]) < 0 or
                            float(mot.attrib["xMax"]) > w or float(mot.attrib["yMax"]) > h):
                            rapport["erreurs"].append(f"texte hors page {p}")
            except (ET.ParseError, KeyError, ValueError):
                rapport["erreurs"].append(f"géométrie page {p} non vérifiable")
        rapport["ok"] = (not rapport["aplat"]) and rapport["accents"] and not rapport["erreurs"]
    return rapport
