"""Extraction des données d'un document de transit — moteur déterministe.

Quatre familles de formulaires sont prises en charge, chacune avec son
extracteur :

  * ``TRANSIT_TAD``  — TAD UE (TR1/TR2, IT) : page 1 = en-tête (case TYPE,
    totaux déclarés, parties, bureaux, garantie, véhicule) ; pages suivantes =
    « ELENCO DEGLI ARTICOLI - TRANSITO », une page d'article chacune. Ces scans
    ont une couche texte dégradée (chiffres confondus, libellés bruités) : la
    lecture est POSITIONNELLE via les boîtes de mots (`pdftotext -bbox`), calée
    sur les libellés du formulaire — pas de zérisation approximative.
  * ``TRANSIT_TCH``  — déclaration de transit national OFDF (CH/DHL) : GDRN,
    référence, total emballages, total masse brute, bureaux, parties. Ces
    déclarations ne portent PAS de liste d'articles : la désignation est
    reprise du waybill DHL du même envoi (« Shipment Content »), le poids net du
    waybill, le colisage de « Total emballages ».
  * ``TRANSIT_FR``   — TAD français « TRANSIT - DOCUMENT D'ACCOMPAGNEMENT »
    (TR1/TR2 émis en France) : cases 31/32/33/35/38/40/50/53, une page.
  * ``ANNONCE_CW``   — formulaire CargoWise « Annonce arrivée » + « Inventory
    request report » + « Transit list of items » (une section par MRN).

Toute valeur non établie avec certitude est marquée « à vérifier » — jamais
inventée.

Liste d'articles d'une page. Deux dispositions possibles :
  * TAD UE « ELENCO »  — une page par article, colonnes positionnelles ;
  * TAD CH/FR « LISTE D'ARTICLES » — une page pour plusieurs articles, le
    colisage est en case 18.06 (« 4;PX;1000001 »), les masses en colonne de
    droite (« 216 » brut / « 180.2 » net), la désignation et le code NC au
    centre, le document précédent sous la désignation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from . import pdfio

A_VERIFIER = "à vérifier"

WORD = re.compile(
    r'<word xMin="([\d.]+)" yMin="([\d.]+)" xMax="([\d.]+)" yMax="([\d.]+)">(.*?)</word>')

# jetons de formulaire à ne jamais confondre avec une donnée métier
BRUIT = re.compile(
    r"(?i)^\W*$|^\[?\d{1,2}\s?\d{1,2}\]?$|^ID\s*:?$|^r[Dd]\s*:?$|^t[Dd]\s*:?"
    r"|^(?:Referente|Speditore|Destinatario|Titolare|Rappresentante|Trasportatore"
    r"|Formulari|Formulaires|BCP|Sicurezza|UCR|TIR|LRN|Numero|Tipo|UNDG|Codice"
    r"|Spese|Massa|Unitä|Unita|Documento|Documenti|Riferimento|Informazioni"
    r"|Attore|Mezzo|ELENCO|Descrizione|Descn|Pag|Totale|Tolal|Toiale|Des|MARIN"
    r"|CUS|Dich|dich|merci|articolo|No\.?|Commodity|Grossmass|Netmass|Consignor"
    r"|Consignee|Holder|Carrier|Previous|Supporting|Additional|Guarantee|Seal"
    r"|Dossier|Nbre|Declarant)\b.*$"
    r"|^[iIl|\[\]\.\,\-\s]{3,}$|^[0-9OISB]{2}[A-Z]{2}[0-9A-Z]{12,}$")

# familles de mots de passe de l'en-tête des pages de liste
MOTS_ENTETE = re.compile(
    r"(?i)n\.\s*dich|merci\s*\[|tipo\s+e\s+numero|numero\s+articolo|descrizione"
    r"|documento\s+precedente|documento\s+giustificativo|riferimento\s+complementare"
    r"|informazioni\s+supplementari|attore\s+supplementare|mezzo\s+di\s+trasporto"
    r"|codice\s+delle\s+merci|massa\s+(?:lorda|netta)|unit[äa]\s+supplementari"
    r"|spese\s+di\s+trasporto|speditore|destinatario|holder|consignor|consignee"
    r"|transit\s+list|liste\s+d.articles|no\.\s*articles|d[ée]signation\s+des"
    r"|nombre\s+et\s+nature|d[ée]claration\s+sommaire|documents\s+produits"
    r"|mentions\s+sp[ée]ciales|information\s+suppl[ée]mentaire|document\s+de"
    r"|code\s+marchandises|masse\s+brute|masse\s+nette|unit[ée]s\s+suppl"
    r"|frais\s+de\s+transport|exp[ée]diteur|destinataire|autuns?\s+participants"
    r"|autres\s+participants|identit[ée]\s+et\s+nationalit[ée]|cd\.onu|numéro\s+dzu"
    r"|type\s*\[|p\.\s*exp[ée]d|p\.\s*destination|l'?nione|union[ei]\s+europ"
    r"|documento\s+di\s+trasporto")


def _unescape(s: str) -> str:
    return (s.replace("&apos;", "'").replace("&quot;", '"').replace("&lt;", "<")
             .replace("&gt;", ">").replace("&amp;", "&"))


def mots_page(pdf: Path, page: int) -> list[tuple[float, float, float, float, str]]:
    """Mots de la page avec leurs boîtes (xMin, yMin, xMax, yMax, texte)."""
    out = pdfio.texte_bbox(pdf, page)
    return [(float(a), float(b), float(c), float(d), _unescape(t))
            for a, b, c, d, t in WORD.findall(out)]


def dimensions(pdf: Path, page: int) -> tuple[float, float]:
    """(largeur, hauteur) en points de la page."""
    out = pdfio.texte_bbox(pdf, page)
    m = re.search(r'<page width="([\d.]+)" height="([\d.]+)"', out)
    w, h = (float(m.group(1)), float(m.group(2))) if m else (595.0, 842.0)
    info = pdfio._txt(pdfio._run(["pdfinfo", "-f", str(page), "-l", str(page), str(pdf)]))
    rotation = re.search(r"Page\s+(?:\d+\s+)?rot:\s*(-?\d+)", info)
    if rotation and int(rotation[1]) % 180 == 90:
        w, h = h, w
    return w, h


def lignes(mots, tol: float = 5.0) -> list[tuple[float, list]]:
    """Regroupe les mots en lignes (y central) — [(y, [mots triés par x])]."""
    tri = sorted(mots, key=lambda w: ((w[1] + w[3]) / 2, w[0]))
    out: list[list] = []
    for w in tri:
        yc = (w[1] + w[3]) / 2
        if out and abs((out[-1][0][1] + out[-1][0][3]) / 2 - yc) <= tol:
            out[-1].append(w)
        else:
            out.append([w])
    return [((ws[0][1] + ws[0][3]) / 2, sorted(ws, key=lambda w: w[0])) for ws in out]


def cellules(ws, seuil: float = 12.0) -> list[tuple[str, float]]:
    """Découpe une ligne en cellules — [(texte, x_debut)]."""
    groupes, cur = [], []
    for w in ws:
        if cur and w[0] - cur[-1][2] > seuil:
            groupes.append(cur)
            cur = [w]
        else:
            cur.append(w)
    if cur:
        groupes.append(cur)
    return [(" ".join(x[4] for x in g), g[0][0]) for g in groupes]


# ------------------------------------------------------------------ utilitaires
def nombre(v) -> float | None:
    """« 2 126,0 » / « 1.3 » / « 0,800 » / « 144 » / « 2.126 » -> float."""
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip()
    if not s:
        return None
    s = re.sub(r"(?i)\bkg\b|tonnes?", "", s).strip()
    s = s.replace(" ", "").replace("\u00a0", "")
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def formater_kg(valeur) -> str:
    n = nombre(valeur)
    if n is None:
        return ""
    return f"{n:,.2f}".replace(",", " ").replace(".", ",") + " kg"


def nettoyer(txt) -> str:
    if txt is None:
        return ""
    t = re.sub(r"\s+", " ", str(txt))
    t = re.sub(r"\s*([.,;:])\s*", r"\1 ", t)
    return re.sub(r"\s+", " ", t).strip(" .;:-")


def chiffres(s) -> str:
    return re.sub(r"\D", "", str(s or ""))


def reparer_chiffres(s) -> str:
    """Confusions classiques de la couche texte des scans sur un champ numérique.

    ATTENTION : ne jamais appliquer à un identifiant alphanumérique (MRN, GDRN) —
    la substitution S→5 / I→1 y détruirait les lettres (ST, …). Pour ces
    identifiants, utiliser `reparer_identifiant`.
    """
    return (str(s).replace("O", "0").replace("o", "0").replace("I", "1")
            .replace("l", "1").replace("S", "5").replace("B", "8")
            .replace(" ", "").replace("\u00a0", ""))


def reparer_identifiant(s) -> str:
    """Identifiant alphanumérique (MRN/GDRN) : espaces retirés + O→0.

    On ne touche ni aux S, I, B : ce sont des lettres légitimes dans un MRN
    (« …ST… »), et la couche texte des scans les confond surtout dans les
    séquences numériques. Le rapprochement final se fait sur le nom de fichier
    (voir `pipeline._finaliser`).
    """
    return re.sub(r"[ \u00a0\-]", "", str(s or "")).upper()


RE_MRN = re.compile(r"\d{2}[A-Z]{2}[0-9A-Z]{14}")

# codes pays plausibles en position 3-4 d'un MRN NCTS (transit UE + CH)
CODES_PAYS = {
    "AT", "BE", "BG", "CH", "CY", "CZ", "DE", "DK", "EE", "ES", "FI", "FR", "GR",
    "HR", "HU", "IE", "IS", "IT", "LT", "LU", "LV", "MT", "NL", "NO", "PL", "PT",
    "RO", "SE", "SI", "SK", "TR", "GB",
}


def _normaliser_ch(c: str) -> str:
    """Corrige la seule position TOUJOURS numérique d'un MRN suisse.

    Un MRN CH est de forme ``AA CH nn xxxxxxxxxxxx`` : les positions 4 et 5 (index
    4:6) sont des CHIFFRES, mais la couche texte dégradée les rend parfois en
    lettres (« 26CHOTST… » pour ``26CH07ST…``). Le reste de l'identifiant contient
    de vraies lettres (ST dans ``26CH08ST…``, Y7 dans ``26CH09Y7…``) : il n'est
    JAMAIS réécrit ici. Le rapprochement avec le nom de fichier (distance
    tolérante aux confusions l/1, S/5, O/0) corrige le reste.
    """
    c = str(c or "").upper()
    if len(c) < 8 or c[2:4] != "CH" or c[4:6].isdigit():
        return c
    milieu = "".join(_CONFUSION_DIGIT.get(ch, ch) for ch in c[4:6])
    return c[:4] + milieu + c[6:]


# lettres que la couche texte substitue aux chiffres dans une zone numérique
_CONFUSION_DIGIT = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "|": "1",
                    "Z": "2", "R": "2", "T": "7", "S": "5", "B": "8", "G": "6",
                    "A": "4", "E": "3", "H": "4", "U": "0", "J": "1"}


def normaliser_mrn(valeur: str) -> str:
    """Nettoie un MRN lu sur un document (espaces + confusions de la zone pays)."""
    c = re.sub(r"[^0-9A-Za-z]", "", str(valeur or "")).upper()
    return _normaliser_ch(c) if c[2:4] == "CH" else c


def _mrn_plausible(c: str) -> bool:
    """Un MRN commence par l'année (20..29) puis un code pays.

    Deux gabarits rencontrés :
      * suisse : ``26CH08ST….`` / ``26CH09Y7…`` (les lettres restent possibles,
        on borne seulement la longueur des suites de lettres) ;
      * UE : ``26FR1170…``, ``26IT5BC0…`` (dominante numérique, toute suite de
        lettres > 3 signale un faux positif comme « 21ITREFERENTE02074 »).
    """
    if not RE_MRN.fullmatch(c):
        return False
    if not c[:2].isdigit() or not (20 <= int(c[:2]) <= 29):
        return False
    if c[2:4] not in CODES_PAYS:
        return False
    if c[2:4] == "CH":
        # positions 4-5 (le n° de bureau) toujours numériques ; le reste du MRN
        # peut contenir de vraies suites de lettres (ST, Y7…)
        return c[4:6].isdigit()
    if sum(ch.isdigit() for ch in c) / len(c) < 0.5:
        return False
    return max((len(m) for m in re.findall(r"[A-Z]+", c)), default=0) <= 3


def candidats_mrn(texte: str) -> list[str]:
    """MRN plausibles d'un texte, par fenêtre glissante de 18 caractères.

    La couche texte d'un scan espace les caractères (« 26lT5BC08FE 1 s635 K3 ») :
    on compacte donc le texte, puis on glisse une fenêtre de 18 caractères. Le
    filtre `_mrn_plausible` (année + code pays + gabarit) écarte les faux
    positifs — numéro de TVA « IT00000000000 », suites de lettres qu'une
    substitution de O en 0 rendrait ressemblantes, etc.
    """
    compact = re.sub(r"[^0-9A-Za-z]", "", str(texte or "")).upper()
    out: list[str] = []
    for i in range(len(compact) - 18 + 1):
        c = compact[i:i + 18]
        if c[2:4] == "CH":
            c = _normaliser_ch(c)
        if _mrn_plausible(c) and c not in out:
            out.append(c)
    return out


def choisir_mrn(texte: str, reference: str = "") -> str:
    """Meilleur MRN d'un texte, rapproché de la référence connue (nom de fichier).

    La couche texte d'un scan confond l/I/1, S/5, B/8, O/0 : on compare donc les
    candidats avec la référence via une distance qui neutralise ces confusions,
    ce qui permet de corriger un MRN lu « 26lT00000001S00001 » en
    « 26IT00000001500001 » (nom du fichier déposé).
    """
    cands = candidats_mrn(texte)
    if reference:
        cands = [c for c in cands if _distance_confusion(c, reference) <= 4] or cands
    if not cands:
        return ""
    if reference:
        best = min(cands, key=lambda c: _distance_confusion(c, reference))
        if _distance_confusion(best, reference) <= 3:
            return best
    return max(cands, key=lambda c: sum(ch.isdigit() for ch in c))


# classes de caractères que la couche texte d'un scan confond entre eux
_CONFUSIONS = ["0OQ", "1IL|", "2Z", "5S", "6G", "8B", "4A", "9g", "7T"]


def _normaliser_confusion(c: str) -> str:
    c = str(c or "").upper()
    for classe in _CONFUSIONS:
        for ch in classe:
            c = c.replace(ch, classe[0])
    return c


def _distance_confusion(a: str, b: str) -> int:
    """Distance de Levenshtein après neutralisation des confusions usuelles."""
    return _levenshtein(_normaliser_confusion(a), _normaliser_confusion(b))


def _levenshtein(a: str, b: str) -> int:
    if not a or not b or abs(len(a) - len(b)) > 4:
        return 99
    prec = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prec[j] + 1, cur[j - 1] + 1, prec[j - 1] + (ca != cb)))
        prec = cur
    return prec[-1]


def est_valeur(texte) -> bool:
    return bool(texte) and not BRUIT.search(str(texte).strip())


def _tri_y(valeurs: list[tuple[str, float]]) -> list[tuple[str, float]]:
    return sorted(valeurs, key=lambda v: v[1])


def valeurs_colonne(lgns, x_min: float, x_max: float, y_min: float = 0.0,
                    y_max: float = 1e9) -> list[tuple[str, float]]:
    """Valeurs numériques d'une bande verticale, triées par y croissant."""
    out: list[tuple[str, float]] = []
    for y, ws in lgns:
        if not (y_min <= y <= y_max):
            continue
        for texte, x in cellules(ws):
            if x_min <= x <= x_max and re.fullmatch(r"[\d.,oO]{1,12}", texte.strip()):
                out.append((texte.strip(), y))
    return _tri_y(out)


