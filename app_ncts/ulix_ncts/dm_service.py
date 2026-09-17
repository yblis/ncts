"""Service central DM ; les postes n'ouvrent jamais directement la base SQLite."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import hmac
import json
import sqlite3
import urllib.error
import urllib.parse
import urllib.request

from .dm import ErreurDM, Registre


def serveur(registre, token, adresse=('127.0.0.1', 8766)):
    if len(token) < 32:
        raise ErreurDM('ULIX_DM_TOKEN doit contenir au moins 32 caractères')

    class Requetes(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Pas de token ni de données métier dans les logs HTTP.

        def repondre(self, code, data):
            corps = json.dumps(data, ensure_ascii=False).encode('utf-8')
            self.send_response(code)
            self.send_header('Content-Type', 'application/json; charset=utf-8')
            self.send_header('Content-Length', str(len(corps)))
            self.end_headers()
            self.wfile.write(corps)

        def traiter(self):
            self.connection.settimeout(15)
            if not hmac.compare_digest(self.headers.get('Authorization', ''), 'Bearer ' + token):
                self.repondre(401, {'erreur': 'Authentification DM requise'})
                return
            try:
                if self.command == 'GET' and self.path == '/statut':
                    self.repondre(200, registre.statut())
                    return
                if self.command != 'POST' or self.path not in ('/attribuer', '/consulter', '/prefixe'):
                    self.repondre(404, {'erreur': 'Opération inconnue'})
                    return
                taille = int(self.headers.get('Content-Length', '0'))
                if not 0 < taille <= 32768:
                    raise ErreurDM('Requête DM trop volumineuse ou vide')
                data = json.loads(self.rfile.read(taille))
                if not isinstance(data, dict):
                    raise ErreurDM('Objet JSON requis')
                if self.path == '/prefixe':
                    resultat = registre.prefixe(data.get('mrns'), data.get('pmp'), data.get('operateur', ''))
                else:
                    resultat = registre.attribuer(data.get('mrns'), data.get('operateur', ''),
                                                 data.get('existant', ''), simulation=self.path == '/consulter')
                self.repondre(200, resultat)
            except (ValueError, TypeError) as exc:
                self.repondre(409, {'erreur': str(exc)})
            except sqlite3.Error:
                self.repondre(503, {'erreur': 'Registre DM indisponible : aucune attribution confirmée'})

        do_GET = traiter
        do_POST = traiter

    return ThreadingHTTPServer(adresse, Requetes)


class Client:
    def __init__(self, cfg):
        self.cfg = cfg
        self.url = cfg.get('url', '').rstrip('/')
        u = urllib.parse.urlsplit(self.url)
        if u.scheme != 'https' and not (u.scheme == 'http' and u.hostname in ('localhost', '127.0.0.1', '::1')):
            raise ErreurDM('Configurer une URL DM HTTPS (HTTP autorisé seulement en local)')
        if not cfg.get('token'):
            raise ErreurDM('ULIX_DM_TOKEN manquant')

    def appeler(self, chemin, data=None):
        req = urllib.request.Request(self.url + chemin,
                data=json.dumps(data).encode() if data is not None else None,
                headers={'Authorization': 'Bearer ' + self.cfg['token'], 'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(req, timeout=float(self.cfg.get('timeout_s', 25))) as rep:
                resultat = json.load(rep)
        except urllib.error.HTTPError as exc:
            try:
                detail = json.loads(exc.read()).get('erreur', f'HTTP {exc.code}')
            except (ValueError, AttributeError):
                detail = f'HTTP {exc.code}'
            raise ErreurDM(str(detail)) from exc
        except (OSError, ValueError) as exc:
            raise ErreurDM('Service DM injoignable ou réponse invalide ; réessayer avec le même lot') from exc
        if not isinstance(resultat, dict):
            raise ErreurDM('Réponse du service DM invalide')
        return resultat

    def attribuer(self, mrns, existant='', simulation=False):
        return self.appeler('/consulter' if simulation else '/attribuer',
                            {'mrns': mrns, 'existant': existant, 'operateur': self.cfg.get('operateur', '')})
