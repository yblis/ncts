#!/usr/bin/env python3
"""Génère le document d'arrivée NCTS avec le gabarit ReportLab partagé.

Usage : python3 generate_doc.py data.json sortie.pdf
Dépendance : pip install reportlab

Exemple entièrement fictif (ne constitue pas une déclaration douanière) :
{
  "ncts_key": "NCT99000001",
  "mrn": "26CH07STTEST000006",
  "type": "T1",
  "dm": "DEMO 001",
  "parties": [{"role": "Destinataire", "lignes": ["Société Exemple"]}],
  "articles": [{"no": "1", "designation": "Article de démonstration",
                "brut": "10 kg", "net": "8 kg", "colis": "2 PK"}],
  "total": {"brut": "10 kg", "net": "8 kg", "colis": "2 colis"}
}

Les champs facultatifs comprennent entete, transport, controle, ecart et
source_marchandises. Les champs manquants ne doivent jamais être inventés.
Le cadre de contrôle reste sur la dernière page ; aucune case n'est cochée.
"""

import json
import re
import sys

from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm
from reportlab.lib.colors import black, red, Color
from reportlab.graphics.barcode import code128

W, H = A4
FOOTER = "V1.1 — ULIX SWISS SA — documents sources"
GREY = Color(0.35, 0.35, 0.35)
L = 25 * mm          # marge gauche
R = 185 * mm         # marge droite
MAX_ART_PER_PAGE = 8  # articles par page d'inventaire (avec sous-lignes)
MAX_BARCODES = 10     # codes-barres dessinés au maximum (voir `barcodes`)
HAUTEUR_BARCODES = 36 * mm   # hauteur maximale réservée au bloc des codes-barres
HAUTEUR_BARCODE_MIN = 5      # mm — en dessous, un lecteur ne décode plus
FOND_UTILE = 22 * mm         # limite basse du contenu (le pied est à 12 mm)


# ---------------------------------------------------------------- utilitaires
def as_kg(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, (int, float)):
        s = f"{float(v):,.2f}".replace(",", " ").replace(".", ",")
        return f"{s} kg"
    return str(v)


def wrap_w(c, text, font, size, maxw):
    """Découpe `text` pour tenir dans `maxw` (points), via stringWidth."""
    text = str(text)
    words = []
    for mot in text.split(" "):
        while mot and c.stringWidth(mot, font, size) > maxw:
            coupure = len(mot) - 1
            while coupure > 1 and c.stringWidth(mot[:coupure], font, size) > maxw:
                coupure -= 1
            words.append(mot[:coupure])
            mot = mot[coupure:]
        if mot:
            words.append(mot)
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if c.stringWidth(trial, font, size) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines or [""]


def _tronquer(c, text, font, size, maxw) -> str:
    """Tronque `text` à `maxw` en ajoutant « … » si nécessaire."""
    text = str(text)
    if c.stringWidth(text, font, size) <= maxw:
        return text
    while text and c.stringWidth(text + " …", font, size) > maxw:
        text = text[:-1]
    return (text.rstrip() + " …") if text else ""


def field(c, x, y, label, value, lw=46 * mm, size=9):
    c.setFillColor(GREY)
    c.setFont("Helvetica", size)
    c.drawString(x, y, str(label) + " :")
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", size)
    c.drawString(x + lw, y, str(value))


def footer(c, page, total):
    c.setFillColor(GREY)
    c.setFont("Helvetica", 7)
    c.drawCentredString(W / 2, 12 * mm, f"{FOOTER}    Page {page}/{total}")
    c.setFillColor(black)


def barcode(c, mrn, y, h=11, target_w=70 * mm, x_right=R):
    """Code 128 du MRN, auto-dimensionné pour tenir dans target_w et aligné à
    droite sur x_right — ne dépasse jamais la marge (plus de rognage)."""
    mrn = str(mrn)
    bw = 0.40 * mm
    bc = code128.Code128(mrn, barHeight=h * mm, barWidth=bw)
    if bc.width > target_w:                       # trop large → réduire le module
        bw = bw * target_w / bc.width
        bc = code128.Code128(mrn, barHeight=h * mm, barWidth=bw)
    x = x_right - bc.width                          # aligné à droite
    bc.drawOn(c, x, y)
    c.setFillColor(GREY)
    c.setFont("Helvetica", 6.5)
    c.drawCentredString(x + bc.width / 2, y - 3.5 * mm, mrn)
    c.setFillColor(black)


