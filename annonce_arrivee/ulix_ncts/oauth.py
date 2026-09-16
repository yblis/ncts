"""OAuth 2.1 pour un serveur MCP distant (RFC 9728 / 8414 / 7591, PKCE).

Le protocole MCP protège un serveur distant par OAuth : un appel non
authentifié renvoie 401 avec un en-tête ``WWW-Authenticate: Bearer
resource_metadata="…"``, qui mène aux métadonnées du serveur d'autorisation.

Ce module implémente la chaîne complète, sans dépendance externe (urllib) :

1. **découverte** — ``/.well-known/oauth-protected-resource`` puis
   ``/.well-known/oauth-authorization-server`` (avec repli OpenID Connect) ;
2. **enregistrement dynamique du client** (RFC 7591) s'il est proposé ;
3. **autorisation par code + PKCE S256** — un serveur local reçoit la
   redirection et l'utilisateur approuve dans son navigateur ;
4. **échange du code et stockage** du jeton d'accès et du jeton de
   rafraîchissement (``~/.ulix_ncts_tokens.json``, droits 600) ;
5. **rafraîchissement** automatique, et **client_credentials** en repli pour les
   serveurs machine-à-machine.

Le jeton n'est jamais journalisé ni affiché : seul son état (présent, expiré,
rafraîchi) est rapporté.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from dataclasses import dataclass, field
from pathlib import Path

from . import plateforme

CHEMIN_JETONS = Path.home() / ".ulix_ncts_tokens.json"
REDIRECT_PATH = "/callback"
DELAI_AUTORISATION_S = 240


class ErreurOAuth(RuntimeError):
    """Échec d'authentification (message destiné à l'utilisateur)."""


# ------------------------------------------------------------------ utilitaires
def _json(url: str, timeout: float = 15.0, entetes: dict | None = None) -> dict:
    req = urllib.request.Request(url, headers=entetes or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as rep:
            return json.loads(rep.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        raise ErreurOAuth(f"HTTP {exc.code} sur {url}") from exc
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise ErreurOAuth(f"{url} injoignable ({exc})") from exc


def _post_form(url: str, donnees: dict, timeout: float = 20.0) -> dict:
    corps = urllib.parse.urlencode(donnees).encode("utf-8")
    req = urllib.request.Request(url, data=corps, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as rep:
            return json.loads(rep.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise ErreurOAuth(f"HTTP {exc.code} sur {url} : {detail}") from exc
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise ErreurOAuth(f"{url} injoignable ({exc})") from exc


def _post_json(url: str, donnees: dict, timeout: float = 20.0) -> dict:
    corps = json.dumps(donnees).encode("utf-8")
    req = urllib.request.Request(url, data=corps, method="POST")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as rep:
            return json.loads(rep.read().decode("utf-8", "replace") or "{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:300]
        raise ErreurOAuth(f"HTTP {exc.code} sur {url} : {detail}") from exc
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        raise ErreurOAuth(f"{url} injoignable ({exc})") from exc


def _origine(url: str) -> str:
    p = urllib.parse.urlsplit(url)
    return f"{p.scheme}://{p.netloc}"


def _port_depuis_uri(uri: str) -> int:
    """Port d'une URI de redirection (0 si indéterminé)."""
    try:
        return urllib.parse.urlsplit(uri).port or 0
    except ValueError:
        return 0


def portee_par_defaut(metadonnees: dict, voulus: list | None = None) -> list[str]:
    """Portée à demander : celle demandée, sinon la LECTURE SEULE si proposée.

    Le serveur IKAMO annonce « read » et « write » ; ne demander que « read »
    évite de solliciter des droits d'écriture inutiles pour un traitement qui ne
    fait que lire un en-tête.
    """
    proposes = metadonnees.get("scopes_supported") or []
    if voulus:
        return [s for s in voulus if not proposes or s in proposes] or list(voulus)
    if "read" in proposes:
        return ["read"]
    return list(proposes)