# ------------------------------------------------------------------ structures
@dataclass
class Article:
    no: str = ""
    designation: str = ""
    code_nc: str = ""
    brut: str = ""
    net: str = ""
    colis: str = ""
    doc_prec: str = ""
    justif: str = ""
    marques: str = ""


@dataclass
class Dossier:
    mrn: str = ""
    type: str = ""
    dm: str = ""
    dossier: str = ""
    date: str = ""
    entete: list = field(default_factory=list)
    parties: list = field(default_factory=list)
    transport: list = field(default_factory=list)
    articles: list = field(default_factory=list)
    total: dict = field(default_factory=dict)
    source_marchandises: str = ""
    ecart: str = ""
    fichiers: list = field(default_factory=list)
    avertissements: list = field(default_factory=list)
    confiance: str = "moyenne"
    mrn_verifie: bool = False
    ia_utilisee: bool = False
    blocages: list[str] = field(default_factory=list)
    preuves: list[dict] = field(default_factory=list)
    lectures_ia: list[dict] = field(default_factory=list)
    annonce_originale: bool = False
    codes_annonce: list[str] = field(default_factory=list)

    def cle(self) -> str:
        return self.mrn or self.dm or "?"

    def ajouter_entete(self, libelle: str, valeur) -> None:
        if valeur and not any(l == libelle for l, _ in self.entete):
            self.entete.append([libelle, str(valeur)])


