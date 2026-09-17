"""Client MCP CargoWise — enrichissement (DM, date d'arrivée, dossier, statut).

Le skill prévoit que l'en-tête NCTS provienne de CargoWise. Ce module interroge
le serveur MCP (transport HTTP streamable) pour compléter les données extraites
des PDF.

Il est FACULTATIF et NE BLOQUE JAMAIS : toute erreur (serveur absent, autorisation
manquante, outil indisponible) est consignée et le document est produit à partir
des seuls PDF.

Configurer un serveur MCP CargoWise protégé par OAuth.
Outils réellement exposés et utilisés :

  * ``cargowise_get_ncts`` — en-tête NCTS complet par clé de déclaration :
    ``declarationKey`` = ``NCT…`` renvoie ``mrn``, ``customs_status``,
    ``messaging_status``, ``movement_type``, ``phase_status``, ``arrival_date``,
    ``references[]`` (le **DM est la référence de type LRN**) et le bureau (EUO) ;
  * ``cargowise_list_documents`` — eDocs attachés (``key``, ``document_type``) ;
  * ``cargowise_get_document`` — téléchargement d'un eDoc ;
  * ``cargowise_resolve_key`` — clés liées (``key``) ;
  * ``cargowise_get_shipment_summary`` / ``cargowise_track_shipment`` — contexte
    du dossier (``shipmentNumber``, PAS ``key``).

Les noms de paramètres sont découverts dans ``tools/list`` : les conventions de
nommage diffèrent d'un serveur à l'autre, et un nom erroné produit une erreur de
validation au lieu d'un résultat.
"""

from __future__ import annotations

import json
import re
import urllib.error
import urllib.request
from dataclasses import dataclass, field

from . import oauth


@dataclass
class ResultatCW:
    ok: bool = False
    statut: str = ""
    message: str = ""
    entete: dict = field(default_factory=dict)      # {clé: {mrn, dm, date, ...}}
    outils: list = field(default_factory=list)      # outils exposés par le serveur
    avertissements: list = field(default_factory=list)
    autorisation_requise: bool = False
    liaisons_bi: dict = field(default_factory=dict)  # MRN -> dossier confirmé par eDoc


class AutorisationRequise(RuntimeError):
    """Le serveur exige une autorisation OAuth non encore accordée."""

    def __init__(self, message: str, resource_metadata: str = ""):
        super().__init__(message)
        self.resource_metadata = resource_metadata


