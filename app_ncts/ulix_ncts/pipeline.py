"""Orchestration : scanner un dépôt, extraire, générer les annonces d'arrivée.

Règles métier appliquées :

  * ``Dépots unique``   : 1 fichier PDF  -> 1 annonce d'arrivée ;
  * ``Dépots multiple`` : N fichiers PDF -> 1 annonce d'arrivée unique
    (toutes les références du dossier figurent sur le document et dans le cadre
    CONTRÔLE).

Toutes les pages des PDF déposés sont classées. Les pièces hors sujet (waybills,
factures, e-mails, déclarations d'export EX1/EAD, pages de garde DHL) sont
écartées du document mais restent exploitées comme source de triangulation
(désignation et poids net du waybill DHL) — et sont listées dans le rapport.
"""

from __future__ import annotations

import re
import hashlib
import shutil
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from . import classify, cw_client, extract, fsutil, ia, pdfio, render, qualite
from .classify import Verdict
from .extract import A_VERIFIER, Article, Dossier

# --------------------------------------------------------------------- modèles
@dataclass
class Analyse:
    pdf: Path
    sha256: str = ""
    verdicts: list[Verdict] = field(default_factory=list)
    dossiers: list[Dossier] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)

    @property
    def pages_transit(self) -> list[int]:
        return [v.page for v in self.verdicts if v.transport]

    @property
    def pages_ecartees(self) -> list[Verdict]:
        return [v for v in self.verdicts if not v.transport]


@dataclass
class Resultat:
    mode: str
    depots: list[Path] = field(default_factory=list)
    analyses: list[Analyse] = field(default_factory=list)
    sorties: list[Path] = field(default_factory=list)
    messages: list[str] = field(default_factory=list)
    rapports: list[Path] = field(default_factory=list)
    archives: list[Path] = field(default_factory=list)
    echecs: list[Path] = field(default_factory=list)
    a_verifier: list[Path] = field(default_factory=list)
    fiches: list[Path] = field(default_factory=list)
    modifiables: list[Path] = field(default_factory=list)
    sources_modifiables: list[Path] = field(default_factory=list)
    modifiables_avec_reserves: list[Path] = field(default_factory=list)


# ------------------------------------------------------------------- utilitaires
RE_DM_FICHIER = re.compile(r"(?i)\bDM\b[\s_\-:]*([A-Z]{2,6}[\s_\-]?\d{4,})")
RE_PMP = re.compile(r"(?i)\b(PMP)[\s_\-]?(\d{4,})")
# le MRN peut être collé à un préfixe (« ..._26CH09Y7… ») : on n'exige pas de
# limite de mot avant (le « _ » du nom de fichier est un caractère de mot)
RE_MRN_FICHIER = re.compile(r"(?<![0-9A-Z])(\d{2}[A-Z]{2}[0-9A-Z]{12,16})(?![0-9A-Z])")


def dm_depuis_nom(pdf: Path) -> str:
    stem = pdf.stem
    m = RE_PMP.search(stem)
    if m:
        return f"PMP {m.group(2)}"
    m = RE_DM_FICHIER.search(stem)
    if m:
        return re.sub(r"[\s_\-]+", " ", m.group(1)).strip()
    return ""


def mrn_depuis_nom(pdf: Path) -> str:
    m = RE_MRN_FICHIER.search(pdf.stem.upper())
    return extract.normaliser_mrn(m.group(1)) if m else ""


def date_iso_fr(valeur: str) -> str:
    """« 2026-07-24 » ou « 06.08.2026, 07:16 » -> « 24.07.2026 »."""
    if not valeur:
        return ""
    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", valeur)
    if m:
        return f"{m.group(3)}.{m.group(2)}.{m.group(1)}"
    m = re.search(r"(\d{2})[./](\d{2})[./](\d{4})", valeur)
    if m:
        return f"{m.group(1)}.{m.group(2)}.{m.group(3)}"
    return valeur


def fichiers_pdf(dossier: Path) -> list[Path]:
    if not dossier.is_dir():
        return []
    return sorted(p for p in dossier.iterdir()
                  if p.is_file() and p.suffix.lower() == ".pdf"
                  and not p.name.startswith("._"))


def _chiffres(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def _distance(a: str, b: str) -> int:
    if not a or not b or abs(len(a) - len(b)) > 3:
        return 99
    prec = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prec[j] + 1, cur[j - 1] + 1, prec[j - 1] + (ca != cb)))
        prec = cur
    return prec[-1]


def _date_pdf(pdf: Path) -> str:
    out = _texte_pdfinfo(pdf)
    m = re.search(r"^CreationDate:\s+(\S+)", out, re.M)
    if not m:
        return ""
    m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", m.group(1))
    return m2.group(0) if m2 else ""


def _texte_pdfinfo(pdf: Path) -> str:
    """`pdfinfo` via le point de passage unique de `pdfio` (résolution du binaire,
    environnement adapté), plutôt qu'un `subprocess` direct : sur Windows, pdfinfo
    est souvent installé hors du PATH."""
    return pdfio._txt(pdfio._run(["pdfinfo", str(pdf)]))


# --------------------------------------------------------- classification pages
def classer_pages(pdf: Path, cfg: dict) -> list[Verdict]:
    dpi = int(cfg["traitement"]["dpi_ocr"])
    langue = cfg["traitement"].get("langue_ocr", "eng")
    verdicts: list[Verdict] = []
    for p in range(1, pdfio.nombre_pages(pdf) + 1):
        txt = pdfio.couche_texte(pdf, p)
        famille, pos, neg, detail = classify.classer(txt)
        source = "texte"
        if len(txt.strip()) < 40 or famille == "INDETERMINE":
            otxt = pdfio.ocr_bandeau_haut(pdf, p, dpi, langue)
            of, op, on, od = classify.classer(otxt)
            rang = {"INDETERMINE": 0, "ENVELOPPE": 1, "ANNEXE": 1, "EXPORT": 2,
                    "TRANSIT_LISTE": 3, "TRANSIT_TAD": 3, "TRANSIT_TCH": 3,
                    "TRANSIT_FR": 3, "ANNONCE_CW": 3, "ANNONCE_CW_INV": 3,
                    "ANNONCE_CW_LISTE": 3}
            if rang.get(of, 0) > rang.get(famille, 0) or op > pos:
                famille, pos, neg, detail, source = of, op, on, od, "ocr-bandeau"
        verdicts.append(Verdict(page=p, famille=famille, source=source,
                                score_pos=pos, score_neg=neg, detail=detail,
                                mrn=classify.mrn_depuis_texte(txt)))
    return verdicts


