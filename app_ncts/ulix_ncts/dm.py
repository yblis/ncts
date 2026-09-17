"""Registre central des annonces : transactions atomiques, aucun effacement."""
from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo
import json
from pathlib import Path
import re
import sqlite3


class ErreurDM(ValueError):
    pass


def annee_courante():
    return datetime.now(ZoneInfo('Europe/Zurich')).year


def references(mrns):
    if not isinstance(mrns, list) or not mrns or len(mrns) > 100:
        raise ErreurDM('Fournir les MRN de l’annonce (1 à 100)')
    valeurs = [str(m).strip().upper() for m in mrns]
    if any(not re.fullmatch(r'\d{2}[A-Z]{2}[A-Z0-9]{14}', m) for m in valeurs):
        raise ErreurDM('MRN incomplet : attribution DM impossible')
    if len(set(valeurs)) != len(valeurs):
        raise ErreurDM('MRN répété dans l’annonce')
    return sorted(valeurs)


def numero(valeur):
    # Les anciennes références LRN CargoWise peuvent porter le libellé « DM ».
    m = re.fullmatch(r'(?:DM )?(PMP )?(20\d{2})(\d{4})', str(valeur).strip())
    if not m:
        raise ErreurDM('Format DM attendu : AAAANNNN ou PMP AAAANNNN')
    return int(m[2]), int(m[3]), bool(m[1])


