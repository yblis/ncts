#!/usr/bin/env python3
"""Faux serveur MCP protégé par OAuth — sert à valider le client sans CargoWise.

Il expose :
  * POST /mcp                       — point MCP (401 sans jeton, JSON-RPC sinon) ;
  * GET  /.well-known/oauth-protected-resource ;
  * GET  /.well-known/oauth-authorization-server ;
  * POST /register                  — enregistrement dynamique du client ;
  * GET  /authorize                 — approuve automatiquement et redirige ;
  * POST /token                     — code + PKCE, puis refresh_token.

Usage : python3 tools/faux_mcp_oauth.py [port]
"""

import base64
import hashlib
import json
import sys
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
BASE = f"http://127.0.0.1:{PORT}"

# Mode « IKAMO » : simule un serveur sans renouvellement de jeton — portées
# « read » et « write », uniquement le flux authorization_code, AUCUN
# refresh_token émis. Sert à répéter le comportement du vrai serveur.
import os  # noqa: E402

MODE_IKAMO = os.environ.get("IKAMO_LIKE", "").strip().lower() in ("1", "true", "oui")
SCOPES = ["read", "write"] if MODE_IKAMO else ["cargowise.read"]

CODES: dict[str, dict] = {}
TOKENS: dict[str, dict] = {}
CLIENTS: dict[str, dict] = {}


