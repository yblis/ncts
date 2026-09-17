# Recherche du MRN dans le MCP BI

Le client BI est intégré au traitement. Lorsque `bi.active` et
`cargowise.active` sont vrais et qu'aucune clé NCT n'est fournie, Hermes :

1. Extrait les MRN des PDF, y compris depuis les relectures liées au contenu.
2. Vérifie la connexion SQL et le schéma configuré via le MCP BI.
3. Recherche chaque MRN dans la source configurée, en lecture seule : soit
   directement dans une colonne MRN, soit via un nom de document exactement
   égal au MRN avec ou sans extension `.pdf`.
4. En mode documents, retrouve le dossier shipment, confirme la présence du
   document dans les eDocs IKAMO et lit les déclarations NCT liées. La référence
   dossier est conservée même si aucun lien NCT n'est renvoyé. Cette association
   documentaire ne valide pas à elle seule le MRN ou le DM.
5. Refuse les résultats ambigus ou incomplets. Relit la déclaration dans IKAMO
   et vérifie son MRN exact et son mouvement
   d'arrivée (`A`) avant de reprendre le DM/LRN. La table BI utilisée est tracée
   dans les preuves internes.

La recherche BI se limite aux correspondances document/dossier/NCT. Elle ne remplace pas la
lecture de l'état douanier dans CW et ne crée ni ne transmet d'annonce.
Une absence dans la BI ne prouve pas une absence dans CW : les données BI
peuvent être décalées ou ne pas couvrir toutes les déclarations.

## Configuration privée

L'URL fournie est enregistrée dans `config.json` local, ignoré par Git. Elle
n'est pas incluse dans la configuration publique ni affichée au démarrage.
Un jeton éventuel peut être fourni via `ULIX_BI_MCP_TOKEN`.

La section `bi` de `config.example.json` donne les champs nécessaires : `url`,
`active`, `database`, `schema`, `table`. Deux modes sont disponibles :

- `mode: "direct"` : `colonne_mrn` et `colonne_nct` pour un mapping explicite.
- `mode: "documents"` : `colonne_document` et `colonne_dossier` pour les eDocs.

`database` vérifie la base connectée ; il ne change pas la base et ne contourne
pas les restrictions du serveur. `source_database` permet une base source
différente uniquement si le serveur autorise cette lecture. Ne renseigner le mapping qu'après inspection
des colonnes et confirmation de leur sens métier. Les clés de dossiers shipment
`S…` ne sont pas des clés NCT.

Diagnostic sans génération ni archivage :

```sh
.venv/bin/python3 lancer.py --statut-bi
```

Sous Windows : `.venv\Scripts\python.exe lancer.py --statut-bi`.
Le diagnostic vérifie SQL puis liste au maximum 100 colonnes candidates dans
les tables/vues de la base courante ; cette liste n'est pas un mapping validé.
Une erreur renvoie le code de sortie 8. Les rapports de traitement distinguent
connexion SQL indisponible, mapping non renseigné, absence de résultat,
ambiguïté et incohérence avec la relecture IKAMO.

## Vérification sur le poste

Le 17 septembre 2026, après une indisponibilité SQL temporaire, la connexion et
les lectures réelles ont réussi. Le mapping eDoc a été inspecté et configuré
localement. Le dossier du PDF test a été retrouvé automatiquement en BI puis
confirmé dans IKAMO par le nom du document. Le contexte IKAMO de ce dossier ne
renvoie aucun lien NCT ; le DM n'a donc pas été récupéré. Cela ne prouve pas
qu'aucune déclaration autonome n'existe dans CW.

Les tests hors ligne couvrent les deux modes, les erreurs, l'ambiguïté, la
confirmation par eDoc et la vérification du mouvement d'arrivée. Aucun
identifiant de production n'entre dans les tests. Redémarrer la surveillance
pour charger la configuration et le nouveau client BI.
