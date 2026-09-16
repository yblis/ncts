#!/usr/bin/env python3
"""Vérifie la réutilisation du client OAuth enregistré (cas IKAMO).

IKAMO ne déclare que ``authorization_code`` : pas de refresh_token, et l'URI de
redirection du client public PKCE est figée. Une seconde autorisation doit donc
réutiliser le MÊME client (et non en enregistrer un nouveau à chaque fois).

Usage : python3 tools/test_reutilisation_client.py [port]
"""

import sys
import threading
import urllib.error
import urllib.request
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
from ulix_ncts import oauth  # noqa: E402

PORT = sys.argv[1] if len(sys.argv) > 1 else "8767"
URL = f"http://127.0.0.1:{PORT}/mcp"
echecs: list[str] = []


def verifier(nom, condition, detail=""):
    print(f"  {'OK  ' if condition else 'ECHEC'} {nom}" + (f" — {detail}" if detail else ""))
    if not condition:
        echecs.append(nom)


def lancer_flux():
    """Rejoue une autorisation en suivant le lien comme le ferait un navigateur."""
    lien: list[str] = []

    def suivre():
        for _ in range(100):
            if lien:
                break
            threading.Event().wait(0.1)
        if lien:
            try:
                urllib.request.urlopen(lien[0], timeout=15).read()
            except urllib.error.URLError:
                pass

    threading.Thread(target=suivre, daemon=True).start()
    return oauth.autoriser(URL, ouvrir_navigateur=False,
                           echo=lambda *a: lien.append(a[-1]) if "http" in a[-1] else None)


print("1) première autorisation : enregistre un client")
oauth.oublier_jetons(URL)
oauth.oublier_client(URL)
j1 = lancer_flux()
c1 = oauth.charger_client(URL)
verifier("client mémorisé localement", bool(c1.get("client_id")), c1.get("client_id", ""))
verifier("URI de redirection conservée", bool(c1.get("redirect_uris")),
         str(c1.get("redirect_uris")))
verifier("pas de refresh_token émis (comme IKAMO)", not j1.refresh_token)

print("\n2) seconde autorisation : doit RÉUTILISER le même client")
j2 = lancer_flux()
c2 = oauth.charger_client(URL)
verifier("même client_id réutilisé", c2.get("client_id") == c1.get("client_id"),
         f"{c1.get('client_id')} -> {c2.get('client_id')}")
verifier("même URI de redirection", c2.get("redirect_uris") == c1.get("redirect_uris"))
verifier("nouveau jeton obtenu", bool(j2.access_token) and j2.access_token != j1.access_token)

print("\n3) jeton expiré sans refresh_token : message explicite")
jetons = oauth.charger_jetons(URL)
jetons.expires_at = 0
jetons.refresh_token = ""
oauth.enregistrer_jetons(URL, jetons)
from ulix_ncts import cw_client  # noqa: E402

jeton, message = cw_client.preparer_jeton({"url": URL, "token": ""},
                                          echo=lambda *_: None)
verifier("aucun jeton exploité", not jeton)
verifier("message mentionne refresh_token", "refresh_token" in message, message)

print()
if echecs:
    print(f"ECHEC : {len(echecs)} vérification(s) -> {', '.join(echecs)}")
    sys.exit(1)
print("Réutilisation du client OAuth : conforme.")