# ------------------------------------------------------------------ analyse PDF
def analyser_pdf(pdf: Path, cfg: dict, tmp: Path,
                 cw_entete: dict | None = None) -> Analyse:
    """Analyse complète d'un PDF de dépôt -> 0..N dossiers de transit."""
    an = Analyse(pdf=pdf, sha256=hashlib.sha256(pdf.read_bytes()).hexdigest())
    an.verdicts = classer_pages(pdf, cfg)
    an.messages.append(
        f"{len(an.verdicts)} page(s) — transit {an.pages_transit or 'aucune'} / "
        f"écartées {[v.page for v in an.pages_ecartees] or 'aucune'}")
    if not an.pages_transit:
        an.messages.append("AUCUNE page de transit reconnue — fichier ignoré")
        return an

    from . import relecture
    relus = relecture.charger(pdf, an.sha256)
    if relus is not None:
        an.dossiers = relus
        an.messages.append("Relecture visuelle enregistrée appliquée (empreinte SHA-256 identique)")
        if cw_entete:
            _appliquer_cw(relus, cw_entete)
        for d in relus:
            _croiser(d)
        return an

    # Corroborer les identifiants AVANT de rattacher les listes à l'en-tête.
    pages_codes = [v.page for v in an.verdicts if v.famille in
                   {"TRANSIT_TAD", "TRANSIT_LISTE", "TRANSIT_TCH", "TRANSIT_FR", "ANNONCE_CW", "ANNONCE_CW_INV"}]
    codes, incident = qualite.codes_mrn(pdf, pages_codes, tmp)
    if incident:
        an.messages.append(incident)

    # --- waybills : un envoi par PDF (les fragments d'un même waybill sont fusionnés)
    waybills = _collecter_waybills(pdf, an.verdicts)
    waybill = _fusionner_waybills(waybills)
    dossiers: list[Dossier] = []
    dossiers += _dossiers_tad(pdf, an.verdicts, cfg, tmp, codes)
    dossiers += _dossiers_tch(pdf, an.verdicts, waybills, waybill)
    dossiers += _dossiers_tad_fr(pdf, an.verdicts)
    cw_dossiers = _dossiers_cw1(pdf, an.verdicts, tmp)
    if cw_dossiers:
        dossiers = _fusionner(dossiers, cw_dossiers)

    # Vérification optique des en-têtes seulement, jamais des déclarations export.
    pages_entete = [v.page for v in an.verdicts if v.famille in
                    {"TRANSIT_TAD", "TRANSIT_TCH", "TRANSIT_FR", "ANNONCE_CW", "ANNONCE_CW_INV"}]
    tous_codes = {m for page, valeurs in codes.items() if page in pages_entete for m in valeurs}
    for d in dossiers:
        mrn_nom = mrn_depuis_nom(pdf)
        if len(dossiers) == 1 and len(tous_codes) == 1:
            code = next(iter(tous_codes))
            if code == d.mrn or code == mrn_nom:
                ancien = d.mrn
                d.mrn = code
                d.mrn_verifie = True
                if ancien != code:
                    d.avertissements.append(f"MRN OCR « {ancien} » rectifié par code-barres et nom de fichier « {code} »")
            else:
                d.blocages.append("Code-barres MRN différent du texte et du nom du fichier")
        elif len(dossiers) > 1 and d.mrn and d.mrn in tous_codes:
            d.mrn_verifie = True
        elif len(tous_codes) > 1:
            d.blocages.append("Plusieurs MRN décodés pour une seule déclaration : association ambiguë")
        d.preuves.append({"fichier": str(pdf.resolve()), "pages_candidates": an.pages_transit,
                          "methode": "extraction déterministe", "codes_barres": codes,
                          "mrn_nom_fichier": mrn_nom,
                          "champs": {"mrn": d.mrn, "dm": d.dm, "total": dict(d.total),
                                     "articles": [vars(a).copy() for a in d.articles]},
                          "precision": "pages candidates, localisation du champ à contrôler"})

    if cw_entete:
        # le MRN et le DM du document doivent être résolus AVANT l'enrichissement :
        # sinon `_appliquer_cw` compare un MRN vide et applique à tort l'en-tête
        # d'une autre déclaration (mélange de dossiers sur le document).
        for d in dossiers:
            _resoudre_identifiants(d, pdf)
        _appliquer_cw(dossiers, cw_entete)

    for d in dossiers:
        _finaliser(d, pdf)
        _croiser(d)

    # --- repli IA : uniquement sur les dossiers que le déterministe a ratés ----
    # Le chemin normal (pdftotext + PaddleOCR) reste la règle ; le modèle n'est
    # sollicité que sur les cas qu'il est seul à pouvoir lire (scan dégradé,
    # tableau de facture illisible). Un échec IA ne bloque jamais la production.
    if len(dossiers) > 1:
        an.messages.append("Repli IA non appliqué : plusieurs déclarations dans le PDF ; association des annexes à vérifier")
    if len(dossiers) == 1 and ia.disponible(cfg):
        for d in dossiers:
            if any("plusieurs waybills annexés" in message for message in d.avertissements):
                an.messages.append("Repli IA non appliqué : plusieurs envois annexés ; une facture seule ne peut compléter le total du transit")
                continue
            if _lacunaire(d):
                d.avertissements.append("relecture par IA des pages mal lues")
                if ia.completer_dossier(d, an, cfg, tmp, echo=an.messages.append):
                    _croiser(d)
                    an.messages.append(
                        f"    IA : dossier {d.dossier or d.mrn} complété "
                        f"({len(d.articles)} ligne(s))")
                else:
                    an.messages.append(
                        f"    IA : aucune donnée supplémentaire pour "
                        f"{d.dossier or d.mrn}")

    if hashlib.sha256(pdf.read_bytes()).hexdigest() != an.sha256:
        for d in dossiers:
            d.blocages.append("Fichier source modifié pendant l'analyse : retraitement requis")
    an.dossiers = dossiers
    if not dossiers:
        an.messages.append("pages de transit détectées mais aucune donnée exploitable")
    return an


def _collecter_waybills(pdf: Path, verdicts: list[Verdict]) -> list[dict]:
    """Waybills DHL du dépôt, indexés par MRN quand celui-ci est reconnaissable.

    Le waybill ne porte pas toujours le MRN du transit : on retient alors les
    chiffres de la référence de déclaration (partagés avec le n° de waybill) pour
    l'appariement, et on garde la page pour le contrôle croisé.
    """
    waybills = []
    for v in verdicts:
        if v.transport:
            continue
        plat = pdfio.couche_texte_layout(pdf, v.page)
        wb = extract.extraire_waybill_dhl(plat)
        if wb.get("designation") or wb.get("poids_net") or wb.get("waybill"):
            wb["page"] = v.page
            # chiffres de la référence de la déclaration, si présents sur la page
            m = re.search(r"(?i)r[ée]f[ée]rence\s*:?\s*([^\n]+)", plat)
            wb["reference"] = extract.nettoyer(m.group(1)) if m else ""
            waybills.append(wb)
    return waybills