class _MCP:
    """Client JSON-RPC minimal pour un serveur MCP HTTP streamable."""

    def __init__(self, url: str, token: str = "", timeout: float = 20.0,
                 rafraichir=None):
        self.url = url
        self.token = token
        self.timeout = timeout
        self.session_id = ""
        self._id = 0
        self._rafraichir = rafraichir
        self._schemas: dict[str, dict] = {}      # nom d'outil -> schéma des paramètres

    # ------------------------------------------------------------------ HTTP
    def _post(self, payload: dict):
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(self.url, data=data, method="POST")
        req.add_header("Content-Type", "application/json")
        req.add_header("Accept", "application/json, text/event-stream")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if self.session_id:
            req.add_header("Mcp-Session-Id", self.session_id)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as rep:
                sid = rep.headers.get("Mcp-Session-Id")
                if sid:
                    self.session_id = sid
                corps = rep.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                raise AutorisationRequise(
                    "le serveur MCP exige une autorisation OAuth (401)",
                    oauth.analyser_defi_authentification(dict(exc.headers or {})))
            detail = exc.read().decode("utf-8", "replace")[:200]
            raise RuntimeError(f"HTTP {exc.code} sur {self.url} : {detail}") from exc
        for ligne in corps.splitlines():
            ligne = ligne.strip()
            if ligne.startswith("data:"):
                ligne = ligne[5:].strip()
            if ligne.startswith("{"):
                try:
                    return json.loads(ligne)
                except json.JSONDecodeError:
                    continue
        try:
            return json.loads(corps)
        except json.JSONDecodeError:
            return {}

    def _reessayer(self, action):
        """Rejoue `action` une fois après rafraîchissement du jeton."""
        try:
            return action()
        except AutorisationRequise:
            if not self._rafraichir:
                raise
            nouveau = self._rafraichir()
            if not nouveau:
                raise
            self.token = nouveau
            return action()

    # -------------------------------------------------------------- protocole
    def appeler(self, methode: str, params: dict | None = None, avec_id: bool = True):
        self._id += 1
        charge = {"jsonrpc": "2.0", "method": methode, "params": params or {}}
        if avec_id:
            charge["id"] = self._id
        rep = self._reessayer(lambda: self._post(charge))
        if "error" in rep:
            raise RuntimeError(str(rep["error"])[:300])
        return rep.get("result", {})

    def initialiser(self):
        self.appeler("initialize", {
            "protocolVersion": "2025-06-18",
            "capabilities": {},
            "clientInfo": {"name": "ulix-ncts-annonce-arrivee", "version": "1.0"},
        })
        try:
            self.appeler("notifications/initialized", avec_id=False)
        except Exception:
            pass

    def lister_outils(self) -> list[dict]:
        res = self.appeler("tools/list")
        outils = res.get("tools", []) or []
        for outil in outils:
            self._schemas[outil.get("name", "")] = (outil.get("inputSchema") or {})
        return outils

    def nom_outil(self, candidats: list[str], motif: str = "") -> str:
        """Premier outil disponible parmi `candidats`, sinon celui qui matche `motif`."""
        for nom in candidats:
            if nom in self._schemas:
                return nom
        if motif:
            for nom in self._schemas:
                if re.search(motif, nom, re.I):
                    return nom
        return ""

    def schema_arguments(self, outil):
        schema = self._schemas.get(outil) or {}
        interne = (schema.get('properties') or {}).get('params')
        if isinstance(interne, dict):
            ref = interne.get('$ref', '')
            if ref.startswith('#/$defs/'):
                interne = schema.get('$defs', {}).get(ref.rsplit('/', 1)[-1], {})
            return interne, True
        return schema, False

    def parametre(self, outil: str, candidats: list[str]) -> str:
        """Nom réel du paramètre attendu par `outil` (schéma ou convention)."""
        schema, _ = self.schema_arguments(outil)
        props = list((schema.get("properties") or {}).keys())
        for nom in candidats:
            if nom in props:
                return nom
        return candidats[0] if candidats else ""

    def appeler_outil(self, nom: str, arguments: dict) -> str:
        schema, imbrique = self.schema_arguments(nom)
        if imbrique and 'params' not in arguments:
            arguments = dict(arguments)
            props = schema.get('properties', {})
            for ancien in ('shipmentNumber', 'declarationKey', 'declaration_key'):
                if ancien in arguments and ancien not in props and 'key' in props:
                    arguments['key'] = arguments.pop(ancien)
            arguments = {'params': arguments}
        res = self.appeler("tools/call", {"name": nom, "arguments": arguments})
        contenus = res.get("content", [])
        texte = "\n".join(c.get("text", "") for c in contenus if isinstance(c, dict))
        if not texte and res.get("structuredContent"):
            texte = json.dumps(res["structuredContent"])
        if res.get("isError"):
            raise RuntimeError(texte or "Erreur de l'outil MCP")
        return texte


