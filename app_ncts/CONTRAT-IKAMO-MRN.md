# Recherche d'arrivée par MRN : contrat proposé pour IKAMO

Statut : client Hermes implémenté, fonction serveur à ajouter et déployer.
Ce nom d'outil est un nouveau contrat proposé, pas un outil déjà disponible.
Une alternative est désormais intégrée : la [recherche via le MCP BI](BI-MRN.md),
qui ne requiert pas cette nouvelle fonction IKAMO si la source BI fournit la clé NCT.

Hermes lit le PDF avant l'interrogation. Sans clé NCT explicite, il découvre
`cargowise_find_arrival_by_mrn` dans `tools/list` et appelle cet outil avec :

```json
{"mrn": "26CH07STTEST000002"}
```

L'outil effectue une recherche exacte, en lecture seule, des déclarations
d'arrivée dans le périmètre société autorisé par la connexion. Il renvoie :

```json
{
  "mrn": "26CH07STTEST000002",
  "complete": true,
  "matches": [
    {
      "declarationKey": "NCT00000001",
      "mrn": "26CH07STTEST000002",
      "movement_type": "A"
    }
  ]
}
```

`complete: true` signifie que tous les résultats ont été examinés. Un index
partiel, périmé ou une page de résultats tronquée ne doit pas annoncer une
recherche complète. Une absence vérifiée donne `matches: []` ; une erreur
technique donne une erreur MCP (`isError: true`), jamais une liste vide.

Hermes exige exactement un candidat. Il relit sa clé avec `cargowise_get_ncts`
et contrôle à nouveau MRN et `movement_type: A` avant de reprendre le DM/LRN.
Plusieurs candidats demandent un rapprochement métier, sans choix automatique.
Les références de test ci-dessus sont fictives.

## Source serveur nécessaire

Les lectures XSR de l'eAdaptor du serveur local demandent une clé de job.
Le nouveau service doit donc s'appuyer sur une source de recherche réellement
disponible : vue de données autorisée, API de recherche ou index alimenté par les
exports CW avec garantie de couverture et de fraîcheur. Le schéma et l'accès à
cette source restent à établir dans le serveur déployé. Aucun balayage de clés
NCT ni création de déclaration pour découvrir une clé n'est prévu.

## Recette

Tester : correspondance unique relue avec DM ; résultat vide ; plusieurs
arrivées ; départ seulement ; réponse incomplète ; erreur réseau ; MRN différent
à la relecture ; absence d'outil. Conserver sources et diagnostic sans fusion en
cas d'échec. La création d'une arrivée ou son envoi douanier ne fait pas partie
de cette fonction de lecture.