# =============================================================== 1) TAD UE (IT)
def _tad_entete_lignes(lgns, w: float, h: float) -> dict:
    """Totaux déclarés : ligne de libellés « Totale articoli / dei colli /
    massa lorda », valeurs 1 ligne plus bas, à l'aplomb du libellé."""
    faits: dict = {}
    for y, ws in lgns:
        cells = cellules(ws)
        plat = " ".join(c[0] for c in cells).lower()
        if not re.search(r"totale|tolal|total", plat):
            continue
        if not re.search(r"colli|articoli|art", plat):
            continue
        zones = {}
        for texte, x in cells:
            tl = texte.lower()
            if "art" in tl:
                zones["articles_total"] = x
            elif "colli" in tl or "colis" in tl:
                zones["colis_total"] = x
            elif "massa" in tl or "lorda" in tl or "masse" in tl or "brute" in tl:
                zones["masse_totale"] = x
        for cle, x in zones.items():
            vals = valeurs_colonne(lgns, x - 12, x + 40, y + 6, y + 40)
            if vals:
                faits[cle] = reparer_chiffres(vals[0][0])
        if zones:
            break
    return faits


def extraire_tad_entete(pdf: Path, page: int, reference: str = "") -> dict:
    """En-tête du TAD UE (page 1). ``reference`` = MRN connu (nom de fichier).

    Ce formulaire utilise une police de code-barres : sa couche texte est
    partiellement illisible (l minuscule pour le 1, S pour le 5, O pour le 0).
    On collecte donc les candidats MRN de la page puis on retient celui qui
    ressemble le plus à la référence du nom de fichier.
    """
    faits: dict = {}
    lgns = lignes(mots_page(pdf, page))
    w, h = dimensions(pdf, page)
    plat = "\n".join(" ".join(c[0] for c in cellules(ws)) for _, ws in lgns)

    entete_zone = " ".join(c[0] for _, ws in lgns if _ < 0.35 * h for c in cellules(ws))
    mrn = choisir_mrn(entete_zone, reference) or choisir_mrn(plat, reference)
    if mrn:
        faits["mrn"] = mrn
    # case TYPE : T1 / T2 (mot isolé en haut de page)
    for y, ws in lgns:
        if y > 0.20 * h:
            break
        for texte, _x in cellules(ws):
            if re.fullmatch(r"T[12][LF]?", texte.strip()):
                faits["type"] = texte.strip()
                break
        if faits.get("type"):
            break
    if not faits.get("type"):
        m = re.search(r"(?m)^\s*(T1|T2|T2L|T2F)\s*$", plat)
        if m:
            faits["type"] = m.group(1)

    faits.update(_tad_entete_lignes(lgns, w, h))

    # parties (colonnes de gauche)
    faits["parties"] = _tad_parties(lgns, w)
    # bureaux
    m = re.search(r"(?i)ufficio\s+doganale\s+di\s+partenza[^\n]*?([A-Z]{2}\d{6}[^\n]*)", plat)
    if m:
        faits["bureau_depart"] = nettoyer(m.group(1))
    m = re.search(r"(?i)(?:ufficio\s+doganale\s+di\s+destinazione|dogana\s+di\s+destinazione)"
                  r"[^\n]*?((?:CH|IT|FR|DE)[\dA-Za-z\s\-\']{4,})", plat)
    if m:
        faits["bureau_dest"] = nettoyer(m.group(1))
    # pays / date / garantie / véhicule / terme ultime
    m = re.search(r"(?i)paese\s+di\s+destinazione[^\n]*?\b([A-Z]{2})\b", plat)
    if m:
        faits["pays_dest"] = m.group(1)
    m = re.search(r"(?i)termine\s+ultimo[^\d]{0,25}(\d{2}[./]\d{2}[./]\d{4})", plat)
    if m:
        faits["terme_ultime"] = m.group(1)
    m = re.search(r"(?i)accettazione[^\d]{0,25}(\d{2}[./]\d{2}[./]\d{4})", plat)
    if m:
        faits["date"] = m.group(1)
    m = re.search(r"(\d{2}[A-Z]{2}\d{2}TR\d{10})", plat)
    if m:
        faits["garantie"] = m.group(1)
    m = re.search(r"\b([A-Z]{2}\d{3,4}[A-Z]{2})\b[^\n]{0,12}\((IT|CH|FR|DE|BE|NL|PL)\)", plat)
    if m:
        faits["vehicule"] = f"{m.group(1)} ({m.group(2)})"
    m = re.search(r"(?i)sigilli[^\n]*?([\d]{4,}[S]?(?:\s*[;:]\s*[\d]{4,}[S]?)*)", plat)
    if m:
        faits["scelles"] = nettoyer(m.group(1))
    return faits