# --------------------------------------------------------------- découvertes
def metadonnees_ressource(url_mcp: str, resource_metadata: str = "") -> dict:
    """Métadonnées du serveur protégé (RFC 9728).

    ``resource_metadata`` provient de l'en-tête ``WWW-Authenticate`` du 401 :
    c'est la piste la plus fiable, on la suit en priorité.
    """
    if resource_metadata:
        return _json(resource_metadata)
    base = _origine(url_mcp)
    for suffixe in ("/.well-known/oauth-protected-resource",
                    "/.well-known/oauth-protected-resource" + urllib.parse.urlsplit(url_mcp).path):
        try:
            return _json(base + suffixe)
        except ErreurOAuth:
            continue
    raise ErreurOAuth("métadonnées du serveur protégé introuvables "
                      "(/.well-known/oauth-protected-resource)")


def metadonnees_autorisation(issuer: str) -> dict:
    """Métadonnées du serveur d'autorisation (RFC 8414, repli OIDC)."""
    base = issuer.rstrip("/")
    for suffixe in ("/.well-known/oauth-authorization-server",
                    "/.well-known/openid-configuration",
                    "/.well-known/oauth-authorization-server" + urllib.parse.urlsplit(base).path):
        try:
            return _json(base + suffixe)
        except ErreurOAuth:
            continue
    raise ErreurOAuth(f"métadonnées du serveur d'autorisation introuvables ({base})")


def enregistrer_client(registration_endpoint: str, redirect_uri: str,
                       nom_client: str = "ULIX — annonce d'arrivée NCTS") -> dict:
    """Enregistrement dynamique du client (RFC 7591)."""
    return _post_json(registration_endpoint, {
        "client_name": nom_client,
        "redirect_uris": [redirect_uri],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "application_type": "native",
    })


# ------------------------------------------------------------------ PKCE
def _pkce() -> tuple[str, str]:
    verifieur = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    defi = base64.urlsafe_b64encode(
        hashlib.sha256(verifieur.encode()).digest()).rstrip(b"=").decode()
    return verifieur, defi