def _fusionner_waybills(waybills: list[dict]) -> dict | None:
    """Fusionne les fragments d'un même envoi, sans mélanger les annexes.

    Un dépôt contient le waybill DHL de l'envoi ET des annexes possiblement
    étrangères à celui-ci (facture proforma d'une autre expédition, fiche
    produit). On regroupe donc les fragments par numéro d'envoi (waybill/AWB) :
    chaque groupe est fusionné séparément, puis on retient le groupe le plus
    complet — celui qui porte à la fois une désignation, les poids et un numéro.
    Les fragments sans numéro rejoignent le groupe principal.
    """
    if not waybills:
        return None
    groupes: dict[str, list[dict]] = {}
    for wb in waybills:
        cle = wb.get("waybill") or wb.get("reference") or "_"
        groupes.setdefault(_chiffres(cle) or "_", []).append(wb)
    meilleur: dict = {}
    meilleure_note = -1
    for fragments in groupes.values():
        fusion = _fusionner_fragments(fragments)
        note = sum(1 for c in ("designation", "poids_net", "poids_brut", "waybill")
                   if fusion.get(c))
        if note > meilleure_note:
            meilleur, meilleure_note = fusion, note
    return meilleur or None


def _fusionner_fragments(fragments: list[dict]) -> dict:
    """Agrège les champs d'un même envoi (premier fragment porteur du champ)."""
    fusion: dict = {}
    for wb in fragments:
        for cle in ("designation", "poids_net", "poids_brut", "waybill",
                    "reference", "colis_waybill", "valeur"):
            val = wb.get(cle)
            if not val or fusion.get(cle):
                continue
            if cle == "designation" and not _designation_plausible(val):
                continue
            fusion[cle] = val
    return fusion


def _designation_plausible(val: str) -> bool:
    v = str(val or "").strip()
    if len(v) < 6 or not re.search(r"[A-Za-z]{4,}", v):
        return False
    if re.match(r"^[\d\s.,]+$", v):
        return False
    return not re.match(r"(?i)^(?:cust|shpt|gross|net|total|value|awb|page|dhl)\b", v)


def _note_designation(val: str) -> int:
    """Score d'une désignation : nombre de mots alphabétiques utiles."""
    return len(re.findall(r"[A-Za-z]{3,}", str(val or "")))


def _waybill_pour(waybills: list[dict], mrn: str, reference: str) -> dict | None:
    """Rapproche un waybill de son transit par les chiffres partagés.

    Trois pistes, dans l'ordre : le MRN du waybill contient le MRN du transit ;
    le n° de waybill et la référence de déclaration partagent leur partie
    numérique ; à défaut, un waybill unique dans le fichier s'applique au seul
    transit présent.
    """
    chiffres_mrn = _chiffres(mrn)
    chiffres_ref = _chiffres(reference)
    for wb in waybills:
        w = _chiffres(wb.get("waybill", ""))
        r = _chiffres(wb.get("reference", ""))
        if w and chiffres_mrn and (w[-9:] == chiffres_mrn[-9:] or w in mrn):
            return wb
        if w and chiffres_ref and len(w) >= 8 and w[-8:] in chiffres_ref:
            return wb
        if r and chiffres_mrn and len(r) >= 10 and r[-10:] == chiffres_mrn[-10:]:
            return wb
    return None


# ------------------------------------------------------------- TAD UE (TR1/TR2)
def _dossiers_tad(pdf: Path, verdicts: list[Verdict], cfg: dict,
                  tmp: Path, codes: dict | None = None) -> list[Dossier]:
    dpi = int(cfg["traitement"]["dpi_ocr"])
    out: list[Dossier] = []
    entetes = [v for v in verdicts if v.famille == "TRANSIT_TAD"]
    listes = sorted((v for v in verdicts if v.famille == "TRANSIT_LISTE"),
                    key=lambda v: v.page)
    reference = mrn_depuis_nom(pdf)
    for v in entetes:
        faits = extract.extraire_tad_entete(pdf, v.page, reference)
        d = Dossier(mrn=faits.get("mrn", ""), type=faits.get("type", ""),
                    date=date_iso_fr(faits.get("date", "")),
                    dm=dm_depuis_nom(pdf))
        optiques = (codes or {}).get(v.page, [])
        if len(optiques) == 1 and optiques[0] in {d.mrn, reference}:
            ancien = d.mrn
            d.mrn = optiques[0]
            d.mrn_verifie = True
            if ancien != d.mrn:
                d.avertissements.append(f"MRN OCR « {ancien} » rectifié par code-barres et nom de fichier « {d.mrn} » avant association des listes")
        d.fichiers.append(pdf.name)
        d.ajouter_entete("Pays de destination", faits.get("pays_dest"))
        d.ajouter_entete("Terme ultime", faits.get("terme_ultime"))
        d.ajouter_entete("Garantie", faits.get("garantie"))
        d.ajouter_entete("Bureau de départ", faits.get("bureau_depart"))
        d.ajouter_entete("Bureau de destination", faits.get("bureau_dest"))
        d.parties.extend(faits.get("parties") or [])
        colis = _chiffres(faits.get("colis_total"))
        masse = extract.nombre(faits.get("masse_totale"))
        if faits.get("vehicule"):
            d.transport.append(["Véhicule / mode", faits["vehicule"] + " — Route"])
        if faits.get("scelles"):
            d.transport.append(["Scellés", faits["scelles"]])
        if colis:
            d.transport.append(["Nbre de colis", colis])
            d.total["colis"] = f"{colis} colis"
        if masse is not None:
            d.transport.append(["Masse brute totale", extract.formater_kg(masse)])
            d.total["brut"] = extract.formater_kg(masse)
        # Les listes appartiennent au bloc de cet en-tête uniquement.
        borne = min((x.page for x in verdicts if x.page > v.page and
                     x.famille in {"TRANSIT_TAD", "TRANSIT_TCH", "TRANSIT_FR", "ANNONCE_CW"}),
                    default=float("inf"))
        for lv in [x for x in listes if v.page < x.page < borne]:
            lus_liste = (codes or {}).get(lv.page, [])
            if len(lus_liste) > 1:
                d.avertissements.append(f"page {lv.page} : plusieurs codes-barres MRN, liste non associée")
                continue
            identifiant_liste = lus_liste[0] if len(lus_liste) == 1 else lv.mrn
            if identifiant_liste and d.mrn and identifiant_liste != d.mrn:
                d.avertissements.append(f"page {lv.page} : MRN différent, liste non associée")
                continue
            arts = extract.extraire_liste_std(pdf, lv.page)
            if arts:
                for art in arts:
                    art.no = str(len(d.articles) + 1)
                    d.articles.append(art)
                continue
            art = extract.extraire_tad_articles(pdf, lv.page, dpi, tmp)
            if art:
                art.no = str(len(d.articles) + 1)
                d.articles.append(art)
        declared = _chiffres(faits.get("articles_total"))
        if declared and len(d.articles) != int(declared):
            d.ecart = (f"nombre d'articles déclaré {declared} vs "
                       f"{len(d.articles)} page(s) de liste lue(s) — à vérifier")
        d.source_marchandises = (
            f"Reprise du document de transit {d.type or 'TAD'}"
            + (f" (MRN {d.mrn})" if d.mrn else "")
            + (f", déposé le {d.date}" if d.date else ""))
        out.append(d)
    return out