# ------------------------------------------------------- lecture des réponses
def lire_entete_ncts(texte: str) -> dict:
    """Extrait l'en-tête NCTS d'une réponse de ``cargowise_get_ncts``.

    Exemple de réponse fictive :

        {"processing_status":"PRS","mrn":"26NL07STTEST000018","customs_status":"CL1",
         "messaging_status":"ACC","movement_type":"A","phase_status":"044",
         "arrival_date":"2026-01-01T12:00:00",
         "references":[{"type":"LRN","reference":"DM 99000001"},
                       {"type":"EUO","reference":"CH005551",
                        "description":"Douane Centre - Le Crêt-du-Locle"}]}

    Le DM (= réf. client) est la référence de type ``LRN`` ; le bureau de
    destination est la référence ``EUO``. Plusieurs conventions de nommage
    coexistent selon les serveurs : on cherche donc aussi les variantes
    camelCase et les clés proches.
    """
    donnees = _json_souple(texte)
    if not donnees:
        return {}
    if isinstance(donnees, list):
        donnees = next((d for d in donnees if isinstance(d, dict)), {})
    if not isinstance(donnees, dict):
        return {}

    if donnees.get("found") is False or donnees.get("error"):
        return {}

    def premier(*noms):
        for nom in noms:
            for cle, valeur in donnees.items():
                if _norme(cle) == _norme(nom):
                    if isinstance(valeur, dict):
                        valeur = valeur.get('code')
                    if valeur is not None and not isinstance(valeur, (dict, list)) and str(valeur).strip():
                        return str(valeur).strip()
        return ""

    entete = {
        "mrn": premier("mrn", "entryNumber", "entry_number", "MRN"),
        "statut_douane": premier("customs_status", "customsStatus"),
        "statut_msg": premier("messaging_status", "messagingStatus"),
        "type_mouvement": premier("movement_type", "movementType"),
        "phase": premier("phase_status", "phaseStatus"),
        "arrivee": premier("arrival_date", "arrivalDate"),
        "lrn": premier("lrn", "LRN"),
        "dossier": premier("shipment_id", "shipmentId", "shipmentNumber"),
    }

    # références : DM (LRN) et bureau (EUO), quelles que soient les majuscules
    for ref in (donnees.get("references") or donnees.get("References") or []):
        if not isinstance(ref, dict):
            continue
        type_ref = str(ref.get("type") or ref.get("Type") or "").upper()
        valeur = str(ref.get("reference") or ref.get("Reference") or "").strip()
        if not valeur:
            continue
        if type_ref == "LRN" and not entete["lrn"]:
            entete["lrn"] = valeur
        elif type_ref in ("EUO", "CUS") and not entete.get("bureau"):
            entete["bureau"] = str(ref.get("description") or "").strip() or valeur
    return {k: v for k, v in entete.items() if v}


def _norme(nom) -> str:
    return re.sub(r"[^a-z0-9]", "", str(nom).lower())


def _json_souple(texte: str):
    """Charge un JSON, ou le premier objet JSON noyé dans du texte."""
    texte = (texte or "").strip()
    if not texte:
        return None
    try:
        return json.loads(texte)
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{.*\}", texte, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


# ------------------------------------------------------------------ connexion
def preparer_jeton(cw: dict, echo=print, interactif: bool = False) -> tuple[str, str]:
    """Retourne (jeton, message) en réutilisant/rafraîchissant le jeton OAuth."""
    if cw.get("token"):
        return str(cw["token"]), "jeton fourni par la configuration"
    url = cw.get("url", "")
    jetons = oauth.charger_jetons(url)
    if jetons.valide:
        return jetons.access_token, "jeton mémorisé réutilisé"
    if jetons.refresh_token:
        try:
            jetons = oauth.rafraichir(url, jetons)
            return jetons.access_token, "jeton rafraîchi"
        except oauth.ErreurOAuth as exc:
            message = f"rafraîchissement du jeton impossible ({exc})"
    else:
        message = ("jeton expiré et aucun refresh_token émis par le serveur "
                   "(seul le flux authorization_code est proposé)"
                   if jetons.access_token else "aucun jeton mémorisé")
    if interactif:
        jetons = oauth.autoriser(url, cw.get("resource_metadata", ""),
                                 cw.get("scopes") or None, cw.get("client_id", ""),
                                 cw.get("client_secret", ""), echo=echo)
        return jetons.access_token, "autorisation accordée"
    if cw.get("client_id") and cw.get("client_secret"):
        jetons = oauth.client_credentials(cw.get("token_endpoint", ""),
                                          cw["client_id"], cw["client_secret"],
                                          cw.get("scopes") or None)
        oauth.enregistrer_jetons(url, jetons)
        return jetons.access_token, "jeton machine-à-machine obtenu"
    return "", message