def _tad_parties(lgns, w: float) -> list[dict]:
    """Expéditeur / Destinataire / Titulaire du régime (colonne de gauche).

    La colonne de gauche du TAD empile les trois blocs ; les libellés sont les
    ancres, les valeurs sont les lignes alphabétiques qui suivent, bornées par
    l'ancre suivante ou par la fin de la zone des parties (≈ 45 % de la hauteur).
    """
    roles = [("Expéditeur", re.compile(r"speditore|exp[ée]diteur", re.I)),
             ("Destinataire", re.compile(r"destinatario|deslinatario|desünatario|destinataire", re.I)),
             ("Titulaire du régime",
              re.compile(r"(?:titolare|tilolare)\s+del\s+(?:regime|resime)|titulaire\s+du\s+r[ée]gime", re.I))]
    hauteur = max((y for y, _ in lgns), default=0.0)
    ancres: list[tuple[float, str]] = []
    for y, ws in lgns:
        for texte, x in cellules(ws):
            if x > 0.42 * w:
                continue
            for role, motif in roles:
                if motif.search(texte) and role not in [r for _, r in ancres]:
                    ancres.append((y, role))
    parties = []
    for i, (y0, role) in enumerate(ancres):
        y1 = ancres[i + 1][0] if i + 1 < len(ancres) else y0 + 55
        y1 = min(y1, y0 + 55, hauteur)
        bloc: list[str] = []
        for y, ws in lgns:
            if not (y0 + 4 <= y < y1 - 3):
                continue
            for texte, x in cellules(ws):
                if x > 0.30 * w:
                    continue
                t = nettoyer(re.sub(r"\[\d{1,2}\s?\d{1,2}\]|\bID\b\s*:?|^r[Dd]\s*:?", " ", texte))
                if re.search(r"(?i)personne de contact|refer[eo]nte|CW-ULI", t):
                    continue
                t = re.sub(r"^[^0-9A-Za-zÀ-ÿ]+", "", t)          # artefacts de marge
                t = re.sub(r"^(?:[a-zA-Z]\s+){0,3}(?=[A-Z]{6})", "", t)
                if t and est_valeur(t) and re.search(r"[A-Za-zÀ-ÿ]{3,}", t):
                    bloc.append(t)
                break
        if bloc:
            parties.append({"role": role, "lignes": list(dict.fromkeys(bloc))[:4]})
    return parties