# ------------------------------------------------- transit national CH (OFDF)
def _dossiers_tch(pdf: Path, verdicts: list[Verdict],
                  waybills: list[dict], waybill: dict | None) -> list[Dossier]:
    out: list[Dossier] = []
    for v in [x for x in verdicts if x.famille == "TRANSIT_TCH"]:
        plat = pdfio.couche_texte_layout(pdf, v.page)
        faits = extract.extraire_tch(plat)
        d = Dossier(mrn=faits.get("mrn", ""), type="TCH",
                    date=date_iso_fr(faits.get("date", "")),
                    dm=dm_depuis_nom(pdf))
        d.fichiers.append(pdf.name)
        d.ajouter_entete("Bureau de destination", faits.get("bureau_dest"))
        d.ajouter_entete("Référence déclaration", faits.get("reference"))
        d.ajouter_entete("Déclaration acceptée", faits.get("date"))
        for role, adr in (("Expéditeur", faits.get("expediteur")),
                          ("Destinataire", faits.get("destinataire"))):
            if adr:
                d.parties.append({"role": role, "lignes": adr})
        colis = _chiffres(faits.get("emballages"))
        masse = extract.nombre(faits.get("masse_brute"))
        if colis:
            d.transport.append(["Nbre de colis", colis])
            d.total["colis"] = f"{colis} colis"
        if masse is not None:
            d.transport.append(["Masse brute totale", extract.formater_kg(masse)])
            d.total["brut"] = extract.formater_kg(masse)

        art = Article(no="1", colis=f"{colis} colis" if colis else "",
                      brut=extract.formater_kg(masse) if masse is not None else "")
        # le waybill DHL est le seul porteur de la désignation pour un TCH ; il
        # est indexé par page, et un fichier de dépôt = un envoi
        wb = _waybill_pour(waybills, d.mrn, faits.get("reference", ""))
        # Un repli sans référence n'est sûr que pour un seul transit et un seul envoi.
        groupes = {w.get("waybill") or w.get("reference") for w in waybills
                   if w.get("waybill") or w.get("reference")}
        if not wb and len([x for x in verdicts if x.famille == "TRANSIT_TCH"]) == 1 and len(groupes) <= 1:
            wb = waybill
        if len(groupes) > 1:
            # Un bordereau associé ne décrit pas à lui seul un transit groupé.
            wb = None
            d.avertissements.append("plusieurs waybills annexés : inventaire complet à rapprocher du transit ; aucune désignation partielle attribuée au total")
        if wb:
            art.designation = wb.get("designation") or A_VERIFIER
            if wb.get("poids_net"):
                art.net = extract.formater_kg(wb["poids_net"])
            art.doc_prec = f"Waybill DHL {wb.get('waybill', '')}".strip()
            # Pas de note « justif » ici : la justification du colisage et des
            # masses est une TRACE INTERNE de fabrication (elle explique d'où
            # viennent les valeurs). Elle reste dans le rapport ; le document
            # remis au client ne porte que les références imprimées sur le
            # document lui-même (waybill, N830/N325).
            d.source_marchandises = (
                f"Déclaration de transit national OFDF (GDRN {d.mrn}) + désignation et "
                f"poids du waybill DHL {wb.get('waybill', '')}")
            brut_wb = extract.nombre(wb.get("poids_brut"))
            if brut_wb is not None and masse is not None and abs(brut_wb - masse) > 0.05:
                d.ecart = (f"masse brute : déclaration OFDF {extract.formater_kg(masse)} "
                           f"vs waybill DHL {extract.formater_kg(brut_wb)} — à vérifier")
        else:
            art.designation = A_VERIFIER
            if len(groupes) <= 1:
                d.avertissements.append("aucun waybill annexé associé à ce MRN")
            d.source_marchandises = (f"Déclaration de transit national OFDF (GDRN {d.mrn}) "
                                     f"— sans liste d'articles")
        d.articles.append(art)
        d.avertissements.append(
            "le formulaire TCH ne porte pas de désignation de marchandises : reprise "
            "du waybill DHL associé lorsque disponible (traçabilité dans le rapport interne)")
        out.append(d)
    return out


# ------------------------------------------------------ TAD français (FR) T1/T2
def _dossiers_tad_fr(pdf: Path, verdicts: list[Verdict]) -> list[Dossier]:
    out: list[Dossier] = []
    for v in [x for x in verdicts if x.famille == "TRANSIT_FR"]:
        plat = pdfio.couche_texte_layout(pdf, v.page)
        faits = extract.extraire_tad_fr(pdf, v.page, plat, mrn_depuis_nom(pdf))
        d = Dossier(mrn=faits.get("mrn", ""), type=faits.get("type", ""),
                    dm=dm_depuis_nom(pdf))
        d.fichiers.append(pdf.name)
        d.ajouter_entete("Pays de destination", faits.get("pays_dest"))
        d.ajouter_entete("Bureau de départ", faits.get("bureau_depart"))
        d.ajouter_entete("Bureau de destination", faits.get("bureau_dest"))
        d.ajouter_entete("Terme ultime", faits.get("terme_ultime"))
        d.ajouter_entete("Garantie", faits.get("garantie"))
        d.ajouter_entete("Numéro de référence", faits.get("reference"))
        for role, cle in (("Expéditeur", "expediteur"), ("Destinataire", "destinataire"),
                          ("Titulaire du régime", "titulaire")):
            if faits.get(cle):
                d.parties.append({"role": role, "lignes": faits[cle]})
        colis = _chiffres(faits.get("colis"))
        masse = extract.nombre(faits.get("masse_brute"))
        if faits.get("vehicule"):
            d.transport.append(["Véhicule / mode", faits["vehicule"] + " — Route"])
        if colis:
            d.transport.append(["Nbre de colis", colis])
            d.total["colis"] = f"{colis} colis"
        if masse is not None:
            d.transport.append(["Masse brute totale", extract.formater_kg(masse)])
            d.total["brut"] = extract.formater_kg(masse)
        net = extract.nombre(faits.get("masse_nette"))
        d.articles.append(Article(
            no="1", designation=faits.get("designation") or A_VERIFIER,
            code_nc=faits.get("code_nc", ""),
            brut=extract.formater_kg(masse) if masse is not None else "",
            net=extract.formater_kg(net) if net is not None else "",
            colis=f"{colis} colis" if colis else "",
            doc_prec=faits.get("doc_prec", "")))
        d.source_marchandises = (f"Reprise du document de transit {d.type or 'T2'}"
                                 + (f" (MRN {d.mrn})" if d.mrn else ""))
        if not faits.get("designation"):
            d.avertissements.append("désignation non lue sur le formulaire — à vérifier")
        out.append(d)
    return out