# --------------------------------------------------------- serveur de retour
class _Retour(http.server.BaseHTTPRequestHandler):
    """Reçoit la redirection OAuth sur 127.0.0.1 et capture le code."""

    code: str = ""
    etat: str = ""
    erreur: str = ""
    evenement = threading.Event()

    def do_GET(self):                                   # noqa: N802
        params = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)
        if urllib.parse.urlsplit(self.path).path != REDIRECT_PATH:
            self.send_response(404)
            self.end_headers()
            return
        type_retour = _Retour
        type_retour.code = (params.get("code") or [""])[0]
        type_retour.etat = (params.get("state") or [""])[0]
        type_retour.erreur = (params.get("error") or [""])[0]
        corps = ("<!doctype html><meta charset='utf-8'>"
                 "<h2>Autorisation reçue</h2>"
                 "<p>Vous pouvez fermer cet onglet et revenir au terminal.</p>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(corps.encode())))
        self.end_headers()
        self.wfile.write(corps.encode())
        type_retour.evenement.set()

    def log_message(self, *args):                        # silence
        pass


def _port_libre() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


# ------------------------------------------------------------------- jetons
@dataclass
class Jetons:
    access_token: str = ""
    refresh_token: str = ""
    expires_at: float = 0.0
    token_endpoint: str = ""
    client_id: str = ""
    client_secret: str = ""
    scopes: list = field(default_factory=list)

    @property
    def valide(self) -> bool:
        # marge de 60 s : on rafraîchit avant l'expiration réelle
        return bool(self.access_token) and time.time() < (self.expires_at - 60)


def charger_jetons(url: str) -> Jetons:
    if not CHEMIN_JETONS.is_file():
        return Jetons()
    try:
        donnees = json.loads(CHEMIN_JETONS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Jetons()
    entree = donnees.get(_origine(url)) or donnees.get(url) or {}
    return Jetons(access_token=entree.get("access_token", ""),
                  refresh_token=entree.get("refresh_token", ""),
                  expires_at=float(entree.get("expires_at", 0) or 0),
                  token_endpoint=entree.get("token_endpoint", ""),
                  client_id=entree.get("client_id", ""),
                  client_secret=entree.get("client_secret", ""),
                  scopes=entree.get("scopes", []) or [])


def enregistrer_jetons(url: str, jetons: Jetons) -> None:
    """Écrit le fichier de jetons en 600 (jamais lisible par les autres)."""
    donnees: dict = {}
    if CHEMIN_JETONS.is_file():
        try:
            donnees = json.loads(CHEMIN_JETONS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            donnees = {}
    donnees[_origine(url)] = {
        "access_token": jetons.access_token,
        "refresh_token": jetons.refresh_token,
        "expires_at": jetons.expires_at,
        "token_endpoint": jetons.token_endpoint,
        "client_id": jetons.client_id,
        "client_secret": jetons.client_secret,
        "scopes": jetons.scopes,
        "maj": int(time.time()),
    }
    tmp = CHEMIN_JETONS.with_suffix(".tmp")
    tmp.write_text(json.dumps(donnees, indent=2), encoding="utf-8")
    plateforme.restreindre(tmp)
    tmp.replace(CHEMIN_JETONS)
    plateforme.restreindre(CHEMIN_JETONS)


def oublier_jetons(url: str) -> None:
    """Supprime les jetons mémorisés pour ce serveur (réauthentification forcée).

    Le client enregistré (``client_id``) est CONSERVÉ : il reste valide côté
    serveur et évite un nouvel enregistrement dynamique à chaque autorisation.
    """
    if not CHEMIN_JETONS.is_file():
        return
    try:
        donnees = json.loads(CHEMIN_JETONS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    for cle in (_origine(url), url):
        donnees.pop(cle, None)
    CHEMIN_JETONS.write_text(json.dumps(donnees, indent=2), encoding="utf-8")
    plateforme.restreindre(CHEMIN_JETONS)


# ------------------------------------------------------- client enregistré
def _cle_client(url: str) -> str:
    return _origine(url) + "::client"


def charger_client(url: str) -> dict:
    """Client OAuth déjà enregistré auprès de ce serveur (sinon {})."""
    if not CHEMIN_JETONS.is_file():
        return {}
    try:
        donnees = json.loads(CHEMIN_JETONS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return donnees.get(_cle_client(url)) or {}


def enregistrer_client_local(url: str, client: dict) -> None:
    """Mémorise le client enregistré (aucun secret : client public PKCE)."""
    donnees: dict = {}
    if CHEMIN_JETONS.is_file():
        try:
            donnees = json.loads(CHEMIN_JETONS.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            donnees = {}
    donnees[_cle_client(url)] = client
    tmp = CHEMIN_JETONS.with_suffix(".tmp")
    tmp.write_text(json.dumps(donnees, indent=2), encoding="utf-8")
    plateforme.restreindre(tmp)
    tmp.replace(CHEMIN_JETONS)
    plateforme.restreindre(CHEMIN_JETONS)


def oublier_client(url: str) -> None:
    """Oublie le client OAuth enregistré (force un nouvel enregistrement)."""
    if not CHEMIN_JETONS.is_file():
        return
    try:
        donnees = json.loads(CHEMIN_JETONS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    donnees.pop(_cle_client(url), None)
    CHEMIN_JETONS.write_text(json.dumps(donnees, indent=2), encoding="utf-8")
    plateforme.restreindre(CHEMIN_JETONS)


def _depuis_reponse(reponse: dict, jetons: Jetons) -> Jetons:
    if not reponse.get("access_token"):
        raise ErreurOAuth("réponse du serveur d'autorisation sans access_token")
    jetons.access_token = reponse["access_token"]
    if reponse.get("refresh_token"):
        jetons.refresh_token = reponse["refresh_token"]
    duree = reponse.get("expires_in")
    jetons.expires_at = time.time() + float(duree) if duree else time.time() + 3600
    return jetons


def rafraichir(url: str, jetons: Jetons) -> Jetons:
    if not jetons.refresh_token or not jetons.token_endpoint:
        raise ErreurOAuth("aucun jeton de rafraîchissement disponible")
    donnees = {"grant_type": "refresh_token", "refresh_token": jetons.refresh_token,
               "client_id": jetons.client_id}
    if jetons.client_secret:
        donnees["client_secret"] = jetons.client_secret
    jetons = _depuis_reponse(_post_form(jetons.token_endpoint, donnees), jetons)
    enregistrer_jetons(url, jetons)
    return jetons


def client_credentials(token_endpoint: str, client_id: str, client_secret: str = "",
                       scopes: list | None = None) -> Jetons:
    """Flux machine-à-machine (repli quand aucun navigateur n'est disponible)."""
    donnees = {"grant_type": "client_credentials", "client_id": client_id}
    if client_secret:
        donnees["client_secret"] = client_secret
    if scopes:
        donnees["scope"] = " ".join(scopes)
    jetons = Jetons(token_endpoint=token_endpoint, client_id=client_id,
                    client_secret=client_secret, scopes=scopes or [])
    return _depuis_reponse(_post_form(token_endpoint, donnees), jetons)


# ------------------------------------------------------------ flux interactif
def autoriser(url_mcp: str, resource_metadata: str = "", scopes: list | None = None,
              client_id: str = "", client_secret: str = "", ouvrir_navigateur: bool = True,
              echo=print) -> Jetons:
    """Flux « code d'autorisation + PKCE » complet, avec enregistrement dynamique.

    Le client enregistré est mémorisé et réutilisé : un serveur comme IKAMO ne
    déclare que ``authorization_code`` (pas de refresh_token), donc chaque
    nouvelle autorisation réutilise le même client plutôt que d'en créer un.
    """
    ressource = metadonnees_ressource(url_mcp, resource_metadata)
    serveurs = ressource.get("authorization_servers") or []
    issuer = serveurs[0] if serveurs else _origine(url_mcp)
    metadonnees = metadonnees_autorisation(issuer)
    auth_endpoint = metadonnees.get("authorization_endpoint")
    token_endpoint = metadonnees.get("token_endpoint")
    if not auth_endpoint or not token_endpoint:
        raise ErreurOAuth("métadonnées d'autorisation incomplètes "
                          "(authorization_endpoint / token_endpoint)")
    methodes = metadonnees.get("code_challenge_methods_supported") or ["S256"]
    if "S256" not in methodes:
        raise ErreurOAuth(f"le serveur n'annonce pas PKCE S256 (proposé : {methodes})")

    port = _port_libre()
    redirect_uri = f"http://127.0.0.1:{port}{REDIRECT_PATH}"

    # --- client : fourni, mémorisé, ou enregistrement dynamique -------------
    mémorisé = charger_client(url_mcp) if not client_id else {}
    if not client_id and mémorisé.get("client_id"):
        client_id = mémorisé["client_id"]
        autorisees = mémorisé.get("redirect_uris") or []
        # un client public PKCE garde l'URI exacte enregistrée : on réutilise
        # le port d'origine quand on le connaît, sinon on réenregistre
        if autorisees:
            redirect_uri = autorisees[0]
            port = _port_depuis_uri(redirect_uri) or port
        echo(f"Client OAuth déjà enregistré réutilisé ({client_id}).")
    if not client_id:
        endpoint_enregistrement = metadonnees.get("registration_endpoint")
        if not endpoint_enregistrement:
            raise ErreurOAuth("aucun client OAuth fourni et le serveur ne propose pas "
                              "d'enregistrement dynamique : renseigner client_id "
                              "(et client_secret) dans la configuration")
        client = enregistrer_client(endpoint_enregistrement, redirect_uri)
        client_id = client.get("client_id", "")
        client_secret = client.get("client_secret", "") or client_secret
        if not client_id:
            raise ErreurOAuth("enregistrement dynamique sans client_id renvoyé")
        client["redirect_uris"] = client.get("redirect_uris") or [redirect_uri]
        enregistrer_client_local(url_mcp, client)
        echo(f"Client OAuth enregistré auprès du serveur ({client_id}).")

    portee = portee_par_defaut(metadonnees, scopes)
    verifieur, defi = _pkce()
    etat = secrets.token_urlsafe(24)
    parametres = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "state": etat,
        "code_challenge": defi,
        "code_challenge_method": "S256",
    }
    if portee:
        parametres["scope"] = " ".join(portee)
    if ressource.get("resource"):
        parametres["resource"] = ressource["resource"]
    lien = f"{auth_endpoint}?{urllib.parse.urlencode(parametres)}"

    _Retour.code = _Retour.etat = _Retour.erreur = ""
    _Retour.evenement.clear()
    try:
        serveur = http.server.HTTPServer(("127.0.0.1", port), _Retour)
    except OSError as exc:
        raise ErreurOAuth(
            f"impossible d'écouter sur {redirect_uri} ({exc}). Ce port est celui "
            f"enregistré pour ce client : réautoriser avec un nouveau client "
            f"(--nouveau-client) ou fermer l'application qui l'occupe") from exc
    fil = threading.Thread(target=serveur.handle_request, daemon=True)
    fil.start()

    echo("Autorisation OAuth requise.")
    if ouvrir_navigateur and webbrowser.open(lien):
        echo("Le navigateur s'est ouvert : approuvez l'accès, puis revenez ici.")
    else:
        echo("Ouvrez ce lien dans votre navigateur pour autoriser l'accès :")
        echo(f"  {lien}")
    if not _Retour.evenement.wait(DELAI_AUTORISATION_S):
        serveur.server_close()
        raise ErreurOAuth(f"aucune autorisation reçue dans les {DELAI_AUTORISATION_S} s")
    serveur.server_close()

    if _Retour.erreur:
        raise ErreurOAuth(f"autorisation refusée par le serveur ({_Retour.erreur})")
    if not _Retour.code:
        raise ErreurOAuth("aucun code d'autorisation reçu")
    if _Retour.etat and _Retour.etat != etat:
        raise ErreurOAuth("état OAuth incohérent (réponse non sollicitée)")

    donnees = {"grant_type": "authorization_code", "code": _Retour.code,
               "redirect_uri": redirect_uri, "client_id": client_id,
               "code_verifier": verifieur}
    if client_secret:
        donnees["client_secret"] = client_secret
    if ressource.get("resource"):
        donnees["resource"] = ressource["resource"]
    jetons = Jetons(token_endpoint=token_endpoint, client_id=client_id,
                    client_secret=client_secret, scopes=portee)
    jetons = _depuis_reponse(_post_form(token_endpoint, donnees), jetons)
    enregistrer_jetons(url_mcp, jetons)
    echo("Autorisation accordée (jeton mémorisé).")
    return jetons


def analyser_defi_authentification(entetes: dict) -> str:
    """Extrait ``resource_metadata`` d'un en-tête ``WWW-Authenticate`` (401)."""
    brut = ""
    for cle, valeur in (entetes or {}).items():
        if str(cle).lower() == "www-authenticate":
            brut = str(valeur)
            break
    if not brut:
        return ""
    m = __import__("re").search(r'resource_metadata\s*=\s*"([^"]+)"', brut)
    return m.group(1) if m else ""