def extraire_tad_articles(pdf: Path, page: int, dpi: int, travail: Path) -> Article | None:
    """Un article par page « ELENCO DEGLI ARTICOLI - TRANSITO ».

    Colonnes (page paysage) : n° article, cellule colis « PK  n », désignation
    (plusieurs lignes à partir de la colonne centrale), code des marchandises,
    masses (colonne de droite : brute puis nette), document précédent et
    justificatifs sous la désignation.
    """
    lgns = lignes(mots_page(pdf, page))
    w, h = dimensions(pdf, page)

    # hauteur des libellés du cadre : tout ce qui suit appartient à l'article
    y_libelles = max((y for y, ws in lgns
                      if MOTS_ENTETE.search(" ".join(c[0] for c in cellules(ws)))),
                     default=0.0)
    depart = y_libelles + 2 if y_libelles else 0.30 * h

    # désignation : lignes alphabétiques de la colonne centrale, dans l'ordre
    lignes_desc: list[tuple[float, str]] = []
    for y, ws in lgns:
        if y < depart:
            continue
        for texte, x in cellules(ws):
            if not (0.52 * w <= x <= 0.92 * w):
                continue
            frag = nettoyer(texte)
            if len(frag) < 12 or not re.search(r"[A-Za-z]{4,}", frag):
                continue
            if MOTS_ENTETE.search(frag) or BRUIT.match(frag):
                continue
            if re.fullmatch(r"[\d\s.,\-/]+", frag):
                continue
            lignes_desc.append((y, frag))
    lignes_desc.sort()
    designation = nettoyer(" ".join(f for _, f in lignes_desc))

    # cellule colis : « PK   1 » (x faible)
    colis = ""
    for y, ws in lgns:
        if y < depart - 30:
            continue
        texte = " ".join(t for t, x in cellules(ws) if .15*w <= x < .52*w)
        m = re.search(r"\b(PK|PC|PX|PLT|CTN|CAR|COL)\s*[-–=:]*\s*(\d{1,3})\b",texte)
        if m:
            colis = f"{m.group(2)} {m.group(1)}"
        if colis:
            break

    # masses : colonne de droite, valeurs triées par y (brute puis nette)
    masses = valeurs_colonne(lgns, 0.80 * w, w, depart)
    brut = reparer_chiffres(masses[0][0]) if len(masses) >= 1 else ""
    net = reparer_chiffres(masses[1][0]) if len(masses) >= 2 else ""

    # code des marchandises : 8 chiffres dans la zone basse de la colonne centrale.
    # Conserver les chiffres imprimés sans réordonner arbitrairement les colonnes.
    code_nc = ""
    bas = depart + 0.55 * (h - depart)
    for y, ws in lgns:
        if y < bas:
            continue
        for texte, x in cellules(ws):
            if not (0.26 * w <= x <= 0.55 * w):
                continue
            for tok in re.findall(r"\d[\d\s]{5,10}\d", texte):
                cand = re.sub(r"\D", "", tok)
                if len(cand) == 8:
                    code_nc = cand.zfill(8)
                    break
                if len(cand) == 7:                 # zéro de tête avalé par le scan
                    code_nc = "0" + cand
                    break
            if code_nc:
                break
        if code_nc:
            break

    # documents précédents / justificatifs (N830 / N325…)
    docs, just = [], []
    for y, ws in lgns:
        if y < depart:
            continue
        for texte in [" ".join(t for t, x in cellules(ws) if x >= .52*w)]:
            for m in re.finditer(r"\bN\s?(830|820|825|325)\s*[-–]?\s*([0-9A-Za-z][\dA-Za-z\s\-/]{4,})",
                                 texte):
                val = nettoyer(f"N{m.group(1)} - {m.group(2)}")
                if re.search(r"\d{4,}", val):
                    (docs if m.group(1).startswith("8") else just).append(val)

    if not (designation or code_nc or brut or colis):
        return None
    return Article(no="", designation=designation or A_VERIFIER, code_nc=code_nc,
                   brut=formater_kg(brut) if nombre(brut) is not None else "",
                   net=formater_kg(net) if nombre(net) is not None else "",
                   colis=colis,
                   doc_prec=list(dict.fromkeys(docs))[0] if docs else "",
                   justif=" ; ".join(list(dict.fromkeys(just))[:4]))


# ============================================== 2) transit national CH (OFDF) =
RE_TCH = {
    "gdrn": r"GDRN[ \t]*:?[ \t]*([0-9A-Z][0-9A-Z \t]{9,40})",
    "date": r"D[ée6]claration\s+accept[ée]e\s*:?\s*([\d.]{8,10}(?:,\s*[\d:]{5})?)",
    "reference": r"R[ée6]f[ée6]rence\s*:?\s*([^\n]+)",
    "emballages": r"Total\s+emballages\s*:?\s*([\dOIl]+)",
    "masse": r"Total\s+masse\s+brute\s*\(?kg\)?\s*:?\s*([\d.,OI]+)",
    "bureau_dest": r"Bureau\s+de\s+destination\s*:?\s*([^\n]+)",
}


def _bloc_adresse(plat: str, label_re: str, maxlignes: int = 3) -> list[str]:
    """Adresse suivant un libellé, arrêtée au prochain libellé du formulaire.

    Sans cette borne, l'adresse absorbe le champ suivant (« Bureau de
    destination Douane Centre … », vu sur les déclarations TCH).
    """
    lignes_ = plat.splitlines()
    for i, ligne in enumerate(lignes_):
        m = re.search(label_re, ligne, re.I)
        if not m:
            continue
        out: list[str] = []
        for j in range(i, min(i + maxlignes + 1, len(lignes_))):
            val = nettoyer(re.sub(label_re, "", lignes_[j], flags=re.I) if j == i
                           else lignes_[j])
            if j > i and (not val or re.match(r"^[A-ZÀ-Ý][a-zà-ÿ]+\s*:?\s*$", val)
                          or re.match(r"^(?:Bureau|Num[ée]ro|D[ée]lai|Total|"
                                      r"Ce document|R[ée6]f[ée6]rence|GDRN|"
                                      r"D[ée6]claration|Exp[ée6]diteur|Destinataire)\b",
                                      val, re.I)):
                break
            if val:
                out.append(val)
        return out
    return []


def extraire_tch(plat: str) -> dict:
    """Déclaration de transit national OFDF (texte en clair)."""
    faits: dict = {}
    m = re.search(RE_TCH["gdrn"], plat, re.I)
    if m:
        faits["mrn"] = normaliser_mrn(m.group(1))
    for cle in ("date", "reference", "bureau_dest"):
        m = re.search(RE_TCH[cle], plat, re.I)
        if m:
            faits[cle] = nettoyer_nombre(nettoyer(m.group(1)))
    m = re.search(RE_TCH["emballages"], plat, re.I)
    if m:
        faits["emballages"] = reparer_chiffres(m.group(1))
    m = re.search(RE_TCH["masse"], plat, re.I)
    if m:
        faits["masse_brute"] = reparer_chiffres(m.group(1)).replace(",", ".")
    faits["expediteur"] = _bloc_adresse(plat, r"Exp[ée6]diteur\s*:?")
    faits["destinataire"] = _bloc_adresse(plat, r"Destinataire\s*:?")
    return faits