# --------------------------------------------------------- formulaire CargoWise
def _dossiers_cw1(pdf: Path, verdicts: list[Verdict], tmp: Path | None = None) -> list[Dossier]:
    faits_par_page: dict[int, dict] = {}
    for v in verdicts:
        if v.famille.startswith("ANNONCE_CW"):
            faits_par_page[v.page] = extract.extraire_cw1(
                pdfio.couche_texte_layout(pdf, v.page), v.page)
    if not faits_par_page:
        return []
    annonce = next((f for f in faits_par_page.values() if f.get("entete_annonce")), {})
    codes_annonce = qualite.codes_annonce(pdf, [annonce["page"]], tmp) if annonce and tmp else []
    mrns = [m for _, m in annonce.get("positions", [])]
    inventaires = [f for f in faits_par_page.values() if f.get("type_page") == "inventaire"]
    listes = [f for f in faits_par_page.values() if f.get("type_page") == "liste"]
    if not mrns:
        mrn_nom = mrn_depuis_nom(pdf)
        mrns = [mrn_nom] if mrn_nom else [f.get("mrn", "") for f in inventaires]
    out: list[Dossier] = []
    for mrn in [m for m in dict.fromkeys(mrns) if m]:
        d = Dossier(mrn=mrn, dm=_nettoyer_annonce_da(annonce.get("no_annonce", "")),
                    dossier=annonce.get("dossier", ""),
                    date=date_iso_fr(annonce.get("date", "")))
        d.fichiers.append(pdf.name)
        d.annonce_originale = bool(annonce)
        d.codes_annonce = list(codes_annonce)
        if annonce and not codes_annonce:
            d.blocages.append("Code-barres de l'annonce originale non décodé : aucun MRN substitué")
        if codes_annonce:
            d.ajouter_entete("N° annonce", " / ".join(codes_annonce))
        d.ajouter_entete("Annonce DA", d.dm)
        d.ajouter_entete("Référence", annonce.get("reference"))
        if annonce.get("date"):
            d.ajouter_entete("Date acceptation",
                             f"{annonce['date']} {annonce.get('heure', '')}".strip())
        d.ajouter_entete("Déclarant", annonce.get("declarant"))
        inv = _page_pour(inventaires, mrn)
        listes_mrn = [f for f in listes if f.get("mrn") == mrn]
        if not listes_mrn:
            proche = _page_pour(listes, mrn)
            listes_mrn = [proche] if proche else []
        if inv:
            colis = _chiffres(inv.get("colis_total"))
            masse = extract.nombre(inv.get("masse_totale"))
            if colis:
                d.transport.append(["Nbre de colis", colis])
                d.total["colis"] = f"{colis} colis"
            if masse is not None:
                d.transport.append(["Masse brute totale", extract.formater_kg(masse)])
                d.total["brut"] = extract.formater_kg(masse)
        if listes_mrn:
            d.articles.extend(extract.extraire_cw1_articles(pdf, [f["page"] for f in listes_mrn]))
            for i, a in enumerate(d.articles, 1):
                a.no = str(i)
        if not d.articles:
            d.avertissements.append("liste d'articles CW1 non extraite — position « à vérifier »")
            d.articles.append(Article(no="1", designation=A_VERIFIER))
            d.ecart = "liste d'articles CW1 illisible : désignation à vérifier"
        d.source_marchandises = ("Reprise du formulaire CargoWise « Annonce arrivée / "
                                 "Inventory request report / Transit list of items »"
                                 + (f" — dossier {d.dossier}" if d.dossier else ""))
        out.append(d)
    return out


def _page_pour(pages: list[dict], mrn: str) -> dict | None:
    """Privilégie l'identité exacte ; aucun choix entre candidats OCR ambigus."""
    exactes = [f for f in pages if mrn and f.get("mrn") == mrn]
    if len(exactes) == 1:
        return exactes[0]
    proches = [f for f in pages if mrn and f.get("mrn")
               and extract._distance_confusion(f["mrn"], mrn) <= 2]
    return proches[0] if len(proches) == 1 else None


def _nettoyer_annonce_da(valeur: str) -> str:
    """« PMP 20:990101 » (confusion de lecture) -> « PMP 20990101 ».

    La couche texte du formulaire CW1 insère un « : » là où le numéro est en
    réalité continu ; on le retire entre deux chiffres avant de relire le motif.
    """
    v = extract.nettoyer_nombre(extract.nettoyer(valeur))
    v = re.sub(r"(?<=\d)\s*:\s*(?=\d)", "", v)
    m = RE_PMP.search(v.replace(" ", ""))
    if m:
        return f"PMP {m.group(2)}"
    return v


def _fusionner(dossiers: list[Dossier], cw_dossiers: list[Dossier]) -> list[Dossier]:
    """Le formulaire CW1 porte le DM/dossier, le TAD/TCH porte les marchandises."""
    if not dossiers:
        return cw_dossiers
    associes = set()
    for d in dossiers:
        cw = next((c for c in cw_dossiers if c.mrn and d.mrn
                   and c.mrn == d.mrn), None)
        if not cw:
            continue
        associes.add(id(cw))
        d.annonce_originale = cw.annonce_originale
        d.codes_annonce = list(cw.codes_annonce)
        d.blocages.extend(cw.blocages)
        d.dm = d.dm or cw.dm
        d.dossier = cw.dossier or d.dossier
        for lbl, val in cw.entete:
            d.ajouter_entete(lbl, val)
        for cle in ("colis", "brut"):
            if not d.total.get(cle) and cw.total.get(cle):
                d.total[cle] = cw.total[cle]
        d.avertissements.append("DM et référence croisés avec le formulaire CargoWise du dépôt")
    return dossiers + [c for c in cw_dossiers if id(c) not in associes]


def _appliquer_cw(dossiers: list[Dossier], cw_entete: dict) -> None:
    """Porte l'en-tête NCTS récupéré par MCP sur les dossiers extraits.

    Champs disponibles (serveur CargoWise, vérifiés) : mrn, statut_douane, statut_msg,
    type_mouvement, phase, arrivee, lrn (= DM), bureau. Le DM est une donnée
    OBLIGATOIRE du document : il est porté dès qu'il est connu.

    GARDE-FOU : l'en-tête n'est appliqué qu'au dossier dont le MRN correspond à
    celui renvoyé par CargoWise. Une clé NCT… fournie à la main pour un autre
    dossier ne doit jamais écraser un MRN — sans quoi le document mélangerait
    les données de deux déclarations.
    """
    for d in dossiers:
        trouve = None
        for cle, valeurs in cw_entete.items():
            mrn_cw = valeurs.get("mrn", "")
            if not mrn_cw:
                continue
            if d.mrn and mrn_cw == d.mrn:
                trouve = valeurs
                break
        if not trouve:
            d.avertissements.append(
                "CargoWise : aucune déclaration ne correspond au MRN de ce document "
                "— en-tête non appliqué (données PDF seules)")
            continue
        d.mrn_verifie = True
        d.preuves.append({"methode": "CargoWise", "cle": cle, "champs": dict(trouve)})
        if trouve.get("lrn"):
            d.dm = trouve["lrn"]
            d.avertissements = [a for a in d.avertissements
                                if a != "DM / LRN manquant — à vérifier"]
        if trouve.get("mrn"):
            d.mrn = trouve["mrn"]
        if trouve.get("arrivee"):
            d.date_arrivee = date_iso_fr(trouve["arrivee"])       # type: ignore[attr-defined]
            d.ajouter_entete("Date d'arrivée",
                             f"{d.date_arrivee} "                          # type: ignore[attr-defined]
                             f"{trouve['arrivee'][11:16]}".strip())
        if trouve.get("statut_douane"):
            d.ajouter_entete("Statut douane", trouve["statut_douane"])
        if trouve.get("phase"):
            d.ajouter_entete("Phase", trouve["phase"])
        if trouve.get("bureau"):
            d.ajouter_entete("Bureau de destination", trouve["bureau"])
        if trouve.get("type_mouvement"):
            d.ajouter_entete("Type de mouvement",
                             f"{trouve['type_mouvement']} (arrivée)")
        d.avertissements.append("en-tête NCTS (MRN, DM, statut, bureau) "
                                "complété depuis CargoWise")