def barcodes(c, mrns, y, target_w=70 * mm):
    """Un code 128 PAR MRN, empilés dans la largeur disponible.

    Un dépôt multiple porte plusieurs déclarations : un seul code-barres avec les
    MRN concaténés devenait illisible (barres trop fines, lecteur incapable de le
    décoder). On en dessine donc un par MRN.

    Mise en page :

    * 1 MRN  -> code-barres unique, placement identique à l'origine ;
    * 2 à 4  -> empilés sur une colonne ;
    * au-delà -> sur deux colonnes, pour que le bloc reste compact et ne repousse
      pas le contenu hors de la page (constaté avec 9 MRN : le bloc écrasait le
      pied de page). Au-delà de la capacité de la zone, les MRN restants sont
      annoncés en clair — ils figurent tous dans le cadre CONTRÔLE.

    Retourne l'ordonnée du bas du bloc : l'appelant y accroche ce qui suit.
    """
    mrns = [m for m in (str(x).strip() for x in mrns) if m]
    if not mrns:
        return y
    if len(mrns) == 1:
        barcode(c, mrns[0], y, target_w=target_w)
        return y

    colonnes = 1 if len(mrns) <= 4 else 2
    retenus = mrns[:MAX_BARCODES]
    lignes = -(-len(retenus) // colonnes)          # arrondi supérieur
    # Le libellé du MRN occupe 4 mm SOUS la barre : le pas doit donc être au
    # minimum de hauteur + 4 mm, sinon le libellé d'une ligne chevauche les barres
    # de la ligne suivante (constaté avec 5 lignes serrées).
    ecart_libelle = 4 * mm
    pas_min = HAUTEUR_BARCODE_MIN * mm + ecart_libelle
    pas = max(pas_min, min(13 * mm, HAUTEUR_BARCODES / lignes))
    hauteur = max(HAUTEUR_BARCODE_MIN, pas / mm - 4)

    largeur_col = (R - L) / colonnes
    for i, mrn in enumerate(retenus):
        col, lig = divmod(i, lignes)
        x_gauche = L + col * largeur_col
        barcode(c, mrn, y - lig * pas, h=hauteur,
                target_w=min(target_w, largeur_col - 4 * mm),
                x_right=x_gauche + largeur_col - 2 * mm)

    bas = y - (lignes - 1) * pas
    if len(mrns) > len(retenus):
        c.setFillColor(GREY)
        c.setFont("Helvetica", 7)
        c.drawString(L, bas - 6 * mm,
                     f"+ {len(mrns) - len(retenus)} autre(s) MRN — voir le cadre CONTRÔLE")
        c.setFillColor(black)
        bas -= 6 * mm
    return bas


def _mrns_de(d) -> list:
    """MRN à encoder : la liste `mrns` si elle existe, sinon la valeur `mrn`."""
    if "codes_barres" in d:
        return [str(m) for m in d["codes_barres"] if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._/-]{0,79}",str(m))]
    liste = d.get("mrns")
    if isinstance(liste, (list, tuple)) and liste:
        return [str(m) for m in liste if re.fullmatch(r"\d{2}[A-Z]{2}[A-Z0-9]{14}", str(m))]
    return [str(d["mrn"])] if re.fullmatch(r"\d{2}[A-Z]{2}[A-Z0-9]{14}", str(d.get("mrn", ""))) else []


def ecart_note(c, d, y):
    """Compatibilité : les écarts sont désormais paginés dans les notes de contrôle."""
    return y


# --------------------------------------------------------------- compat. ancien
def _norm_entete(d):
    if d.get("entete"):
        return d["entete"]
    return d.get("champs_entete", [])


def _norm_articles(d):
    if d.get("articles"):
        return d["articles"]
    out = []
    for p in d.get("positions", []):
        a = {"no": p.get("no", ""), "designation": p.get("designation", ""),
             "code_nc": p.get("code_nc", ""), "brut": as_kg(p.get("brut_kg")),
             "net": as_kg(p.get("net_kg")), "colis": p.get("colis", "")}
        notes = p.get("notes", [])
        if notes:
            a["doc_prec"] = notes[0]
            if len(notes) > 1:
                a["justif"] = " ; ".join(notes[1:])
        out.append(a)
    return out


# --------------------------------------------------------------------- page 1
def page_annonce(c, d, page, total):
    """Document client : champs alignés, sans notes internes ni provenance."""
    premiere = page
    y = 0
    valeur_x = L + 46 * mm

    def ouvrir():
        nonlocal y
        c.setFont("Helvetica-Bold", 14)
        c.drawString(L, H - 24 * mm, "Annonce d'arrivée" if page == premiere else "Annonce d'arrivée - suite")
        dm = "DM : " + str(d.get("dm") or "à compléter")
        c.setFont("Helvetica", 9)
        for i, ligne in enumerate(wrap_w(c, dm, "Helvetica", 9, 85 * mm)):
            c.drawRightString(R, H - (24 + 4 * i) * mm, ligne)
        c.setFillColor(GREY)
        c.setFont("Helvetica", 9)
        sous_titre = "   ".join(f"{titre} : {d[cle]}" for cle, titre in
                                 (("type", "Type"), ("dossier", "Dossier"), ("date", "Date")) if d.get(cle))
        c.drawString(L, H - 31 * mm, _tronquer(c, sous_titre, "Helvetica", 9, R - L))
        c.setFillColor(black)
        # Les codes-barres ne figurent que sur la première page physique.
        bas = barcodes(c, _mrns_de(d), H - 49 * mm) if page == 1 else H - 37 * mm
        c.line(L, bas - 6 * mm, R, bas - 6 * mm)
        y = bas - 13 * mm

    def reserver(hauteur):
        nonlocal page
        if y - hauteur < FOND_UTILE:
            footer(c, page, total)
            c.showPage()
            page += 1
            ouvrir()

    def champ(label, valeurs):
        nonlocal y
        labels = wrap_w(c, str(label) + " :", "Helvetica", 9, 43 * mm)
        lignes = []
        for valeur in valeurs:
            lignes.extend(wrap_w(c, str(valeur), "Helvetica", 9, R - valeur_x))
        for i in range(max(len(labels), len(lignes))):
            reserver(5 * mm)
            c.setFont("Helvetica", 9)
            if i < len(labels):
                c.setFillColor(GREY)
                c.drawString(L, y, labels[i])
            c.setFillColor(black)
            if i < len(lignes):
                c.drawString(valeur_x, y, lignes[i])
            y -= 5 * mm
        y -= 1 * mm

    def separateur():
        nonlocal y
        reserver(16 * mm)
        y -= 3 * mm
        c.line(L, y, R, y)
        y -= 7 * mm

    ouvrir()
    for label, val in _norm_entete(d):
        champ(label, [val])
    if d.get("parties"):
        separateur()
        for pa in d["parties"]:
            champ(pa.get("role", "Partie"), pa.get("lignes", []))
            y -= 2 * mm
    if d.get("transport"):
        separateur()
        for label, val in d["transport"]:
            champ(label, [val])
    footer(c, page, total)
    c.showPage()
    return page - premiere + 1


# --------------------------------------------------------------------- page 2
# colonnes inventaire (mm)
COL_ART, COL_DESC, COL_NC, COL_BRUT, COL_NET, COL_COLIS = 26, 37, 116, 140, 158, 176
DESC_W = (COL_NC - COL_DESC - 2) * mm


def _inv_header(c, d, page, total):
    c.setFont("Helvetica-Bold", 13)
    c.drawString(L, H - 24 * mm, "Liste d'inventaire")
    c.setFillColor(GREY)
    c.setFont("Helvetica", 9)
    sub = " ".join(p for p in [
        f"Dossier : {d.get('dossier','')}" if d.get("dossier") else "",
        f"MRN : {d['mrn']}",
        f"Type : {d['type']}" if d.get("type") else "",
        f"DM : {d['dm']}" if d.get("dm") else ""] if p)
    # le sous-titre est TRONQUÉ proprement à la marge (jamais au-delà du cadre)
    c.drawString(L, H - 30 * mm, _tronquer(c, sub, "Helvetica", 9, R - L))
    c.setFillColor(black)
    top = H - 56 * mm
    c.setFont("Helvetica-Bold", 8.5)
    c.drawString(COL_ART * mm, top, "Art.")
    c.drawString(COL_DESC * mm, top, "Description")
    c.drawString(COL_NC * mm, top, "Code NC")
    c.drawRightString((COL_NET - 2) * mm, top, "Brut")
    c.drawRightString((COL_COLIS - 2) * mm, top, "Net")
    c.drawRightString(R, top, "Colis")
    c.line(L, top - 2.5 * mm, R, top - 2.5 * mm)
    return top - 8 * mm


def _cellule_droite(c, x, y, valeur, largeur):
    texte = str(valeur)
    taille = 8.5
    while taille > 6 and c.stringWidth(texte, "Helvetica-Bold", taille) > largeur:
        taille -= 0.25
    if c.stringWidth(texte, "Helvetica-Bold", taille) > largeur:
        raise ValueError(f"Valeur trop longue pour une colonne : {texte}")
    c.setFont("Helvetica-Bold", taille)
    c.drawRightString(x, y, texte)


def page_inventaire(c, d, articles, page, total, last):
    y = _inv_header(c, d, page, total)
    for a in articles:
        c.setFont("Helvetica-Bold", 8.5)
        c.drawString(COL_ART * mm, y, str(a.get("no", "")))
        c.drawString(COL_NC * mm, y, str(a.get("code_nc", "")))
        _cellule_droite(c, (COL_NET - 2) * mm, y, as_kg(a.get("brut", a.get("brut_kg"))), 18 * mm)
        _cellule_droite(c, (COL_COLIS - 2) * mm, y, as_kg(a.get("net", a.get("net_kg"))), 16 * mm)
        _cellule_droite(c, R, y, a.get("colis", ""), (R / mm - COL_COLIS) * mm)
        # désignation (gras) renvoyée à la ligne ; la 1re ligne est sur la même
        # ligne de base que n°/NC/brut/net/colis déjà tracés ci-dessus
        c.setFont("Helvetica-Bold", 8.5)
        for dl in wrap_w(c, a.get("designation", ""), "Helvetica-Bold", 8.5, DESC_W):
            c.drawString(COL_DESC * mm, y, dl)
            y -= 4.6 * mm
        # sous-lignes doc précédent / justificatif (gris, petit)
        c.setFillColor(GREY)
        for key, lab in [("marques", "Marques : "), ("doc_prec", "Doc. préc. : "), ("justif", "Justif. : ")]:
            if a.get(key):
                c.setFont("Helvetica", 7.3)
                for wln in wrap_w(c, lab + str(a[key]), "Helvetica", 7.3, DESC_W):
                    c.drawString(COL_DESC * mm, y, wln)
                    y -= 4 * mm
        c.setFillColor(black)
        y -= 1.5 * mm
        c.setStrokeColor(GREY)
        c.line(L, y, R, y)
        c.setStrokeColor(black)
        y -= 4.5 * mm

    if last:
        tot = d.get("total", {})
        c.setFont("Helvetica-Bold", 9)
        c.drawString(COL_DESC * mm, y, "TOTAL")
        if tot.get("brut"):
            c.drawRightString((COL_NET - 2) * mm, y, as_kg(tot.get("brut")))
        if tot.get("net"):
            c.drawRightString((COL_COLIS - 2) * mm, y, as_kg(tot.get("net")))
        if tot.get("colis"):
            _cellule_droite(c, R, y, tot.get("colis"), (R / mm - COL_COLIS) * mm)
        c.line(L, y - 3 * mm, R, y - 3 * mm)
        y -= 10 * mm
        # Les notes et la provenance figurent dans les pages d'annonce.
        _controle(c, d)

    footer(c, page, total)
    c.showPage()


def _controle(c, d):
    """Cadre CONTRÔLE — GABARIT FIXE. Ne rien modifier ici sans validation métier."""
    ctl = d.get("controle", {})
    cy = 62 * mm
    largeur_info = 68 * mm                 # au-delà, le texte entrerait dans le cadre
    # bloc d'info à gauche, en regard (valeurs tronquées à la largeur disponible)
    src_val = lambda v: _tronquer(c, v, "Helvetica-Bold", 9, largeur_info - 30 * mm)
    field(c, L, cy + 34 * mm, "Dossier", src_val(ctl.get("dossier", d.get("dossier", ""))), 30 * mm)
    field(c, L, cy + 28 * mm, "DM", src_val(ctl.get("dm", d.get("dm", ""))), 30 * mm)
    # `Réf. transit` peut porter PLUSIEURS MRN (dépôt multiple) : une seule ligne
    # les tronquait à « 26CH08STI34CFXOJN … », donc la référence du 2e et du 3e
    # dossier n'apparaissaient nulle part sur le document. On renvoie à la ligne
    # plutôt que de tronquer.
    refs = str(ctl.get("ref_transit", d.get("mrn", ""))).split(" / ")
    c.setFillColor(GREY)
    c.setFont("Helvetica", 9)
    c.drawString(L, cy + 22 * mm, "Réf. transit :")
    c.setFillColor(black)
    c.setFont("Helvetica-Bold", 9)
    yy = cy + 22 * mm
    for ref in [r for r in refs if r.strip()]:
        c.drawString(L + 30 * mm, yy, ref.strip())
        yy -= 4.6 * mm
    # Aucun bloc de provenance sur le document final.
    # cadre
    c.setStrokeColor(black)
    c.rect(100 * mm, cy, 85 * mm, 40 * mm)
    c.setFont("Helvetica-Bold", 10)
    c.drawString(103 * mm, cy + 34 * mm, "CONTRÔLE : ULIX SWISS SA")
    c.drawRightString(182 * mm, cy + 34 * mm, str(ctl.get("numero", "3140")))
    c.setFont("Helvetica", 9)
    for i, lab in enumerate(["CONFORME, selon document joint", "NON-CONFORME",
                             "AVIS D'IRRÉGULARITÉ ÉTABLI"]):
        yy = cy + 26 * mm - i * 7 * mm
        c.rect(103 * mm, yy - 1 * mm, 4 * mm, 4 * mm)
        c.drawString(109 * mm, yy, lab)
    c.drawString(103 * mm, cy + 3 * mm, "Date :")
    c.drawString(140 * mm, cy + 3 * mm, "Signature :")


# ------------------------------------------------------------------------ main
LIMITE_BASSE = 108 * mm      # la liste ne doit pas descendre sur le cadre CONTRÔLE


def _hauteur_article(c, a) -> float:
    """Hauteur (pt) qu'occupera un article : désignation + sous-lignes + filets."""
    h = 0.0
    for _ in wrap_w(c, a.get("designation", ""), "Helvetica-Bold", 8.5, DESC_W):
        h += 4.6 * mm
    for key, lab in (("marques", "Marques : "), ("doc_prec", "Doc. préc. : "), ("justif", "Justif. : ")):
        if a.get(key):
            for _ in wrap_w(c, lab + str(a[key]), "Helvetica", 7.3, DESC_W):
                h += 4 * mm
    return h + 1.5 * mm + 4.5 * mm          # trait de séparation + respiration


def _pagination(c, d, articles, hauteur_finale: float) -> list[list[dict]]:
    """Répartit les articles en pages qui Tiennent au-dessus du cadre CONTRÔLE.

    Le gabarit impose 8 articles par page, mais une désignation longue (ou des
    sous-lignes Doc. préc. / Justif.) peut faire déborder le bloc sur le cadre :
    on mesure donc la hauteur réelle de chaque article et on coupe la page dès
    que la suivante ne tiendrait plus, en réservant la place du bloc TOTAL sur la
    dernière page.
    """
    depart = _inv_header(c, d, 0, 0)
    chunks: list[list[dict]] = []
    courant: list[dict] = []
    y = depart
    for a in articles:
        h = _hauteur_article(c, a)
        if h + 10 * mm > depart - LIMITE_BASSE:
            raise ValueError("Article trop long pour le gabarit : scinder la description avant génération")
        if courant and (y - h < LIMITE_BASSE or len(courant) >= MAX_ART_PER_PAGE):
            chunks.append(courant)
            courant = []
            y = depart
        courant.append(a)
        y -= h
    chunks.append(courant)

    # place du bloc TOTAL (+ écart + source) sur la DERNIÈRE page : si ça ne
    # tient pas, on reporte le dernier article sur une page supplémentaire.
    if chunks and len(chunks[-1]) > 1:
        bloc_final = hauteur_finale + 10 * mm
        y_fin = depart - sum(_hauteur_article(c, a) for a in chunks[-1])
        if y_fin - bloc_final < LIMITE_BASSE:
            chunks.append([chunks[-1].pop()])
    return [ch for ch in chunks if ch] or [[]]


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    if not d.get("ncts_key") or not d.get("mrn"):
        print("ERREUR : 'ncts_key' et 'mrn' sont obligatoires.")
        return 2
    articles = _norm_articles(d)
    # canvas jetable dédié à la mesure (stringWidth) — mêmes polices que le rendu
    mesure = canvas.Canvas(__import__("io").BytesIO(), pagesize=A4)
    # L'inventaire réserve le TOTAL ; les notes restent dans le rapport interne.
    hauteur_finale = 0.0
    chunks = _pagination(mesure, d, articles, hauteur_finale)
    if len(_mrns_de(d)) > MAX_BARCODES:
        raise ValueError(f"Lot trop volumineux : maximum {MAX_BARCODES} déclarations par annonce")
    nb_annonce = page_annonce(mesure, d, 1, 0)
    total = nb_annonce + len(chunks)
    c = canvas.Canvas(sys.argv[2], pagesize=A4)
    c.setTitle(f"Annonce et inventaire {d['ncts_key']}")
    page_annonce(c, d, 1, total)
    for i, chunk in enumerate(chunks):
        page_inventaire(c, d, chunk, nb_annonce + 1 + i, total, last=(i == len(chunks) - 1))
    c.save()
    # auto-vérif : le fichier doit être un PDF valide non vide
    with open(sys.argv[2], "rb") as fh:
        head = fh.read(5)
    if head != b"%PDF-":
        print("ERREUR : sortie non conforme (pas un PDF).")
        return 3
    print(f"OK → {sys.argv[2]} ({total} pages)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