def extraire_waybill_dhl(plat: str) -> dict:
    """Désignation, poids et n° de waybill repris des annexes DHL du dépôt.

    Trois dispositions rencontrées dans les dépôts ULIX :
      * waybill DHL « Shipment Content: … » (la couche texte écrit parfois
        « Shipment »/« Shipmont ») ;
      * facture proforma jointe (Société Exemple) : la désignation est la ligne du
        tableau DESCRIPTION, les poids sont en pied (Net/Gross weight) ;
      * waybill AWB : « Gross weight 4.50 KG » réparti sur la ligne.
    """
    out: dict = {}
    # 1) « Shipment Content » sur le waybill DHL
    m = re.search(r"(?i)sh[ia]?[pob]?(?:ment|mont|menl)\s+con\S{0,8}(?:nt|nl)\s*:?\s*([^\n]+)", plat)
    if m:
        val = re.sub(r"(?i)\bpackages?\b|Dackaoes|Dacka\S*", " ", m.group(1))
        out["designation"] = nettoyer(val)
    # 2) facture proforma : première ligne de description du tableau
    if not out.get("designation"):
        m = re.search(r"(?i)description\s+quantity\s+unit\s+price[^\n]*\n(.*)", plat)
        if m:
            candidat = nettoyer(re.sub(r"\d[\d\s,\.]*$", "", m.group(1)))
            if len(candidat) > 8 and re.search(r"[A-Za-z]{4,}", candidat):
                out["designation"] = candidat
    m = re.search(r"(?i)shipment\s+content\s*:?\s*([^\n]+)", plat)
    if m and not out.get("designation"):
        out["designation"] = nettoyer(m.group(1))
    # 3) poids (les libellés sont souvent coupés par la couche texte)
    m = re.search(r"(?i)net\s*w?eight\s*:?\s*([\d.,]+)", plat)
    if m:
        out["poids_net"] = m.group(1)
    m = re.search(r"(?i)gro\S*\s*w?eight\s*:?\s*([\d.,]+)", plat)
    if m:
        out["poids_brut"] = m.group(1)
    # bordereau AWB : « Gross weight  4.50  KG » (une seule occurrence, répartie)
    if not out.get("poids_brut"):
        m = re.search(r"(?i)(?:gr[oö]\S*|gross)\s+weight\s+([\d.,]+)\s*KG", plat)
        if m:
            out["poids_brut"] = m.group(1)
    m = re.search(r"(?i)(\d+)\s*box(?:es)?\s*[\dx]+cm", plat)
    if m:
        out["colis_waybill"] = m.group(1)
    m = re.search(r"WAYB[Il|]LL\s*([\d ]{8,})", plat)
    if m:
        out["waybill"] = re.sub(r"\D", "", m.group(1))
    if not out.get("waybill"):
        m = re.search(r"(?i)AWB\s*No\.?\s*([\d ]{8,})", plat)
        if m:
            out["waybill"] = re.sub(r"\D", "", m.group(1))
    m = re.search(r"(?i)customs\s+value\s*:?\s*([\d.,]+\s*[A-Z]{3})", plat)
    if m:
        out["valeur"] = nettoyer(m.group(1))
    return out


# ============================================== 3) TAD français (TR1/TR2 FR) ==
def extraire_tad_fr(pdf: Path, page: int, plat: str, reference: str = "") -> dict:
    """TAD français « TRANSIT - DOCUMENT D'ACCOMPAGNEMENT » (formulaire 1 page)."""
    faits: dict = {}
    lgns = lignes(mots_page(pdf, page))
    w, h = dimensions(pdf, page)
    plat1 = re.sub(r"[ \u00a0]", " ", plat)

    # MRN : 18 caractères dans le cadre « MRN » (bandeau haut, colonne droite).
    # On passe la référence du nom de fichier : c'est elle qui départage les
    # lectures dégradées (ex. « 20CH2000NEUCHTELFO » capté dans l'adresse du
    # destinataire au lieu du vrai MRN).
    zone = " ".join(c[0] for y, ws in lgns if y <= 0.25 * h for c in cellules(ws))
    mrn = choisir_mrn(zone, reference)
    if not mrn:
        mrn = choisir_mrn(plat1, reference)
    faits["mrn"] = mrn
    m = re.search(r"(?m)^\s*(T1|T2|T2L|T2F)\s*$", plat1)
    if m:
        faits["type"] = m.group(1)
    for cle, motif in (("articles_total", r"(\d{1,3})\s+Articles"),
                       ("colis_total", r"(\d{1,3})\s+Total\s+des\s+colis"),
                       ("reference", r"\b([A-Z]{2,4}\d{6,})\b\s*\n?\s*Exemplaire")):
        m = re.search(motif, plat1)
        if m:
            faits[cle] = m.group(1)
    # case 31 : colis et désignation (colonne de gauche, sous l'entête)
    colis = ""
    for y, ws in lgns:
        for texte, x in cellules(ws):
            m = re.fullmatch(r"(\d{1,3})\s*/\s*(PC|PX|PK|PLT|CAR|CTN)\s*/.*", texte.strip(), re.I)
            if m:
                colis = f"{m.group(1)} {m.group(2).upper()}"
                break
        if colis:
            break
    faits["colis"] = colis
    # désignation : cellule sous la ligne colis, colonne de gauche
    designation = ""
    for y, ws in lgns:
        for texte, x in cellules(ws):
            t = nettoyer(texte)
            if (0.05 * w <= x <= 0.30 * w and len(t) >= 5
                    and re.fullmatch(r"[A-ZÀ-Ý0-9 ,'’\-\.]{5,}", t)
                    and not re.search(r"(?i)colis|marques|d[ée]signation|marchandises|"
                                      r"article|masse|pays|bureau|titulaire|garantie|"
                                      r"document|douane|transit|r[ée]gime|exp[ée]diteur|"
                                      r"destinataire|formulaires|incidents|visa", t)):
                designation = t
                break
        if designation:
            break
    faits["designation"] = designation
    # case 33 code marchandises, 35 masse brute, 38 masse nette
    m = re.search(r"(?i)code\s+des\s+marchandises[^\d]{0,20}(\d{8})", plat1)
    if m:
        faits["code_nc"] = m.group(1)
    m = re.search(r"(?i)masse\s+brute\s*\(kg\)\s*[\n ]*([\d.,]{1,10})", plat1)
    if m:
        faits["masse_brute"] = m.group(1)
    m = re.search(r"(?i)masse\s+nette\s*\(kg\)\s*[\n ]*([\d.,]{1,10})", plat1)
    if m:
        faits["masse_nette"] = m.group(1)
    m = re.search(r"(?i)masse\s+brute\s*\(kg\)[^\n]*?\n[^\n]*?([\d.,]{1,10})\s*\n[^\n]*?"
                  r"masse\s+nette", plat1)
    if m and not faits.get("masse_brute"):
        faits["masse_brute"] = m.group(1)
    m = re.search(r"(?i)d[ée]claration\s+sommaire/documents?\s+pr[ée]c[ée]dents?[^\n]*\n\s*([^\n]+)",
                  plat1)
    if m:
        faits["doc_prec"] = nettoyer(m.group(1))
    for cle, motif in (("bureau_dest", r"(?i)bureau\s+de\s+destination[^\n]*?\n?\s*([^\n]+)"),
                       ("bureau_depart", r"(?i)bureau\s+de\s+d[ée]part\s*\n?\s*([^\n]+)"),
                       ("garantie", r"(?i)garantie\s*[\n ]*([0-9A-Z]{10,})"),
                       ("terme_ultime", r"(?i)d[ée]lai\s*\(date\s+limite\)\s*:?\s*([\d/]{8,10})"),
                       ("pays_dest", r"(?i)pays\s+de\s+destination[^\n]*?\b([A-Z]{2})\b"),
                       ("vehicule", r"([A-Z]{2}-\d{2}-[A-Z]{3})\s*([A-Z]{2})")):
        m = re.search(motif, plat1)
        if m:
            faits[cle] = nettoyer(" ".join(g for g in m.groups() if g))
    # parties : expéditeur (case 2), destinataire (case 8), titulaire (case 50)
    for cle, motif, limite in (("expediteur", r"2\s+Exp[ée6]diteur/Exportateur", 0.30),
                               ("destinataire", r"8\s+Destinataire", 0.30),
                               ("titulaire", r"50\s+Titulaire\s+du\s+r[ée]gime", 0.30)):
        bloc: list[str] = []
        y0 = None
        for y, ws in lgns:
            for texte, x in cellules(ws):
                if x < 0.45 * w and re.search(motif, texte, re.I):
                    y0 = y
                    break
            if y0:
                break
        if y0 is None:
            continue
        for y, ws in lgns:
            if not (y0 + 3 <= y <= y0 + 65):
                continue
            for texte, x in cellules(ws):
                if x > limite * w:
                    continue
                t = nettoyer(re.sub(r"^\d{1,2}\s+", "", texte))
                if t and est_valeur(t) and re.search(r"[A-Za-zÀ-ÿ]{3,}", t):
                    bloc.append(t)
                break
        if bloc:
            faits[cle] = list(dict.fromkeys(bloc))[:4]
    return faits