def autoriser_maintenant(cfg: dict, echo=print, nouveau_client: bool = False) -> tuple[bool, str]:
    """Déclenche le flux d'autorisation OAuth (à la demande de l'utilisateur)."""
    cw = cfg.get("cargowise", {})
    if not cw.get("url"):
        return False, "aucune URL de serveur MCP configurée"
    if nouveau_client:
        oauth.oublier_jetons(cw["url"])
        oauth.oublier_client(cw["url"])
    try:
        jetons = oauth.autoriser(cw["url"], cw.get("resource_metadata", ""),
                                 cw.get("scopes") or None, cw.get("client_id", ""),
                                 cw.get("client_secret", ""), echo=echo)
    except oauth.ErreurOAuth as exc:
        return False, str(exc)
    return bool(jetons.access_token), "autorisation accordée et mémorisée"


def _fabrique_rafraichissement(cw: dict):
    def rafraichir() -> str:
        jetons = oauth.charger_jetons(cw["url"])
        if jetons.refresh_token:
            return oauth.rafraichir(cw["url"], jetons).access_token
        if cw.get("client_id") and cw.get("client_secret"):
            jetons = oauth.client_credentials(cw.get("token_endpoint", ""),
                                              cw["client_id"], cw["client_secret"],
                                              cw.get("scopes") or None)
            oauth.enregistrer_jetons(cw["url"], jetons)
            return jetons.access_token
        return ""
    return rafraichir


def connecter(cfg: dict, echo=print, interactif: bool = False):
    """Établit la session MCP authentifiée. Retourne (client, résultat d'erreur).

    En cas d'échec, le client renvoyé est ``None`` et le ``ResultatCW`` porte le
    motif — jamais d'exception propagée : l'appelant continue sans enrichissement.
    """
    cw = cfg.get("cargowise", {})
    res = ResultatCW()
    if not cw.get("url"):
        res.message = "aucune URL de serveur MCP configurée"
        res.avertissements.append(res.message)
        return None, res
    try:
        jeton, etat = preparer_jeton(cw, echo=echo, interactif=interactif)
        mcp = _MCP(cw["url"], jeton, float(cw.get("timeout_s", 20)),
                   _fabrique_rafraichissement(cw))
        mcp.initialiser()
        outils = mcp.lister_outils()
        res.outils = [o.get("name", "") for o in outils]
    except AutorisationRequise as exc:
        res.autorisation_requise = True
        res.message = f"autorisation OAuth requise ({exc})"
        res.avertissements.append(
            res.message + " — lancer « lancer.py --autoriser » pour approuver "
            "l'accès dans le navigateur")
        return None, res
    except (urllib.error.URLError, OSError, RuntimeError, ValueError) as exc:
        res.message = f"serveur MCP injoignable ({exc})"
        res.avertissements.append(res.message)
        return None, res
    res.statut = etat
    return mcp, res