def _resoudre_identifiants(d: Dossier, pdf: Path) -> None:
    """Établit le MRN et le DM d'un dossier à partir du document puis du fichier.

    La couche texte des scans étant dégradée (l/1, S/5, O/0), le nom de fichier
    fait foi dès que les deux se ressemblent : c'est la référence déposée par
    l'utilisateur pour ce dossier précis.
    """
    mrn_fichier = mrn_depuis_nom(pdf)
    if mrn_fichier and d.mrn != mrn_fichier:
        if d.mrn:
            d.avertissements.append(
                f"MRN lu « {d.mrn} » corrigé en « {mrn_fichier} » "
                f"(nom du fichier déposé, couche texte dégradée)")
            d.avertissements[-1] = (
                f"MRN du document « {d.mrn} » différent du nom « {mrn_fichier} » — à vérifier")
        elif not d.mrn:
            d.mrn = mrn_fichier
            d.avertissements.append("MRN repris du nom de fichier (non lu sur le document)")
    if not d.dm:
        d.dm = dm_depuis_nom(pdf)
        if d.dm:
            d.avertissements.append("DM repris du nom de fichier")


def _finaliser(d: Dossier, pdf: Path) -> None:
    """Complète la date, la clé de dossier, les articles et la confiance."""
    _resoudre_identifiants(d, pdf)
    if not d.mrn:
        d.avertissements.append("MRN introuvable — champ « à vérifier »")
    elif not re.fullmatch(r"\d{2}[A-Z]{2}[A-Z0-9]{14}", d.mrn):
        d.avertissements.append("MRN incomplet ou mal formé — à vérifier ; aucun code-barres exploitable")

    if not d.date:
        d.date = date_iso_fr(_date_pdf(pdf))
    if not d.dossier:
        d.dossier = d.mrn
    if not d.articles:
        d.articles.append(Article(no="1", designation=A_VERIFIER))
    if not d.source_marchandises:
        d.source_marchandises = "Reprise du document de transit déposé"
    lisible = any(a.designation and a.designation != A_VERIFIER for a in d.articles)
    d.confiance = "haute" if (d.mrn and d.dm and lisible and not _lacunaire(d)
                                  and not d.ecart and not any("MRN" in a and "vérifier" in a for a in d.avertissements)) else "faible"
    if not d.dm:
        d.avertissements.append("DM / LRN manquant — à vérifier")
    d.avertissements = list(dict.fromkeys(d.avertissements))


def _lacunaire(d: Dossier) -> bool:
    """Le dossier manque-t-il d'une donnée que seule la lecture d'image donne ?

    Critères (skill, étape 6) : pas de désignations exploitables, ou aucun
    article complet (sans code marchandise ni masse, une ligne n'est pas
    contrôlable), ou aucune partie identifiée.
    """
    lisibles = [a for a in d.articles
                if a.designation and a.designation != A_VERIFIER]
    if not lisibles:
        return True
    if len(lisibles) != len(d.articles):
        return True
    if any(not a.code_nc or not (a.brut or a.net) for a in lisibles):
        return True
    return not d.parties


def _croiser(d: Dossier) -> None:
    """Conserve tous les écarts ; ne compare que des sommes complètes."""
    ecarts = [x for x in d.ecart.split(" | ") if x]
    def ajouter(texte):
        if texte not in ecarts:
            ecarts.append(texte)
    def colis(v):
        m = re.fullmatch(r"\s*(\d+)\s*(?:colis|[A-Z]{2,3})?\s*", str(v or ""))
        return int(m.group(1)) if m else None
    total = colis(d.total.get("colis"))
    valeurs = [colis(a.colis) for a in d.articles]
    if total is not None and valeurs and all(v is not None for v in valeurs):
        somme = sum(valeurs)
        if somme != total:
            ajouter(f"colisage : total déclaré {total} vs somme des lignes {somme} — à vérifier")
    total = extract.nombre(d.total.get("brut"))
    masses = [extract.nombre(a.brut) for a in d.articles]
    if total is not None and masses and all(m is not None for m in masses):
        somme = sum(masses)
        if abs(somme - total) > 0.05:
            ajouter(f"masse brute : total déclaré {extract.formater_kg(total)} vs somme des lignes {extract.formater_kg(somme)} — à vérifier")
    d.ecart = " | ".join(ecarts)


# ------------------------------------------------------------------ exécution
def cles_cargowise(pdf: Path, cles_nct: list[str] | None = None) -> list[str]:
    """Clés NCTS à interroger pour ce PDF.

    ``cargowise_get_ncts`` n'accepte QUE la clé de déclaration ``NCT…`` (vérifié
    sur le serveur CargoWise : un MRN, un DM ou un LRN renvoient « no business object
    matching the criteria »). Cette clé est fournie par l'utilisateur (``--nct``)
    ou reprise du nom de fichier ; à défaut il n'y a rien à interroger.
    """
    cles = [c.strip() for c in (cles_nct or []) if c.strip()]
    if cles:
        return cles
    m = re.search(r"(?i)\b(NCT\d{6,10})\b", pdf.stem)
    return [m.group(1).upper()] if m else []


