"""Recherche MRN -> NCT via le MCP SQL BI, en lecture seule.

Le mapping est configuré après inspection des colonnes, jamais déduit d'une
ressemblance entre des valeurs. Les données douanières restent relues via CW.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .cw_client import _MCP, _json_souple


class ErreurBI(RuntimeError):
    pass


@dataclass
class ResultatBI:
    cles: dict[str, str] = field(default_factory=dict)  # NCT -> MRN
    dossiers: dict[str, str] = field(default_factory=dict)  # MRN -> shipment
    messages: list[str] = field(default_factory=list)
    source: str = ''


def _objet(mcp, outil, arguments):
    try:
        donnees = _json_souple(mcp.appeler_outil(outil, arguments))
    except (RuntimeError, OSError, ValueError) as exc:
        # Une URL MCP peut porter un identifiant privé : ne pas journaliser
        # l'exception HTTP brute qui contient cette URL ou ses en-têtes.
        raise ErreurBI(f'appel BI {outil} en échec ({type(exc).__name__})') from exc
    if not isinstance(donnees, dict) or donnees.get('error') or donnees.get('isError'):
        raise ErreurBI(f'réponse BI {outil} invalide ou en erreur')
    return donnees


def _connecter(cfg):
    bi = cfg.get('bi', {})
    if not bi.get('active'):
        raise ErreurBI('MCP BI désactivé')
    if not bi.get('url'):
        raise ErreurBI('URL du MCP BI non configurée')
    try:
        mcp = _MCP(bi['url'], bi.get('token', ''), float(bi.get('timeout_s', 25)))
        mcp.initialiser()
        mcp.lister_outils()
    except (RuntimeError, OSError, ValueError) as exc:
        raise ErreurBI(f'connexion au MCP BI en échec ({type(exc).__name__})') from exc
    etat = _objet(mcp, 'mssql_connection_status', {})
    if etat.get('connected') is not True:
        raise ErreurBI('MCP BI joignable, mais connexion SQL indisponible (connected=false)')
    if bi.get('database') and etat.get('database') != bi['database']:
        raise ErreurBI('la base connectée ne correspond pas à la base BI configurée')
    return mcp, etat


def _identifiant(valeur):
    if not isinstance(valeur, str) or not valeur.strip() or any(ord(c) < 32 for c in valeur):
        raise ErreurBI('identifiant SQL manquant ou invalide')
    return '[' + valeur.replace(']', ']]') + ']'


def _mapping(cfg):
    bi = cfg.get('bi', {})
    noms = (('schema', 'table', 'colonne_document', 'colonne_dossier')
            if bi.get('mode') == 'documents' else ('schema', 'table', 'colonne_mrn', 'colonne_nct'))
    if any(not bi.get(n) for n in noms):
        raise ErreurBI('correspondance BI à configurer : table et colonnes non vérifiées')
    return {n: _identifiant(bi[n]) for n in noms}


def resoudre(cfg, mrns):
    resultat = ResultatBI()
    try:
        valides = list(dict.fromkeys(mrns))
        if not valides or any(not isinstance(m, str) or not re.fullmatch(r'\d{2}[A-Z]{2}[A-Z0-9]{14}', m)
                              for m in valides):
            raise ErreurBI('recherche BI impossible : MRN absent ou invalide')
        mcp, etat = _connecter(cfg)
        champs = _mapping(cfg)
        bi = cfg['bi']
        documents = bi.get('mode') == 'documents'
        base_source = bi.get('source_database') or etat.get('database', '')
        if base_source != etat.get('database') and etat.get('lockDatabase') is True:
            raise ErreurBI('le serveur BI interdit la lecture de la base source configurée')
        description = _objet(mcp, 'mssql_describe_table', {
            'database': base_source, 'schema': bi['schema'], 'table': bi['table']})
        colonnes = description.get('columns')
        if not isinstance(colonnes, list):
            raise ErreurBI('structure de la table BI non vérifiable')
        noms = {c.get('name') for c in colonnes if isinstance(c, dict)}
        attendues = ({bi['colonne_document'], bi['colonne_dossier']} if documents
                     else {bi['colonne_mrn'], bi['colonne_nct']})
        if not attendues <= noms:
            raise ErreurBI('colonnes de correspondance absentes de la table BI configurée')
        resultat.source = f"{base_source}.{bi['schema']}.{bi['table']}"
        table_sql = f"{champs['schema']}.{champs['table']}"
        if base_source != etat.get('database'):
            table_sql = _identifiant(base_source) + '.' + table_sql
        for mrn in valides:
            # L'outil ne propose pas de paramètres SQL liés. Le littéral est
            # exclusivement un MRN validé par fullmatch ASCII ci-dessus.
            sql = ((f"SELECT DISTINCT TOP (2) {champs['colonne_dossier']} AS shipmentKey "
                    f"FROM {table_sql} WHERE {champs['colonne_document']} IN ('{mrn}', '{mrn}.pdf')")
                   if documents else
                   (f"SELECT DISTINCT TOP (2) {champs['colonne_mrn']} AS mrn, "
                   f"{champs['colonne_nct']} AS declarationKey "
                   f"FROM {table_sql} "
                   f"WHERE {champs['colonne_mrn']} = '{mrn}'"))
            donnees = _objet(mcp, 'mssql_run_select_query', {'sql': sql, 'max_rows': 2})
            lignes = donnees.get('rows')
            if (not isinstance(lignes, list) or donnees.get('truncated')
                    or donnees.get('hasMore') or donnees.get('tronque')):
                raise ErreurBI('résultat BI incomplet ou invalide')
            if not lignes:
                resultat.messages.append(f'{mrn} : absent de la source BI consultée ; présence dans CW non déterminée')
                continue
            if len(lignes) != 1:
                resultat.messages.append(f'{mrn} : plusieurs correspondances BI, aucune clé sélectionnée')
                continue
            ligne = lignes[0]
            if not isinstance(ligne, dict):
                raise ErreurBI('ligne BI invalide')
            if documents:
                dossier = ligne.get('shipmentKey', '')
                if not isinstance(dossier, str) or not re.fullmatch(r'S[A-Z0-9]{6,30}', dossier):
                    resultat.messages.append(f'{mrn} : référence dossier BI invalide')
                    continue
                resultat.dossiers[mrn] = dossier
                resultat.messages.append(f'{mrn} : dossier {dossier} retrouvé par document BI, à confirmer dans CargoWise')
                continue
            cle = ligne.get('declarationKey', '')
            if (ligne.get('mrn') != mrn or not isinstance(cle, str)
                    or not re.fullmatch(r'NCT\d{6,10}', cle)):
                resultat.messages.append(f'{mrn} : correspondance BI invalide (MRN exact ou clé NCT manquant)')
                continue
            if cle in resultat.cles and resultat.cles[cle] != mrn:
                raise ErreurBI('une clé NCT est associée à plusieurs MRN dans la BI')
            resultat.cles[cle] = mrn
            resultat.messages.append(f'{mrn} : clé {cle} retrouvée dans la BI, à confirmer dans CargoWise')
    except ErreurBI as exc:
        resultat.cles.clear()
        resultat.dossiers.clear()
        resultat.messages.append(str(exc))
    return resultat


def diagnostiquer(cfg):
    """Ne lit aucune donnée métier ; inspecte les noms de colonnes pertinents."""
    mcp, etat = _connecter(cfg)
    sql = ("SELECT TOP (100) s.name AS schema_name, o.name AS object_name, c.name AS column_name "
           "FROM sys.columns c JOIN sys.objects o ON c.object_id=o.object_id "
           "JOIN sys.schemas s ON o.schema_id=s.schema_id "
           "WHERE o.type IN ('U','V') AND (c.name LIKE '%MRN%' OR c.name LIKE '%NCT%' "
           "OR c.name LIKE '%declar%' OR c.name LIKE '%transit%') "
           "ORDER BY s.name, o.name, c.name")
    resultat = {'database': etat.get('database'), 'connected': True,
                'colonnes_candidates': _objet(mcp, 'mssql_run_select_query', {'sql': sql, 'max_rows': 100})}
    bi = cfg['bi']
    if bi.get('table'):
        resultat['source_configuree'] = _objet(mcp, 'mssql_describe_table', {
            'database': bi.get('source_database') or etat.get('database'),
            'schema': bi.get('schema', 'dbo'), 'table': bi['table']})
    return resultat