def interroger(cfg: dict, cles: list[str], echo=print,
               mrns: list[str] | None = None) -> ResultatCW:
    """Lit les clés connues ou recherche par MRN via le MCP CargoWise.

    L'outil de recherche est optionnel : son absence est distinguée d'une
    recherche vide. Voir CONTRAT-IKAMO-MRN.md pour le contrat à fournir serveur.
    """
    cw = cfg.get("cargowise", {})
    if not cw.get("active"):
        return ResultatCW(message="enrichissement CargoWise désactivé")
    mcp, res = connecter(cfg, echo=echo, interactif=bool(cw.get("autorisation_interactive")))
    if mcp is None:
        return res
    cles = [c for c in dict.fromkeys(cles) if c]
    if not cles and 'cargowise_find_by_mrn' in res.outils and not cw.get('_index_deja_interroge'):
        return _interroger_index(cfg, mcp, res, mrns or [], echo)
    attendus = {}
    source_bi = ''
    bi_active = cfg.get('bi', {}).get('active', False)
    if not cles and bi_active:
        from . import bi_client
        resolution = bi_client.resoudre(cfg, mrns or [])
        res.avertissements.extend(f"BI : {m}" for m in resolution.messages)
        attendus = resolution.cles
        source_bi = resolution.source
        if resolution.dossiers:
            return _interroger_dossiers_bi(mcp, res, resolution)
        cles = list(attendus)
        if not cles:
            res.message = "Liaison PDF / CargoWise non résolue par la BI ; voir le diagnostic BI"
            return res
    if not cles:
        valides = list(dict.fromkeys(m for m in (mrns or [])
                                    if re.fullmatch(r'\d{2}[A-Z]{2}[A-Z0-9]{14}', m)))
        if not valides:
            res.message = "Recherche CargoWise impossible : aucun MRN complet extrait du PDF"
            return res
        recherche = mcp.nom_outil(['cargowise_find_arrival_by_mrn'])
        if not recherche:
            res.message = ("Liaison PDF / CargoWise indisponible : le serveur CargoWise "
                           "n'expose pas cargowise_find_arrival_by_mrn. "
                           "Aucune recherche effectuée ; cela ne prouve pas "
                           "l'absence de déclaration dans CargoWise")
            return res
        for mrn in valides:
            try:
                reponse = _json_souple(mcp.appeler_outil(recherche, {'mrn': mrn}))
                cle = _cle_arrivee(reponse, mrn)
                if cle in attendus and attendus[cle] != mrn:
                    raise ValueError("une clé NCT est associée à plusieurs MRN")
                attendus[cle] = mrn
            except AutorisationRequise as exc:
                res.autorisation_requise = True
                res.avertissements.append(f"{mrn} : autorisation expirée ({exc})")
            except (RuntimeError, OSError, ValueError) as exc:
                res.avertissements.append(f"{mrn} : recherche non résolue ({exc})")
        cles = list(attendus)
        if not cles:
            res.message = "Aucune déclaration d'arrivée associée automatiquement ; voir les motifs"
            return res

    outil = mcp.nom_outil(cw.get("outil_entete", []), r"get_ncts|ncts_header")
    if not outil:
        res.message = ("aucun outil d'en-tête NCTS sur le serveur "
                       f"({', '.join(res.outils) or 'aucun outil exposé'})")
        res.avertissements.append(res.message)
        return res
    parametre = mcp.parametre(outil, ["declarationKey", "key", "declaration_key"])

    for cle in cles:
        try:
            texte = mcp.appeler_outil(outil, {parametre: cle})
        except AutorisationRequise as exc:
            res.autorisation_requise = True
            res.avertissements.append(f"{cle} : autorisation expirée ({exc})")
            continue
        except (RuntimeError, OSError, ValueError) as exc:
            res.avertissements.append(f"{cle} : {str(exc)[:160]}")
            continue
        entete = lire_entete_ncts(texte)
        if cle in attendus and (entete.get('mrn') != attendus[cle]
                                or entete.get('type_mouvement') != 'A'):
            res.avertissements.append(f"{cle} : MRN ou mouvement d'arrivée non confirmé par CargoWise")
            continue
        if entete:
            if source_bi:
                entete['source_liaison_bi'] = source_bi
            res.ok = True
            res.entete[cle] = entete
            continue
        res.avertissements.append(f"{cle} : aucun en-tête NCTS renvoyé")
    res.message = (f"en-tête NCTS récupéré ({res.statut})" if res.ok
                   else "aucune donnée NCTS récupérée")
    return res