def executer(cfg: dict, mode: str | None = None, dry_run: bool = False,
             enrichir_cw: bool | None = None,
             cles_nct: list[str] | None = None,
             lot: tuple[list[Path], list[Path]] | None = None) -> Resultat:
    """Traite les dépôts. `lot` restreint le traitement à des fichiers précis.

    Le guetteur (`surveillance`) fournit `lot` : c'est le lot qu'il a vu arriver
    et jugé stable. Sans `lot`, tous les PDF présents dans les dépôts sont pris.
    """
    dossiers_cfg = cfg["dossiers"]
    unique = Path(dossiers_cfg["depot_unique"])
    multiple = Path(dossiers_cfg["depot_multiple"])
    sortie_dir = Path(dossiers_cfg["sortie"])

    if lot is None:
        uniques, multiples = fichiers_pdf(unique), fichiers_pdf(multiple)
    else:
        uniques, multiples = list(lot[0]), list(lot[1])
    if mode == "unique":
        multiples = []
    elif mode == "multiple":
        uniques = []

    if not uniques and not multiples:
        return Resultat(mode=mode or "auto",
                        messages=[f"aucun PDF à traiter ({unique} et {multiple})"])

    actif_cw = cfg["cargowise"].get("active") if enrichir_cw is None else enrichir_cw
    res = Resultat(mode=mode or ("both" if uniques and multiples
                                 else ("unique" if uniques else "multiple")),
                   depots=uniques + multiples)

    sortie_dir = fsutil.dossier(Path(cfg["_projet"]), sortie_dir, creer=not dry_run)
    # les fichiers d'échange (data.json) et les rapports vont dans un sous-dossier :
    # « Annonces d'arrivées » ne doit contenir que les PDF remis au client.
    dossier_data = fsutil.dossier(sortie_dir, "data", creer=not dry_run)
    horodatage = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    traites: list[Path] = []
    journal = [f"Annonce(s) d'arrivée NCTS — {datetime.now():%d.%m.%Y %H:%M:%S}",
               f"mode : {res.mode}   |   {len(uniques)} PDF en dépôt unique, "
               f"{len(multiples)} PDF en dépôt multiple",
               f"CargoWise : {'activé' if actif_cw else 'désactivé'}", ""]

    def analyser_sans_interrompre(pdf, tmp):
        cw_res = None
        try:
            # Le MRN est établi par la lecture du PDF (ou sa relecture liée au
            # contenu) avant de rechercher sa déclaration dans CargoWise.
            an = analyser_pdf(pdf, cfg, tmp)
        except Exception as exc:
            an = Analyse(pdf=pdf, messages=[f"Échec d'analyse : {type(exc).__name__} — {exc}"])
        if actif_cw and an.dossiers:
            try:
                cfg_cw = {**cfg, 'cargowise': {**cfg['cargowise'], 'active': True}}
                cw_res = cw_client.interroger(cfg_cw, cles_cargowise(pdf, cles_nct),
                                             mrns=[d.mrn for d in an.dossiers])
                for d in an.dossiers:
                    liaison = cw_res.liaisons_bi.get(d.mrn)
                    if liaison:
                        if d.dossier and d.dossier not in (d.mrn, liaison['dossier']):
                            d.blocages.append('Dossier BI / CargoWise différent de la référence dossier extraite')
                        else:
                            d.dossier = liaison['dossier']
                            d.ajouter_entete('Dossier', d.dossier)
                        d.preuves.append({'methode': 'Liaison BI confirmée par eDoc CargoWise', **liaison})
                if cw_res.ok:
                    _appliquer_cw(an.dossiers, cw_res.entete)
            except Exception as exc:
                cw_res = cw_client.ResultatCW(message=f"Enrichissement CargoWise en échec : {exc}")
        if cw_res is not None:
            etat = ("données récupérées" if cw_res.ok else
                    "dossier retrouvé, en-tête NCTS absent" if cw_res.liaisons_bi else "non exploité")
            an.messages.append(f"CargoWise : {etat} — {cw_res.message or cw_res.statut}")
            an.messages.extend(f"CargoWise : {a}" for a in cw_res.avertissements)
        return an, cw_res

    with tempfile.TemporaryDirectory(prefix="ulix_ncts_") as td:
        tmp = Path(td)

        # --- dépôt unique : 1 fichier -> 1 annonce ---------------------------
        for pdf in uniques:
            an, cw_res = analyser_sans_interrompre(pdf, tmp)
            res.analyses.append(an)
            journal += _journaliser(an, cw_res)
            if an.dossiers:
                nb_word_avant = len(res.modifiables)
                produits = _produire(an.dossiers, cfg, sortie_dir, horodatage,
                                     multiple=False, journal=journal, res=res,
                                     dry_run=dry_run, dossier_data=dossier_data)
                res.sorties += produits
                if produits or len(res.modifiables) > nb_word_avant:
                    traites.append(pdf)

        # --- dépôt multiple : N fichiers -> 1 annonce ------------------------
        if multiples:
            tous: list[Dossier] = []
            for pdf in multiples:
                an, cw_res = analyser_sans_interrompre(pdf, tmp)
                res.analyses.append(an)
                journal += _journaliser(an, cw_res)
                tous += an.dossiers
            incomplets = [a for a in res.analyses if a.pdf in multiples and not a.dossiers]
            if incomplets:
                res.messages.append("Dépôt multiple incomplet : au moins un PDF n'a pas pu être associé à un transit ; lot conservé pour vérification")
            elif tous:
                nb_word_avant = len(res.modifiables)
                produits = _produire(tous, cfg, sortie_dir, horodatage,
                                     multiple=True, journal=journal, res=res,
                                     dry_run=dry_run, dossier_data=dossier_data)
                res.sorties += produits
                if produits or len(res.modifiables) > nb_word_avant:
                    traites.extend(a.pdf for a in res.analyses
                                   if a.pdf in multiples and a.dossiers)
            else:
                res.messages.append("dépôt multiple : aucune donnée de transit exploitable")

    res.echecs = [p for p in res.depots if p not in traites]
    if not dry_run:
        if cfg["traitement"].get("deplacer_traite"):
            res.archives = _archiver(traites, cfg, journal)
        if cfg["traitement"].get("ecrire_rapport"):
            rapport = dossier_data / f"Rapport_{horodatage}.txt"
            rapport.write_text("\n".join(journal), encoding="utf-8")
            res.rapports.append(rapport)
    return res


def _journaliser(an: Analyse, cw_res) -> list[str]:
    lignes = [f"— {an.pdf.name}"]
    lignes += [f"    {m}" for m in an.messages]
    for v in an.verdicts:
        if not v.transport:
            lignes.append(f"    page {v.page} écartée : {v.famille} ({v.detail})")
    for d in an.dossiers:
        lignes.append(f"    -> dossier {d.mrn or '?'} (DM {d.dm or '?'}) : "
                      f"{len(d.articles)} article(s), confiance {d.confiance}")
        if d.source_marchandises:
            lignes.append(f"       SOURCE : {d.source_marchandises}")
        for a in d.avertissements:
            lignes.append(f"       ! {a}")
        if d.ecart:
            lignes.append(f"       ECART : {d.ecart}")
    if cw_res is not None:
        etat = ("OK" if cw_res.ok else
                "dossier retrouvé, en-tête NCTS absent" if cw_res.liaisons_bi else "non exploité")
        lignes.append(f"    CargoWise : {etat} — {cw_res.message or cw_res.statut}")
        for a in cw_res.avertissements:
            lignes.append(f"       ! CW {a}")
    lignes.append("")
    return lignes


