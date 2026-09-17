"""Contrat du MCP CargoWise : params imbriqués et index MRN."""
import copy
import json
import unittest
from unittest.mock import patch
from ulix_ncts import cw_client as cw, config

MRN='26CH07STTEST000002'


class NouveauMCP(unittest.TestCase):
    def setUp(self):
        self.cfg=copy.deepcopy(config.DEFAULTS)
        self.cfg['cargowise']['active']=True
        self.client=cw._MCP('https://example.invalid/mcp')
        for nom, champs in [('cargowise_get_ncts',['key']), ('cargowise_get_shipment_context',['key']), ('cargowise_find_by_mrn',['mrn','refresh','include_summary'])]:
            self.client._schemas[nom]={'properties':{'params':{'$ref':'#/$defs/Entree'}}, '$defs':{'Entree':{'properties':{k:{} for k in champs}}}}
        self.recherche={'found':True,'mrn':MRN,'matches':[{'key':'NCT00000001','mrn':MRN,'movement_type':'A'}]}
        self.entete={'found':True,'mrn':MRN,'lrn':'20260001','movement_type':{'code':'A'},'customs_status':{'code':'CL1'},'arrival_date':None}
        self.appels=[]

    def rpc(self, methode, params):
        self.assertEqual(methode,'tools/call')
        self.appels.append(params)
        self.assertIn('params',params['arguments'])
        return {'content':[{'type':'text','text':json.dumps(self.recherche if params['name']=='cargowise_find_by_mrn' else self.entete)}]}

    def executer(self):
        with patch.object(cw,'connecter',return_value=(self.client,cw.ResultatCW(outils=list(self.client._schemas)))),patch.object(self.client,'appeler',side_effect=self.rpc):
            return cw.interroger(self.cfg,[],mrns=[MRN])

    def test_recherche_native_et_statuts(self):
        self.cfg['bi']['active']=True
        with patch('ulix_ncts.bi_client.resoudre') as bi:
            res=self.executer()
            bi.assert_not_called()
        self.assertTrue(res.ok)
        self.assertEqual(res.entete['NCT00000001']['type_mouvement'],'A')
        self.assertEqual(res.entete['NCT00000001']['statut_douane'],'CL1')
        self.assertNotIn('arrivee',res.entete['NCT00000001'])
        self.assertFalse(self.appels[0]['arguments']['params']['refresh'])
        self.assertEqual(self.appels[1]['arguments'],{'params':{'key':'NCT00000001'}})

    def test_alias_ancien_client_vers_params(self):
        with patch.object(self.client,'appeler',side_effect=self.rpc):
            self.client.appeler_outil('cargowise_get_shipment_context',{'shipmentNumber':'S00000001'})
            self.client.appeler_outil('cargowise_get_ncts',{'declarationKey':'NCT00000001'})
        self.assertEqual(self.appels[0]['arguments'],{'params':{'key':'S00000001'}})
        self.assertEqual(self.client.parametre('cargowise_get_ncts',['declarationKey','key']),'key')

    def test_ambiguite_refusee(self):
        self.recherche['matches']*=2
        self.assertFalse(self.executer().ok)
        self.assertEqual(len(self.appels),1)

    def test_mrn_relecture_different_refuse(self):
        self.entete['mrn']='26CH07STTEST000003'
        self.assertFalse(self.executer().ok)

    def test_erreur_entete_refusee(self):
        self.entete['error']=True
        self.assertFalse(self.executer().ok)

    def test_absence_index_explicite(self):
        self.recherche.update(found=False,matches=[])
        res=self.executer()
        self.assertFalse(res.ok)
        self.assertTrue(any('ne prouve pas' in m for m in res.avertissements))

    def test_depart_seul_ne_devient_pas_arrivee(self):
        self.recherche['matches'][0]['movement_type']='D'
        self.assertFalse(self.executer().ok)

    def test_repli_bi_pour_absence(self):
        from ulix_ncts.bi_client import ResultatBI
        self.cfg['bi']['active']=True
        self.recherche.update(found=False,matches=[])
        with patch('ulix_ncts.bi_client.resoudre',return_value=ResultatBI()) as bi:
            self.assertFalse(self.executer().ok)
            bi.assert_called_once()
            self.assertEqual(bi.call_args.args[1], [MRN])