def _interroger_dossiers_bi(mcp, res, resolution):
    """Confirme l'eDoc du shipment avant de lire les déclarations liées."""
    outil = mcp.nom_outil(['cargowise_get_shipment_context'])
    outil_nct = mcp.nom_outil(['cargowise_get_ncts'])
    if not outil:
        res.message = "Dossier trouvé en BI, mais outil de contexte shipment indisponible dans CargoWise"
        return res
    contextes, entetes = {}, {}
    for mrn, dossier in resolution.dossiers.items():
        try:
            if dossier not in contextes:
                contextes[dossier] = _json_souple(mcp.appeler_outil(outil, {'shipmentNumber': dossier}))
            contexte = contextes[dossier]
            if not isinstance(contexte, dict) or not isinstance(contexte.get('documents'), list):
                raise ValueError('contexte shipment non exploitable')
            documents = [doc for doc in contexte['documents'] if isinstance(doc, dict)
                         and re.sub(r'(?i)\.pdf$', '', str(doc.get('file_name', ''))) == mrn]
            if not documents:
                raise ValueError("le document portant le MRN n'est pas confirmé dans les eDocs CargoWise")
            res.liaisons_bi[mrn] = {'dossier': dossier, 'source_liaison_bi': resolution.source,
                                   'document': documents[0]['file_name']}
            liens = contexte.get('related')
            if not isinstance(liens, list):
                raise ValueError('liste des déclarations liées non disponible')
            cles = list(dict.fromkeys(lien['key'] for lien in liens
                        if isinstance(lien, dict) and isinstance(lien.get('key'), str)
                        and re.fullmatch(r'NCT\d{6,10}', lien['key'])))
            if not cles:
                res.avertissements.append(f'{mrn} : dossier {dossier} confirmé, aucun lien NCT renvoyé par CargoWise ; DM non récupéré')
                continue
            if len(cles) > 20 or not outil_nct:
                raise ValueError('déclarations liées non vérifiables (outil absent ou plus de 20 liens)')
            correspondances = []
            for cle in cles:
                if cle not in entetes:
                    entetes[cle] = lire_entete_ncts(mcp.appeler_outil(outil_nct, {'declarationKey': cle}))
                entete = entetes[cle]
                if not entete.get('mrn') or not entete.get('type_mouvement'):
                    raise ValueError('déclaration liée incomplète : association non décidée')
                if entete['mrn'] == mrn and entete['type_mouvement'] == 'A':
                    correspondances.append((cle, entete))
            if len(correspondances) != 1:
                res.avertissements.append(f'{mrn} : {len(correspondances)} déclarations d’arrivée correspondantes ; DM non récupéré')
                continue
            cle, entete = correspondances[0]
            res.entete[cle] = {**entete, 'dossier': dossier, 'source_liaison_bi': resolution.source}
        except AutorisationRequise:
            res.autorisation_requise = True
            res.avertissements.append(f'{mrn} : autorisation CargoWise expirée')
        except (RuntimeError, OSError, ValueError):
            res.avertissements.append(f'{mrn} : lecture du contexte ou des déclarations CargoWise incomplète ; DM non récupéré')
    res.ok = bool(res.entete)
    res.message = (f"BI / CargoWise : {len(res.liaisons_bi)} dossier(s) confirmé(s), "
                   f"{len(res.entete)} déclaration(s) d'arrivée correspondante(s)")
    return res