# ============================================ 4) formulaire CargoWise (CW1) ===
def nettoyer_nombre(txt) -> str:
    """Répare les nombres espacés par la couche texte d'un scan CW1.

    « 30. 07. 2026 » -> « 30.07.2026 » ; « 14: 21: 51 » -> « 14:21:51 » ;
    « PMP 20: 990101 » -> « PMP 20990101 ».
    """
    t = str(txt or "")
    t = re.sub(r"(?<=\d)\s*([.:/])\s*(?=\d)", r"\1", t)
    t = re.sub(r"(?<=\d)\s+(?=\d{3}\b)", "", t)
    return re.sub(r"\s{2,}", " ", t).strip()


def extraire_cw1(plat: str, page: int) -> dict:
    """« Annonce arrivée » / « Inventory request report » / « Transit list of items »."""
    faits: dict = {"page": page}
    if re.search(r"annonce\s+arriv", plat, re.I):
        faits["entete_annonce"] = True
        for cle, motif in (
            ("no_annonce", r"No\s+annonce\s+DA\s+([^\n]+)"),
            ("reference", r"R[eé]f[eé]r[ea]nce\s+([^\n]+)"),
            ("date", r"Date\s+acceptation\s+([\d.\s]{8,14})"),
            ("heure", r"Temps\s+acceptation\s+([\d:\s]{5,10})"),
            ("declarant", r"No\s+de\s+d[eé]clarant\s+([^\n]+)"),
            ("lieu", r"Lieu\s+agr[eé][^\n]*\n?[^\n]*?(\d{8,})"),
        ):
            m = re.search(motif, plat, re.I)
            if m:
                faits[cle] = nettoyer_nombre(nettoyer(m.group(1)))
        mrns = []
        for m in re.finditer(
                r"(?is)No\.?\s*position\s+(\d+)\s*\n\s*MRN\s+([0-9A-Z ]{12,26})", plat):
            mrns.append((m.group(1), normaliser_mrn(m.group(2))))
        if mrns:
            faits["positions"] = mrns
        m = re.search(r"Dossier\s*:?\s*([^\n]+)", plat)
        if m:
            faits["dossier"] = nettoyer(m.group(1))
    elif re.search(r"transit\s+list\s+of\s+items", plat, re.I):
        faits["type_page"] = "liste"
        faits["plat"] = plat
        faits["lignes"] = plat.splitlines()
        ms = candidats_mrn(plat)
        if ms:
            faits["mrn"] = ms[0]
        else:                       # 1re ligne de la page : le MRN du bloc
            prem = plat.splitlines()[0].strip() if plat.splitlines() else ""
            ms = candidats_mrn(prem)
            if ms:
                faits["mrn"] = ms[0]
    elif re.search(r"inventory\s+request\s+report", plat, re.I):
        faits["type_page"] = "inventaire"
        faits["plat"] = plat
        plat_c = re.sub(r"[ \u00a0\u00fe\u00ff]+", " ", plat.replace("\u000c", " "))
        ms = candidats_mrn(plat)
        if ms:
            faits["mrn"] = ms[0]
        m = re.search(r"(?i)(?:Tobi?t?l?\s*packag\w*|Total\s+packag\w*)\s*[\n ]*([\dOIl]{1,4})", plat_c)
        if m:
            faits["colis_total"] = reparer_chiffres(m.group(1))
        m = re.search(r"(?i)(?:Total\s+gro\S*m(?:ass)?\s*\(?\s*Kg\s*\)?|gross\s*mass\s*\(Kg\))\s*"
                      r"[\n ]*([\d.,]{1,12})", plat_c)
        if m:
            faits["masse_totale"] = m.group(1)
        m = re.search(r"(?i)(?:f?otal\s+it[eo]ms?|Total\s+items)\s*[\n ]*([\dOIl]{1,4})", plat_c)
        if m:
            faits["articles_total"] = reparer_chiffres(m.group(1))
        # masses cumulées de la page d'inventaire (total du MRN)
        masses = re.findall(r"\b(\d{1,4}\.\d{3,6})\b", plat_c)
        if masses:
            faits["masses_page"] = masses
    return faits


_LIBELLES_CW = re.compile(
    r"(?i)consignor|consignee|holder|carrier|departure|additional|previous document|"
    r"supporting document|transport document|guarantee|seal|bcp|representative|"
    r"contact|declarant|dossier|page|waybill|inventory|transit list|total|"
    r"no\.|mrn|lrn|ucr|tir|undg|codice|mass|packages|items|s[ée]curit|sicurezza|"
    r"description of goods|decl\.goods|document|formulari|speditore|destinatario|"
    r"titolare|mezzo|spese|riferimento|informazioni|attore")