class Main(BaseHTTPRequestHandler):
    def _json(self, code, objet):
        corps = json.dumps(objet).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(corps)))
        self.end_headers()
        self.wfile.write(corps)

    def _corps(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n).decode("utf-8", "replace")

    def log_message(self, *a):
        print(f"  [faux-mcp] {self.command} {self.path.split('?')[0]}")

    # ------------------------------------------------------------------ GET
    def do_GET(self):                                       # noqa: N802
        chemin = urllib.parse.urlsplit(self.path)
        if chemin.path == "/.well-known/oauth-protected-resource":
            return self._json(200, {"resource": f"{BASE}/mcp",
                                    "authorization_servers": [BASE],
                                    "bearer_methods_supported": ["header"],
                                    "scopes_supported": SCOPES})
        if chemin.path == "/.well-known/oauth-authorization-server":
            meta = {
                "issuer": BASE,
                "authorization_endpoint": f"{BASE}/authorize",
                "token_endpoint": f"{BASE}/token",
                "registration_endpoint": f"{BASE}/register",
                "response_types_supported": ["code"],
                "grant_types_supported": ["authorization_code"],
                "token_endpoint_auth_methods_supported": ["none"],
                "code_challenge_methods_supported": ["S256"],
                "scopes_supported": SCOPES,
            }
            if not MODE_IKAMO:
                meta["grant_types_supported"] = ["authorization_code", "refresh_token",
                                                 "client_credentials"]
            return self._json(200, meta)
        if chemin.path == "/authorize":
            q = urllib.parse.parse_qs(chemin.query)
            code = base64.urlsafe_b64encode(hashlib.sha256(
                q.get("state", [""])[0].encode()).digest()).rstrip(b"=").decode()[:24]
            CODES[code] = {"client_id": q.get("client_id", [""])[0],
                           "redirect_uri": q.get("redirect_uri", [""])[0],
                           "challenge": q.get("code_challenge", [""])[0],
                           "scope": q.get("scope", [""])[0]}
            cible = (q.get("redirect_uri", [""])[0]
                     + "?code=" + code + "&state=" + q.get("state", [""])[0])
            self.send_response(302)
            self.send_header("Location", cible)
            self.end_headers()
            return
        return self._json(404, {"error": "not_found"})

    # ----------------------------------------------------------------- POST
    def do_POST(self):                                      # noqa: N802
        chemin = urllib.parse.urlsplit(self.path).path
        if chemin == "/mcp":
            if not (self.headers.get("Authorization") or "").startswith("Bearer "):
                corps = b'{"error":"unauthorized"}'
                self.send_response(401)
                self.send_header(
                    "WWW-Authenticate",
                    f'Bearer resource_metadata="{BASE}/.well-known/oauth-protected-resource"')
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(corps)))
                self.end_headers()
                self.wfile.write(corps)
                return
            jeton = self.headers["Authorization"].split(" ", 1)[1]
            if jeton not in TOKENS:
                return self._json(401, {"error": "invalid_token"})
            demande = json.loads(self._corps() or "{}")
            methode = demande.get("method")
            if methode == "initialize":
                return self._json(200, {"jsonrpc": "2.0", "id": demande.get("id"),
                                        "result": {"protocolVersion": "2025-06-18",
                                                   "capabilities": {}, "serverInfo":
                                                               {"name": "faux", "version": "1"}}})
            if methode == "tools/list":
                return self._json(200, {"jsonrpc": "2.0", "id": demande.get("id"),
                                        "result": {"tools": [{"name": "cargowise_get_ncts"},
                                                             {"name": "cargowise_get_record"}]}})
            if methode == "tools/call":
                args = demande.get("params", {}).get("arguments", {})
                cle = args.get("declarationKey", "")
                if cle == "_diagnostic_":
                    charge = {"entryNumber": "26CH07STTESTDEMO1",
                              "customsStatus": "CL1", "lrn": "PMP 20260999",
                              "shipmentId": "SBDY26009999"}
                else:
                    charge = {"entryNumber": cle, "customsStatus": "CL1 Closed",
                              "lrn": "PMP 20260999", "movementType": "A",
                              "arrivalDate": "2026-09-15T10:00:00",
                              "shipmentId": "SBDY26009999"}
                return self._json(200, {"jsonrpc": "2.0", "id": demande.get("id"),
                                        "result": {"content": [
                                            {"type": "text", "text": json.dumps(charge)}]}})
            return self._json(200, {"jsonrpc": "2.0", "id": demande.get("id"), "result": {}})

        if chemin == "/register":
            demande = json.loads(self._corps() or "{}")
            cid = "client-faux-" + str(len(CLIENTS) + 1)
            CLIENTS[cid] = {"redirect_uris": demande.get("redirect_uris", [])}
            return self._json(201, {"client_id": cid,
                                    "redirect_uris": demande.get("redirect_uris", []),
                                    "token_endpoint_auth_method": "none"})

        if chemin == "/token":
            form = urllib.parse.parse_qs(self._corps())
            grant = form.get("grant_type", [""])[0]
            if grant == "authorization_code":
                code = form.get("code", [""])[0]
                infos = CODES.pop(code, None)
                if not infos:
                    return self._json(400, {"error": "invalid_grant"})
                verifieur = form.get("code_verifier", [""])[0]
                defi = base64.urlsafe_b64encode(hashlib.sha256(
                    verifieur.encode()).digest()).rstrip(b"=").decode()
                if defi != infos["challenge"]:
                    return self._json(400, {"error": "invalid_grant",
                                            "error_description": "PKCE invalide"})
            elif grant == "refresh_token":
                if form.get("refresh_token", [""])[0] not in TOKENS:
                    return self._json(400, {"error": "invalid_grant"})
            elif grant == "client_credentials":
                if not form.get("client_secret", [""])[0]:
                    return self._json(401, {"error": "invalid_client"})
            else:
                return self._json(400, {"error": "unsupported_grant_type"})
            acces = "at-" + base64.urlsafe_b64encode(
                hashlib.sha256(str(len(TOKENS) + 1).encode()).digest()).decode()[:20]
            reponse = {"access_token": acces, "token_type": "Bearer",
                       "expires_in": 60 if MODE_IKAMO else 3600,
                       "scope": " ".join(SCOPES)}
            if not MODE_IKAMO:
                # IKAMO n'émet PAS de refresh_token : on ne le simule qu'en mode générique
                rafraich = "rt-" + str(len(TOKENS) + 1)
                TOKENS[rafraich] = {"scope": " ".join(SCOPES)}
                reponse["refresh_token"] = rafraich
            TOKENS[acces] = {"scope": " ".join(SCOPES)}
            return self._json(200, reponse)
        return self._json(404, {"error": "not_found"})


if __name__ == "__main__":
    print(f"Faux serveur MCP OAuth sur {BASE}/mcp  (Ctrl-C pour arrêter)")
    serveur = HTTPServer(("127.0.0.1", PORT), Main)
    threading.Thread(target=serveur.serve_forever, daemon=True).start()
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        print("\narrêt")