def _cle_arrivee(reponse, mrn: str) -> str:
    """Refuse résultats incomplets/ambigus avant toute lecture ou fusion."""
    if not isinstance(reponse, dict) or reponse.get('complete') is not True:
        raise ValueError("réponse de recherche incomplète ou invalide")
    if reponse.get('mrn') != mrn or not isinstance(reponse.get('matches'), list):
        raise ValueError("réponse de recherche sans MRN exact ou liste de résultats")
    candidats = reponse['matches']
    if not candidats:
        raise ValueError("aucune déclaration d'arrivée trouvée pour ce MRN")
    if len(candidats) != 1:
        raise ValueError("plusieurs déclarations candidates : rapprochement à vérifier")
    candidat = candidats[0]
    if (not isinstance(candidat, dict) or candidat.get('mrn') != mrn
            or candidat.get('movement_type') != 'A'
            or not re.fullmatch(r'NCT\d{6,10}', str(candidat.get('declarationKey', '')))):
        raise ValueError("candidat sans clé NCT, MRN exact ou mouvement d'arrivée")
    return candidat['declarationKey']


def _interroger_index(cfg, mcp, res, mrns, echo):
    """Recherche native en premier, BI en repli uniquement pour les MRN absents."""
    absents = []
    for mrn in dict.fromkeys(mrns):
        if not re.fullmatch(r'\d{2}[A-Z]{2}[A-Z0-9]{14}', mrn):
            res.avertissements.append('Recherche ignorée : MRN incomplet')
            continue
        try:
            # Pas de balayage de centaines de clés dans la boucle de surveillance.
            reponse = _json_souple(mcp.appeler_outil('cargowise_find_by_mrn',
                {'mrn': mrn, 'refresh': False, 'include_summary': False}))
            if not isinstance(reponse, dict) or reponse.get('mrn') != mrn:
                raise ValueError('réponse sans MRN exact')
            matches = reponse.get('matches')
            if not isinstance(matches, list):
                raise ValueError('liste de candidats absente')
            if reponse.get('found') is False and not matches:
                res.avertissements.append(f'{mrn} : absent de l’index NCTS ; cela ne prouve pas son absence dans CargoWise')
                absents.append(mrn)
                continue
            if reponse.get('found') is not True or not matches:
                raise ValueError('résultat de recherche incohérent')
            for candidat in matches:
                if not isinstance(candidat, dict) or candidat.get('mrn') != mrn or candidat.get('movement_type') not in ('A', 'D'):
                    raise ValueError('candidat incomplet ou MRN différent')
            arrivees = [c for c in matches if c['movement_type'] == 'A']
            if len(arrivees) != 1:
                raise ValueError(f'{len(arrivees)} déclarations d’arrivée candidates : association non décidée')
            cle = arrivees[0].get('key', '')
            if not re.fullmatch(r'NCT\d{6,10}', str(cle)):
                raise ValueError('clé NCT invalide')
            # Relire la déclaration : le cache de recherche peut être ancien.
            entete = lire_entete_ncts(mcp.appeler_outil('cargowise_get_ncts', {'key': cle}))
            if entete.get('mrn') != mrn or entete.get('type_mouvement') != 'A':
                raise ValueError('MRN ou mouvement d’arrivée non confirmé par la déclaration')
            if cle in res.entete and res.entete[cle].get('mrn') != mrn:
                raise ValueError('clé NCT associée à plusieurs MRN')
            res.entete[cle] = entete
        except AutorisationRequise:
            res.autorisation_requise = True
            res.avertissements.append(f'{mrn} : autorisation CargoWise requise')
        except (RuntimeError, OSError, ValueError) as exc:
            res.avertissements.append(f'{mrn} : recherche NCTS non résolue ({exc})')
    if absents and cfg.get('bi', {}).get('active'):
        repli_cfg = {**cfg, 'cargowise': {**cfg['cargowise'], '_index_deja_interroge': True}}
        repli = interroger(repli_cfg, [], echo=echo, mrns=absents)
        res.liaisons_bi.update(repli.liaisons_bi)
        res.entete.update(repli.entete)
        res.avertissements.extend(repli.avertissements)
        res.autorisation_requise |= repli.autorisation_requise
    res.ok = bool(res.entete)
    res.message = (f'CargoWise : {len(res.entete)} déclaration(s) d’arrivée récupérée(s), '
                   f'{len(res.liaisons_bi)} dossier(s) confirmé(s) via la BI')
    return res