class Registre:
    """SQLite sur le disque local du serveur UNIQUEMENT, jamais sur SMB/NFS."""
    def __init__(self, chemin):
        self.chemin = str(Path(chemin).expanduser().resolve())
        Path(self.chemin).parent.mkdir(parents=True, exist_ok=True)
        with self.transaction() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS etat (id INTEGER PRIMARY KEY CHECK(id=1), bascule INTEGER);
                INSERT OR IGNORE INTO etat VALUES (1, NULL);
                CREATE TABLE IF NOT EXISTS compteurs (annee INTEGER PRIMARY KEY, dernier INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS annonces (
                    identite TEXT PRIMARY KEY, annee INTEGER NOT NULL, sequence INTEGER NOT NULL,
                    pmp INTEGER NOT NULL, UNIQUE(annee, sequence));
                CREATE TABLE IF NOT EXISTS transits (
                    mrn TEXT PRIMARY KEY, identite TEXT NOT NULL REFERENCES annonces(identite));
                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY, date TEXT NOT NULL, action TEXT NOT NULL,
                    operateur TEXT NOT NULL, detail TEXT NOT NULL);
            ''')

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.chemin, timeout=20, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON')
            db.execute('BEGIN IMMEDIATE')
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def _trace(self, db, action, operateur, detail):
        if not isinstance(operateur, str) or not operateur.strip():
            raise ErreurDM('Nom de l’opérateur requis')
        db.execute('INSERT INTO journal(date,action,operateur,detail) VALUES(?,?,?,?)',
                   (datetime.now().astimezone().isoformat(), action, operateur.strip(), json.dumps(detail)))

    def activer(self, dernier, operateur):
        if not re.fullmatch(r'20\d{6}', str(dernier)):
            raise ErreurDM('Dernier numéro Sisa attendu sur 8 chiffres, sans préfixe')
        an, seq, pmp = numero(dernier)
        if pmp or an != annee_courante():
            raise ErreurDM('Dernier numéro Sisa numérique de l’année courante requis')
        with self.transaction() as db:
            if db.execute('SELECT bascule FROM etat').fetchone()[0] is not None:
                raise ErreurDM('Bascule déjà effectuée : réinitialisation interdite')
            db.execute('INSERT INTO compteurs VALUES(?,?)', (an, seq))
            db.execute('UPDATE etat SET bascule=?', (int(dernier),))
            self._trace(db, 'bascule', operateur, {'dernier_sisa': dernier})
        return self.statut()

    def statut(self):
        with self.transaction() as db:
            bascule = db.execute('SELECT bascule FROM etat').fetchone()[0]
            return {'actif': bascule is not None, 'dernier_sisa_bascule': bascule,
                    'compteurs': [dict(r) for r in db.execute('SELECT * FROM compteurs ORDER BY annee')],
                    'annonces': db.execute('SELECT COUNT(*) FROM annonces').fetchone()[0]}

    def attribuer(self, mrns, operateur='', existant='', simulation=False):
        refs = references(mrns)
        identite = '|'.join(refs)
        with self.transaction() as db:
            ligne = db.execute('SELECT * FROM annonces WHERE identite=?', (identite,)).fetchone()
            if ligne:
                if existant and numero(existant)[:2] != (ligne['annee'], ligne['sequence']):
                    raise ErreurDM('DM de la source différent du DM enregistré : rapprochement requis')
                return self._resultat(ligne, refs, True)
            if any(db.execute('SELECT 1 FROM transits WHERE mrn=?', (m,)).fetchone() for m in refs):
                raise ErreurDM('Un transit possède déjà un DM dans un autre regroupement : reprendre le lot original')
            if simulation:
                return {'dm': '', 'statut': 'simulation — aucune réservation'}
            bascule = db.execute('SELECT bascule FROM etat').fetchone()[0]
            if bascule is None:
                raise ErreurDM('Numérotation en préparation : dernier DM Sisa à confirmer lors de la bascule')
            an = annee_courante()
            derniere_annee = db.execute('SELECT MAX(annee) FROM compteurs').fetchone()[0]
            if an < max(bascule // 10000, derniere_annee or 0):
                raise ErreurDM('Horloge serveur antérieure à la bascule')
            dernier = db.execute('SELECT dernier FROM compteurs WHERE annee=?', (an,)).fetchone()
            seq = (dernier[0] if dernier else 0) + 1
            pmp = False
            if existant:
                an, seq, pmp = numero(existant)
                if not seq or an > annee_courante():
                    raise ErreurDM('DM source invalide ou futur')
                # Les numéros antérieurs à la bascule appartiennent à Sisa.
                # Un numéro ultérieur inconnu du registre ne peut pas être adopté automatiquement.
                if an * 10000 + seq > bascule:
                    raise ErreurDM('DM source postérieur à la bascule et inconnu du registre : rapprochement requis')
            if seq > 9999:
                raise ErreurDM('Compteur annuel épuisé (9999) : attribution arrêtée')
            try:
                db.execute('INSERT INTO annonces VALUES(?,?,?,?)', (identite, an, seq, int(pmp)))
            except sqlite3.IntegrityError as exc:
                raise ErreurDM('Ce DM appartient déjà à une autre annonce') from exc
            db.executemany('INSERT INTO transits VALUES(?,?)', [(m, identite) for m in refs])
            if not existant:
                db.execute('INSERT INTO compteurs VALUES(?,?) ON CONFLICT(annee) DO UPDATE SET dernier=excluded.dernier', (an, seq))
            self._trace(db, 'reprise_sisa' if existant else 'attribution', operateur,
                        {'mrns': refs, 'numero': f'{an}{seq:04d}', 'pmp': pmp})
            return self._resultat(db.execute('SELECT * FROM annonces WHERE identite=?', (identite,)).fetchone(), refs, False)

    @staticmethod
    def _resultat(ligne, refs, reutilise):
        return {'dm': ('PMP ' if ligne['pmp'] else '') + f"{ligne['annee']}{ligne['sequence']:04d}",
                'mrns': refs, 'reutilise': reutilise}

    def prefixe(self, mrns, pmp, operateur):
        refs = references(mrns)
        if not isinstance(pmp, bool):
            raise ErreurDM('Le préfixe PMP doit être vrai ou faux')
        with self.transaction() as db:
            identite = '|'.join(refs)
            ligne = db.execute('SELECT * FROM annonces WHERE identite=?', (identite,)).fetchone()
            if not ligne:
                raise ErreurDM('Annonce non enregistrée : réserver son DM avant de modifier le préfixe')
            db.execute('UPDATE annonces SET pmp=? WHERE identite=?', (int(pmp), identite))
            self._trace(db, 'prefixe', operateur, {'mrns': refs, 'pmp_avant': bool(ligne['pmp']), 'pmp': pmp})
            return self._resultat(db.execute('SELECT * FROM annonces WHERE identite=?', (identite,)).fetchone(), refs, True)
