"""Classification déterministe des pages d'un PDF de dépôt.

Le dépôt contient, dans la pratique ULIX, plusieurs familles de documents
souvent mélangés dans un même PDF :

  TRANSIT_TAD       TAD UE (TR1/TR2) page 1 — « ELENCO/UNIONE EUROPEA », T1/T2
  TRANSIT_TCH       déclaration de transit national OFDF (GDRN, CH/DHL)
  TRANSIT_FR        TAD français « TRANSIT - DOCUMENT D'ACCOMPAGNEMENT » (T2)
  TRANSIT_LISTE     page liste d'articles d'un transit (ELENCO / LISTE
                    D'ARTICLES / TRANSIT LIST OF ITEMS / TRANSLIST)
  ANNONCE_CW        formulaire CW1 « Annonce arrivée »
  ANNONCE_CW_INV    formulaire CW1 « Inventory request report » (détail MRN)
  ANNONCE_CW_LISTE  formulaire CW1 « Transit list of items » (articles)
  EXPORT            déclaration d'export EX1/EAD — À ÉCARTER (piège n°1)
  ANNEXE            facture / proforma / waybill / AWB / CMR / e-AD / e-mail
  ENVELOPPE         page de garde DHL (code-barres, pagination) sans valeur
  INDETERMINE       aucun marqueur exploitable

Les familles hors sujet (`EXPORT`, `ANNEXE`, `ENVELOPPE`) sont écartées du
traitement, mais leur contenu reste exploité comme source secondaire quand il
sert la triangulation (waybill DHL -> désignation et poids net).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

MRN_TCH = re.compile(r"\b\d{2}CH\d{2}ST[0-9A-Z]{10}\b")
MRN_UE = re.compile(r"\b\d{2}[A-Z]{2}[0-9A-Z]{12,16}\b")

# --------------------------------------------------------------- ancres titres
TITRES = [
    ("ANNONCE_CW", r"annonce\s+arriv", 8),
    ("ANNONCE_CW_INV", r"inventory\s+request\s+report", 8),
    ("ANNONCE_CW_LISTE", r"transit\s+list\s+of\s+items", 7),
    ("TRANSIT_LISTE", r"liste\s+d.articles|transit\s*[-–]\s*liste", 6),
    ("TRANSIT_LISTE", r"elenco\s+degli\s+articoli\s*[-–.]*\s*transito", 6),
    ("TRANSIT_FR", r"transit\s*[-–]\s*document\s+d.accompagnement", 7),
    ("TRANSIT_TCH", r"d[ée]claration\s+de\s+marchandises\s+en\s+transit\s+national", 8),
    ("TRANSIT_TAD", r"document\s+d.accompagnement\s+transit", 7),
    ("TRANSIT_TAD", r"transit\s+accompanying\s+document", 7),
    ("TRANSIT_TAD", r"documento\s+di\s+accompagnamento\s+transito", 7),
    # page 1 d'un TAD UE : formule italienne « UNIONE EUROPEA + TIPO DI
    # DICHIARAZIONE », titre souvent absent de la couche texte dégradée
    ("TRANSIT_TAD", r"unione\s+europea|'nione\s+europea|un\.}cne\s+europea", 6),
    ("TRANSIT_TAD", r"tipo\s+di\s+dichiarazione|tipo\s+dioichia", 6),
    # page 1 d'un TAD CH : entête de la déclaration
    ("TRANSIT_TAD", r"type\s+de\s+d[ée]claration", 5),
    ("TRANSIT_TAD", r"nombre\s+et\s+nature\s+des\s+colis", 4),
    # page 1 d'un TAD émis en CH/UE : cases caractéristiques du SAD
    ("TRANSIT_TAD", r"titulaire\s+du\s+r[ée]gime\s+de\s+transit", 4),
    ("TRANSIT_TAD", r"titolare\s+del\s+regime\s+di\s+transito", 4),
    ("TRANSIT_TAD", r"bureau\s+de\s+destination", 3),
    ("TRANSIT_TAD", r"ufficio\s+doganale\s+di\s+destinazione|ufficio\s+doganale\s+di\s+partenza", 3),
]
ANCRES_TRANSIT = [
    (r"\bgdrn\b", 5),
    (r"d[ée]lai\s+de\s+transit", 4),
    (r"titulaire\s+du\s+r[ée]gime\s+de\s+transit", 4),
    (r"titolare\s+del\s+regime\s+di\s+transito", 4),
    (r"principal\s+oblig[ée]", 3),
    (r"exemplaire\s+de\s+renvoi|esemplare\s+per\s+il\s+rinvio", 3),
    (r"r[ée]gime\s+de\s+transit|regime\s+di\s+transito", 3),
    (r"masse\s+brute|massa\s+lorda", 3),
    (r"\bt2l\b|\bt2f\b", 4),
]
CASE_TYPE = (r"(?m)^\s*(T1|T2|T2L|T2F)\s*$"
             r"|\b(?:type|tipo)\b[^\n]{0,40}\b(T1|T2L|T2F|T2)\b")

# --------------------------------------------------------------------- rejets
NEG_EXPORT = [
    (r"export\s+accompanying\s+document", 8),
    (r"document\s+d.accompagnement[- ]?export", 8),
    (r"wywozowy\s+dokument\s+towarzysz", 8),
    (r"ausfuhrbegleitdokument", 8),
    (r"eu\s+export\s+declaration", 8),
    (r"d[ée]claration\s+d.exportation", 7),
    (r"\bEX\s?1\b|\bEX\s?A\b|\bEX\s?D\b", 3),
]
NEG_ANNEXE = [
    (r"proforma\s+invoice|commercial\s+invoice|packing\s+list|facture\s+proforma", 5),
    (r"\bwaybill\s+doc\b|air\s+waybill|\bawb\b\s*no|\bwaybill\b\s*[\d ]{8,}", 4),
    (r"\bcmr\b|consignment\s+note|lettre\s+de\s+voiture", 4),
    (r"from:\s|sent:\s|subject:|objet\s*:", 5),
    (r"certificate\s+of\s+origin|eur\.?1\b", 4),
    (r"dokument\s+e-?ad|\bAD\b\s*dokument|administrative\s+accompanying", 6),
    (r"prohl[áa]šení|celn[íi]\s+prohl", 4),
]
NEG_ENVELOPPE = [
    (r"g[ée]n[ée]rateur\s+de\s+balayage", 5),
    (r"nombre\s+d.enregistrements", 5),
    (r"ce\s+document\s+sert\s+d.outil", 4),
    (r"swiss-app\.dhl\.com", 4),
]

HORS_SUJET = {"EXPORT", "ANNEXE", "ENVELOPPE"}


@dataclass
class Verdict:
    page: int
    famille: str
    source: str = "texte"
    score_pos: int = 0
    score_neg: int = 0
    detail: str = ""
    mrn: str = ""
    texte: str = field(default="", repr=False)

    @property
    def utile(self) -> bool:
        return self.famille not in HORS_SUJET and self.famille != "INDETERMINE"

    @property
    def transport(self) -> bool:
        return self.famille.startswith("TRANSIT") or self.famille.startswith("ANNONCE_CW")


def _score(texte: str, motifs) -> int:
    return sum(poids for motif, poids in motifs if re.search(motif, texte, re.I))


def _mrns(texte: str, famille: str) -> str:
    t = re.sub(r"[ \u00a0]", "", texte.upper())
    if famille == "TRANSIT_TCH":
        m = MRN_TCH.search(t)
        if m:
            return m.group(0)
    m = MRN_UE.search(t)
    return m.group(0) if m else ""


def classer(texte: str) -> tuple[str, int, int, str]:
    """Retourne (famille, score_positif, score_negatif, explication)."""
    if not texte or not texte.strip():
        return "INDETERMINE", 0, 0, "page sans couche texte"
    t = texte.lower()

    titres = {}
    pos_total = 0
    for famille, motif, poids in TITRES:
        if re.search(motif, t):
            titres[famille] = max(titres.get(famille, 0), poids)
    pos_total = sum(titres.values()) + (_score(t, ANCRES_TRANSIT)
                                        if titres else 0)
    if re.search(CASE_TYPE, texte):
        pos_total += 4
    neg_x = _score(t, NEG_EXPORT)
    neg_a = _score(t, NEG_ANNEXE)
    neg_e = _score(t, NEG_ENVELOPPE)

    if neg_x >= 7:
        return "EXPORT", pos_total, neg_x, "déclaration d'export (EX1/EAD) — écartée"

    # « ELENCO DEGLI ARTICOLI - TRANSITO » : page 1 du TAD UE si les totaux et
    # l'entête UE sont là, sinon page de liste d'articles
    if "TRANSIT_LISTE" in titres:
        if (re.search(r"totale\s+(?:articoli|dei\s+colli|massa)", t)
                and re.search(r"unione\s+europea|'nione\s+europea|tipo\s+di\s+dichiarazione", t)):
            return "TRANSIT_TAD", pos_total, neg_x + neg_a, "page 1 du TAD UE"
        return "TRANSIT_LISTE", pos_total, neg_x + neg_a, "liste d'articles d'un transit"

    if "ANNONCE_CW_LISTE" in titres:
        return "ANNONCE_CW_LISTE", pos_total, neg_x + neg_a, "liste d'articles CargoWise"
    if "ANNONCE_CW_INV" in titres:
        return "ANNONCE_CW_INV", pos_total, neg_x + neg_a, "inventaire CargoWise"
    if "ANNONCE_CW" in titres:
        return "ANNONCE_CW", pos_total, neg_x + neg_a, "annonce d'arrivée CargoWise"

    if neg_e >= 4 and pos_total < 6:
        return "ENVELOPPE", pos_total, neg_e, "page de garde / pagination DHL"

    for famille in ("TRANSIT_TCH", "TRANSIT_FR", "TRANSIT_TAD"):
        if titres.get(famille, 0) >= 6:
            return famille, pos_total, neg_x + neg_a, "document de transit"

    if pos_total >= 6:
        return "TRANSIT_TAD", pos_total, neg_x + neg_a, "document de transit (indices)"
    if neg_a >= 4:
        return "ANNEXE", pos_total, neg_a, "pièce annexe (facture/waybill/e-mail)"
    return "INDETERMINE", pos_total, neg_x + neg_a, "aucun marqueur fort"


def mrn_depuis_texte(texte: str) -> str:
    """MRN crédible d'un texte (identifiant à dominante numérique)."""
    from .extract import candidats_mrn
    c = candidats_mrn(texte)
    if c:
        return c[0]
    t = re.sub(r"[ \u00a0]", "", texte.upper())
    m = MRN_TCH.search(t)
    return m.group(0) if m else ""