def _produire(dossiers: list[Dossier], cfg: dict, sortie_dir: Path, horodatage: str,
              multiple: bool, journal: list[str], res: Resultat,
              dry_run: bool = False, dossier_data: Path | None = None) -> list[Path]:
    gabarit = render.trouver_gabarit(Path(cfg["_projet"]))
    if not gabarit and cfg["document"].get("format_sortie", "docx") == "pdf":
        res.messages.append("generate_doc.py introuvable : rendu impossible "
                            "(le gabarit du skill est le seul chemin de rendu autorisé)")
        return []
    identifiants = [d.mrn for d in dossiers if d.mrn]
    if len(identifiants) != len(set(identifiants)):
        res.messages.append("MRN présent plusieurs fois dans le lot : rapprochement manuel requis pour éviter le double comptage")
        journal.append(res.messages[-1])
        return []
    if cfg.get('dm', {}).get('active'):
        from . import dm, dm_service
        try:
            if any(not d.mrn_verifie or d.blocages for d in dossiers):
                raise dm.ErreurDM('Réservation DM arrêtée : MRN non corroboré ou dossier bloqué')
            existants = {d.dm.strip() for d in dossiers if d.dm and
                         not re.search(r'vérifier|compléter|absent|inconnu', d.dm, re.I)}
            if len(existants) > 1:
                raise dm.ErreurDM('Plusieurs DM sources dans une annonce : rapprochement requis')
            attribution = dm_service.Client(cfg['dm']).attribuer(
                [d.mrn for d in dossiers], next(iter(existants), ''), simulation=dry_run)
            valeur = attribution.get('dm', '')
            if valeur:
                dm.numero(valeur)  # Une réponse invalide ne doit jamais atteindre le document.
                for d in dossiers:
                    d.dm = valeur
                    d.avertissements = [a for a in d.avertissements if not a.startswith('DM / LRN')]
                    d.avertissements.append(f'DM {valeur} : registre central, numéro conservé aux réimpressions')
                    d.preuves.append({'source': 'registre_dm', 'dm': valeur,
                                      'mrns': [x.mrn for x in dossiers]})
                journal.append(f'DM central : {valeur} — ' + ('réutilisé' if attribution.get('reutilise') else 'réservé'))
            else:
                journal.append('DM : simulation sans réservation de numéro')
                if not dry_run:
                    raise dm.ErreurDM('Le service DM n’a renvoyé aucun numéro')
        except dm.ErreurDM as exc:
            message = f'DM : {exc} ; lot conservé, aucun document généré'
            res.messages.append(message)
            journal.append(message)
            return []
    controles = [{"mrn": d.mrn, "motifs": qualite.evaluer(d), "preuves": d.preuves,
                  "lectures_ia": d.lectures_ia} for d in dossiers]
    a_revoir = any(c["motifs"] for c in controles)
    destination = sortie_dir / ("A_verifier" if a_revoir else "Prets_a_remettre")
    if not dry_run and cfg["document"].get("format_sortie", "docx") == "pdf":
        destination.mkdir(parents=True, exist_ok=True)
    data = render.dossiers_vers_data(dossiers, cfg)
    data["controle_interne"] = {"statut": "a_verifier" if a_revoir else "pret", "dossiers": controles}
    mrns = [d.mrn for d in dossiers if d.mrn]
    if multiple:
        nom = (f"Annonce_et_Inventaire_MULTI_{len(dossiers)}REF_"
               f"{_slug(data.get('dm') or 'DM')}_{horodatage}.pdf")
    else:
        nom = f"Annonce_et_Inventaire_{_slug(mrns[0] if mrns else dossiers[0].cle())}.pdf"
    if cfg["document"].get("format_sortie", "docx") == "docx":
        from . import word
        destination = sortie_dir
        sortie = destination / (Path(nom).stem.replace("v_rifier", "DM_a_completer") + ".docx")
        if sortie.exists():
            sortie = sortie.with_name(f"{sortie.stem}_{horodatage}{sortie.suffix}")
        ok, msg = (True, "simulation") if dry_run else word.generer(data, sortie, dossier_data)
        if not ok:
            res.messages.append(msg)
            journal.append(msg)
            return []
        res.modifiables.append(sortie)
        if a_revoir:
            res.modifiables_avec_reserves.append(sortie)
        noms = {f for d in dossiers for f in d.fichiers}
        res.sources_modifiables.extend(a.pdf for a in res.analyses if a.pdf.name in noms)
        journal.append(f"DOCX modifiable généré : {sortie}")
        for c in controles:
            journal.extend(f"    CONTRÔLE {c['mrn']} : {m}" for m in c["motifs"])
        return []
    sortie = destination / nom
    if sortie.exists():
        sortie = sortie.with_name(f"{sortie.stem}_{horodatage}{sortie.suffix}")
    if dry_run:
        journal.append(f"    [simulation] sortie attendue : {sortie}")
        if a_revoir:
            res.a_verifier.append(sortie)
            return []
        return [sortie]
    ok, msg = render.generer(data, sortie, gabarit, dossier_data=dossier_data)
    if not ok:
        res.messages.append(f"échec de génération pour {nom} : {msg}")
        journal.append(f"    échec de génération : {msg}")
        return []
    try:
        controle = render.verifier_rendu(sortie, data=data)
    except Exception as exc:
        controle = {"ok": False, "pages": 0, "accents": False, "aplat": False,
                    "erreurs": [f"validation impossible : {exc}"]}
    journal.append(f"    PDF : {sortie} ({controle['pages']} pages, "
                   f"accents={controle['accents']}, aplat_couleur={controle['aplat']})")
    if not controle["ok"]:
        res.messages.append(f"contrôle visuel à refaire sur {nom} "
                            f"({controle.get('erreurs', [])})")
        rejet = sortie_dir / "A_verifier"
        rejet.mkdir(exist_ok=True)
        cible = rejet / ("RENDU_INVALIDE_" + sortie.name)
        shutil.move(str(sortie), str(cible))
        res.messages.append(f"Rendu techniquement invalide isolé : {cible}")
        return []
    if a_revoir:
        res.a_verifier.append(sortie)
        noms = {f for d in dossiers for f in d.fichiers}
        analyses = [a for a in res.analyses if a.pdf.name in noms]
        fiche = qualite.fiche(dossiers, data, analyses, destination, sortie.stem)
        res.fiches.append(fiche)
        res.messages.append(f"À VÉRIFIER : {nom} — sources conservées, voir {fiche.name}")
        for c in controles:
            journal.extend(f"    BLOCAGE {c['mrn']} : {m}" for m in c["motifs"])
        return []
    return [sortie]


def _slug(valeur: str) -> str:
    return re.sub(r"[^0-9A-Za-z._-]+", "_", str(valeur)).strip("_") or "NCT"


def _archiver(depots: list[Path], cfg: dict, journal: list[str]) -> list[Path]:
    """Déplace les PDF traités dans le dossier Archive/ (racine du projet)."""
    if not any(p.is_file() for p in depots):
        return []
    archive = fsutil.dossier(Path(cfg["_projet"]), cfg["dossiers"].get("archive", "Archive"),
                             creer=True)
    archives: list[Path] = []
    for pdf in depots:
        if not pdf.is_file():
            continue
        cible = archive / pdf.name
        if cible.exists():
            cible = archive / f"{pdf.stem}_{datetime.now():%Y%m%d-%H%M%S-%f}{pdf.suffix}"
        shutil.move(str(pdf), str(cible))
        archives.append(cible)
        journal.append(f"archivé : {cible}")
    return archives
