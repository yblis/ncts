#!/usr/bin/env python3
"""Valide la chaîne OAuth du client contre le faux serveur MCP.

Rejoue exactement ce que fait un navigateur : récupère le lien d'autorisation
construit par `oauth.autoriser`, l'appelle (le faux serveur approuve et
redirige), et laisse la redirection atteindre le serveur local du client.

Usage : python3 tools/test_oauth.py [port]
"""

import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
from ulix_ncts import config as C, cw_client, oauth  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "8765"
URL = f"http://127.0.0.1:{PORT}/mcp"

echecs = []


def verifier(nom, condition, detail=""):
    print(f"  {'OK  ' if condition else 'ECHEC'} {nom}" + (f" — {detail}" if detail else ""))
    if not condition:
        echecs.append(nom)


# --- 0) repartir d'un état propre -------------------------------------------
oauth.oublier_jetons(URL)
print("1) sans jeton : le client doit signaler l'autorisation requise")
cfg = C.charger()
cfg["cargowise"].update({"active": True, "url": URL, "token": "",
                         "autorisation_interactive": False})
res = cw_client.interroger(cfg, ["_diagnostic_"], echo=lambda *_: None)
verifier("401 détecté", res.autorisation_requise, res.message)
verifier("aucune donnée exploitée", not res.ok)

# --- 1) flux interactif, lien suivi comme le ferait un navigateur -----------
print("\n2) flux d'autorisation (découverte -> DCR -> PKCE -> code -> jeton)")
lien: list[str] = []


def suivre_lien():
    """Attend que le client imprime le lien, puis l'appelle comme un navigateur."""
    for _ in range(100):
        if lien:
            break
        threading.Event().wait(0.1)
    if not lien:
        return
    try:
        urllib.request.urlopen(lien[0], timeout=15).read()
    except urllib.error.URLError as exc:
        print(f"  (appel du lien : {exc})")


fil = threading.Thread(target=suivre_lien, daemon=True)
fil.start()
jetons = oauth.autoriser(URL, ouvrir_navigateur=False,
                         echo=lambda *args: lien.append(args[-1]) if "http" in args[-1] else None)
verifier("access_token obtenu", bool(jetons.access_token))
verifier("refresh_token obtenu", bool(jetons.refresh_token))
verifier("token_endpoint découvert", jetons.token_endpoint.endswith("/token"))
verifier("client_id (enregistrement dynamique)", bool(jetons.client_id), jetons.client_id)
verifier("scopes repris du serveur", jetons.scopes == ["cargowise.read"], str(jetons.scopes))
verifier("jeton considéré valide", jetons.valide)

# --- 2) le jeton mémorisé doit être réutilisé ------------------------------
print("\n3) jeton mémorisé réutilisé (aucune nouvelle autorisation)")
jeton, etat = cw_client.preparer_jeton(cfg["cargowise"], echo=lambda *_: None)
verifier("jeton mémorisé repris", jeton == jetons.access_token, etat)
verifier("fichier de jetons en 600", (oauth.CHEMIN_JETONS.stat().st_mode & 0o777) == 0o600,
         oct(oauth.CHEMIN_JETONS.stat().st_mode & 0o777))

# --- 3) appel MCP authentifié de bout en bout ------------------------------
print("\n4) appel MCP authentifié (en-tête NCTS)")
res = cw_client.interroger(cfg, ["_diagnostic_"], echo=lambda *_: None)
verifier("appel accepté", res.ok, res.message)
verifier("outil d'en-tête trouvé", bool(res.entete), str(list(res.entete)[:1]))
charge = next(iter(res.entete.values()), {})
verifier("MRN renvoyé", bool(charge.get("entrynumber")), charge.get("entrynumber", ""))
verifier("statut douane renvoyé", bool(charge.get("customsstatus")),
         charge.get("customsstatus", ""))
verifier("DM (lrn) renvoyé", bool(charge.get("lrn")), charge.get("lrn", ""))

# --- 4) rafraîchissement du jeton ------------------------------------------
print("\n5) rafraîchissement d'un jeton expiré")
expire = oauth.charger_jetons(URL)
expire.expires_at = 0                      # force l'expiration
oauth.enregistrer_jetons(URL, expire)
jeton, etat = cw_client.preparer_jeton(cfg["cargowise"], echo=lambda *_: None)
verifier("jeton rafraîchi", bool(jeton) and jeton != expire.access_token, etat)
verifier("mémorisé à nouveau en 600",
         (oauth.CHEMIN_JETONS.stat().st_mode & 0o777) == 0o600)

# --- 5) le jeton ne fuit jamais dans les messages --------------------------
print("\n6) étanchéité : le jeton n'apparaît dans aucun message")
res = cw_client.interroger(cfg, ["_diagnostic_"], echo=lambda *_: None)
textes = " ".join([res.message, *res.avertissements, *(str(v) for v in res.entete.values())])
verifier("jeton absent des messages", jeton not in textes)
verifier("refresh_token absent des messages", (expire.refresh_token or "x") not in textes)

print()
if echecs:
    print(f"ECHEC : {len(echecs)} vérification(s) en échec -> {', '.join(echecs)}")
    sys.exit(1)
print("Toutes les vérifications OAuth passent.")