def extraire_cw1_articles(pdf: Path, pages: list[int]) -> list[Article]:
    """Colonnes du CW1 : position, colis/marques, description, brut puis net.

    Les dimensions respectent la rotation du PDF. Les nombres des marques et
    unités supplémentaires ne sont jamais utilisés comme masses.
    """
    articles = []
    for page in pages or []:
        w, h = dimensions(pdf, page)
        lgns = lignes(mots_page(pdf, page))
        debuts = []
        for index, (y, ws) in enumerate(lgns):
            numero = next((t for x, _, _, _, t in ws
                           if x < .15*w and re.fullmatch(r"\d{1,3}",t)), None)
            description = " ".join(t for x, _, _, _, t in ws if x >= .52*w)
            if numero and re.search(r"[A-Za-zÀ-ÿ]{4,}",description) and not MOTS_ENTETE.search(description):
                debuts.append((index, numero, description))
        for i, (index, numero, description) in enumerate(debuts):
            fin = debuts[i+1][0] if i+1<len(debuts) else len(lgns)
            bande = lgns[index:fin]
            emballage = " ".join(t for x, _, _, _, t in bande[0][1] if .28*w <= x < .52*w)
            a = Article(no=numero, designation=nettoyer(description), colis=_colis_cw1(emballage))
            marque = re.search(r"\b(?:PK|PC|PX|PLT|CTN|CAR|COL)\s*,\s*\d+\s*,\s*([0-9 ]+)",emballage)
            if marque:
                a.marques = marque[1].replace(' ','')
            # On garde les emplacements même si une valeur est illisible :
            # une masse nette ne doit pas être décalée dans la case brute.
            cellules_masse = []
            for y, ws in bande[1:]:
                for x, _, _, _, texte in ws:
                    if x >= .84*w and re.fullmatch(r"[0-9OoIiLlSsTt]+[.,][0-9OoIiLlSsTt]{3,6}",texte):
                        cellules_masse.append((y,texte))
            for champ, (_,texte) in zip(('brut','net'),sorted(cellules_masse)[:2]):
                # O/0 et I/1 seulement, dans une case exclusivement numérique.
                valeur=texte.translate(str.maketrans({'O':'0','o':'0','I':'1','i':'1','l':'1','L':'1'}))
                if re.fullmatch(r"\d+[.,]\d+",valeur):
                    setattr(a,champ,formater_kg(valeur))
            for _, ws in bande[1:]:
                texte=" ".join(t for x, _, _, _, t in ws if x >= .52*w)
                if re.search(r"(?i)previous\s+document", texte) and not a.doc_prec:
                    a.doc_prec=_apres_libelle(texte,r"previous\s+document")
                elif re.search(r"(?i)supporting\s+document", texte) and not a.justif:
                    a.justif=_apres_libelle(texte,r"supporting\s+document")[:240]
            articles.append(a)
    return articles


def _apres_libelle(ligne: str, motif: str) -> str:
    """Valeur qui suit un libellé de champ, en sautant le numéro de case [12 01]."""
    m = re.search(motif, ligne, re.I)
    reste = ligne[m.end():] if m else ligne
    return nettoyer(re.sub(r"^[\s\[\]\d]{0,12}", "", reste))


def extraire_liste_std(pdf: Path, page: int) -> list[Article]:
    """Liste d'articles d'un TAD CH/FR (« LISTE D'ARTICLES ») : 1..N articles.

    Disposition : le colisage est en case 18.06 au format
    ``n° item ; TYPE ; nombre ; marques`` (ex. « 4;PX;1000001 »), la désignation
    au centre, la masse brute puis la masse nette en colonne de droite (cellules
    empilées), le code NC et le document précédent sous la désignation.
    """
    lgns = lignes(mots_page(pdf, page))
    w, h = dimensions(pdf, page)

    # ligne de séparation : dernière ligne de libellés du cadre
    y_fin_libelles = 0.0
    for y, ws in lgns:
        plat = " ".join(c[0] for c in cellules(ws))
        if MOTS_ENTETE.search(plat):
            y_fin_libelles = max(y_fin_libelles, y)
    depart = y_fin_libelles + 2 if y_fin_libelles else 0.28 * h

    articles: list[Article] = []
    courant: Article | None = None
    for y, ws in lgns:
        if y < depart:
            continue
        cells = cellules(ws)
        # nouveau bloc d'article : colisage « n;PX;marques »
        cellule_colis = next((t for t, x in cells if x < 0.30 * w
                              and re.match(r"^\d{1,3}\s*;\s*[A-Z]{2}\s*;", t.strip())), None)
        if cellule_colis:
            if courant:
                articles.append(courant)
            m = re.match(r"^\s*(\d{1,3})\s*;\s*([A-Z]{2})", cellule_colis)
            courant = Article(no=str(len(articles) + 1),
                              colis=f"{m.group(1)} {m.group(2)}" if m else "")
            # désignation éventuellement sur la même ligne
            for t, x in cells:
                if 0.45 * w <= x < 0.75 * w and len(t) > 15 and re.search(r"[A-Za-z]{4,}", t):
                    courant.designation = nettoyer(t)
                    break
            continue
        if courant is None:
            continue
        # désignation (suite), code NC, masses
        for t, x in cells:
            txt = nettoyer(t)
            if 0.45 * w <= x < 0.75 * w:
                if re.fullmatch(r"\d{6,10}", txt.replace(" ", "")):
                    if not courant.code_nc:
                        courant.code_nc = txt.replace(" ", "")
                elif re.match(r"\d+\s*;\s*(?:EXPO|N\d{3})\s*;",txt):
                    if ';EXPO;' in txt.replace(' ',''):
                        courant.doc_prec=txt
                    else:
                        courant.justif=txt
                elif (len(txt) > 15 and re.search(r"[A-Za-z]{4,}", txt)
                      and not MOTS_ENTETE.search(txt) and not BRUIT.match(txt)):
                    courant.designation = nettoyer(f"{courant.designation} {txt}")
                elif re.search(r"\bN\d{3}\b", txt) and not courant.doc_prec:
                    courant.doc_prec = txt
            if x >= 0.75 * w and re.fullmatch(r"[\d.,oO]{1,12}", txt.replace(" ", "")):
                valeur = reparer_chiffres(txt.replace(" ", ""))
                if not courant.brut:
                    courant.brut = formater_kg(valeur)
                elif not courant.net:
                    courant.net = formater_kg(valeur)
    if courant:
        articles.append(courant)
    for a in articles:
        a.designation = nettoyer(re.sub(
            r"(?i)\b(consignor|consignee|holder|carrier|previous|supporting|"
            r"additional|document|guarantee)\b.*$", "", a.designation))
    return [a for a in articles if a.designation or a.code_nc or a.brut]


def _colis_cw1(plat: str) -> str:
    """Cellule « and number of packages shipping marks » : « PC,1,1234500004 »."""
    m = re.search(r"\b(PK|PC|PX|PLT|CTN|CAR|COL)\s*[,\s-]\s*(\d{1,3})\b", plat)
    if m:
        return f"{m.group(2)} {m.group(1)}"
    return ""
