# Processus d'arrivée : préparation de la bascule CargoWise

## Origine et portée

Cette spécification traduit le retour utilisateur reçu le 17 septembre 2026 et
l'exemple privé `DM POSTE.pdf` fourni comme référence documentaire. Elle décrit
le besoin opérationnel et les adaptations à réaliser ; elle ne certifie pas les
échanges douaniers ni leur implémentation dans l'application.

Le retour fixe une échéance opérationnelle au **25 septembre 2026**, avant la
bascule annoncée au plus tard le 26 septembre. Deux conditions sont mentionnées :
disposer du document de contrôle et changer le certificat de communication avec
les douanes. Le certificat douanier est un chantier distinct de la connexion
OAuth au connecteur CargoWise de cette application.

## Circuit cible

| Étape | Responsable proposé | Action et preuve attendue |
|---|---|---|
| Préparation | Déclarant | Rassembler tous les transits du dossier, identifier le lieu agréé et obtenir le numéro DM dans le système métier. Conserver la correspondance DM, dossier et références de transit. |
| 1. Annonce d'arrivée | Déclarant dans CW | Effectuer le premier échange décrit par l'utilisateur et conserver le retour du système douanier, sa référence et son horodatage. La création d'un fichier local ne prouve pas cet échange. |
| Préparation du contrôle | Application puis déclarant | Produire et relire l'annonce et la liste d'inventaire de tous les transits, puis transmettre la version identifiée au lieu agréé concerné. |
| Contrôle physique | Personnel du lieu agréé | Comparer la marchandise reçue aux documents T1, T2 ou T-CH. Renseigner le résultat, les écarts éventuels, la date et la signature. Renvoyer le document au déclarant. |
| 2. Résultat du contrôle | Déclarant dans CW | Sur la base du retour terrain, communiquer le résultat selon le circuit CW applicable. Conserver le retour douanier ; traiter les écarts sans les convertir automatiquement en conformité. |
| Suite du dossier | Déclarant | Poursuivre selon le statut douanier effectivement reçu et les consignes métier. Archiver ensemble sources, version envoyée, retour signé et échanges. |

Les responsables sont des rôles proposés, à affecter dans l'équipe. Les noms de
messages CW, les réponses attendues et les conditions de poursuite doivent être
confirmés avec le responsable métier/CW ; le retour fourni ne les spécifie pas.

## Contenu minimum à garantir

### Annonce d'arrivée

- Identifiant de la société émettrice.
- Numéro complet du lieu agréé, en conservant les lettres et zéros initiaux.
- Numéro d'annonce / DM attendu pour le premier échange.
- Numéro de dossier.
- Immatriculation et nationalité du moyen de transport.
- Numéro et nom du déclarant.
- Toutes les références des documents de transit du dossier.

### Liste d'inventaire

Pour chaque transit, conserver l'expéditeur, le destinataire et la référence du
transit. Pour chaque ligne de marchandise, afficher le type et le nombre de colis,
la désignation, le poids brut et le poids net, avec leurs unités. Le rapprochement
ligne/transit doit rester lisible même lorsque plusieurs transits sont regroupés.

Le support de retour terrain comprend les choix « conforme », « non conforme »,
« avis d'irrégularité établi », la date et la signature. L'application laisse ces
choix vierges. Une conformité documentaire calculée ne vaut pas contrôle physique.

## Enseignements de l'exemple Sisa

Les cinq pages comprennent une annonce regroupant deux transits, puis un couple
inventaire/liste d'articles pour chacun. Le cadre de contrôle est présent sur
chacune des deux listes. Le rendu cible doit permettre de savoir quels transits
sont couverts par chaque résultat de contrôle, y compris en cas d'écart partiel.

La première page distingue le numéro d'annonce avec code-barres, le « No annonce
DA », la référence du dossier et les MRN. Ces identifiants ne sont pas
interchangeables. La correspondance exacte entre DM, annonce DA et LRN dans CW
reste à confirmer sur un dossier CW représentatif. Aucun numéro ne doit être
inventé pour débloquer le circuit.

La couche texte du scan altère certains caractères : l'exemple doit être relu
visuellement avant de constituer une référence de recette. Les valeurs et noms
réels du document restent privés et ne doivent pas entrer dans les tests publics.

## Écarts constatés dans le code au 17 septembre 2026

| Sujet | Existant | Travail nécessaire |
|---|---|---|
| Document de contrôle | Rendus Word/PDF, articles, parties, masses, codes-barres et cadre de contrôle existent. | Vérifier la couverture de tous les champs minimum sur chaque famille de transit et sur un lot multiple. |
| Identifiant société et transport de l'annonce Sisa | `extraire_cw1` ne reprend pas explicitement l'identifiant société, l'immatriculation et la nationalité de cette page. | Extraire et transmettre ces champs au rendu avec leur source. |
| Lieu agréé | `extraire_cw1` recherche une valeur numérique ; le constructeur des dossiers CW ne reporte pas le champ `lieu` dans l'en-tête. | Préserver l'identifiant alphanumérique complet jusqu'au Word/PDF. |
| Référence dossier | La référence Sisa est reprise comme ligne d'en-tête ; le champ dossier dépend d'un libellé distinct. Le rendu peut se rabattre sur le MRN. | Garantir la véritable référence dossier, sans présenter un MRN comme numéro de dossier par défaut. |
| DM | Registre central préparé : compteur annuel unique, conservation aux réimpressions, préfixe PMP manuel. Désactivé avant bascule. | Déployer le service partagé, confirmer le dernier Sisa puis activer. Voir [DM.md](DM.md). |
| Contrôles de complétude | `qualite.evaluer` contrôle notamment MRN, DM, articles et totaux ; une liste de parties non vide suffit au contrôle des parties. | Vérifier séparément expéditeur et destinataire ainsi que les champs d'annonce obligatoires. |
| Critères internes supplémentaires | Le mode PDF strict exige notamment un code marchandise, absent de la liste minimale du retour utilisateur. | Faire arbitrer cette exigence par le métier ; ne pas l'assimiler à une exigence déduite du retour ni la supprimer sans analyse. |
| Statuts | `Prets_a_remettre` qualifie la préparation documentaire ; le Word reste éditable et ne vaut pas validation. | Distinguer dans le suivi dossier : document préparé, premier échange confirmé, envoyé au lieu agréé, retour terrain reçu, second échange confirmé. Conserver les erreurs/rejets. |
| Retour terrain | Cadre vierge dans le document ; pas de preuve de contrôle physique dans la décision de qualité. | Prévoir le rattachement du retour signé à la version envoyée et aux transits concernés. |
| Communication douanière | L'intégration consultée enrichit les données via le connecteur CW. | Faire vérifier les deux échanges et le certificat dans CW ; un test du connecteur seul ne suffit pas. |

Ces écarts constituent un périmètre d'adaptation, pas des fonctionnalités déjà
livrées. Les points d'entrée concernés sont `ulix_ncts/extract.py`,
`pipeline.py`, `render.py`, `word.py`, `qualite.py` et `cw_client.py`.

## Recette avant bascule

### Liaison automatique du PDF à IKAMO

Le parcours utilisateur attendu reste « déposer le PDF ». L'opérateur ne doit
pas avoir à connaître une clé interne NCT. Le traitement cible lit le MRN du
transit, retrouve les déclarations candidates via IKAMO, puis relit la déclaration
retenue et vérifie son MRN exact avant de reprendre son DM et ses références.

La [liaison via la BI](BI-MRN.md) est maintenant intégrée comme autre point
d'entrée : nom de document correspondant au MRN, dossier shipment trouvé en BI,
eDoc confirmé dans IKAMO, puis lecture des NCT liés. Le test réel retrouve le
dossier du PDF fourni, mais son contexte IKAMO ne renvoie aucun lien NCT. Le DM
reste donc non récupéré pour ce cas ; la référence dossier seule ne vaut pas
déclaration d'arrivée.

Vérification du connecteur disponible le 17 septembre 2026 : `get_ncts` lit une
clé de déclaration et `resolve_key` navigue depuis une clé connue ; aucun outil
de recherche par MRN n'est exposé. L'essai de résolution du MRN du PDF testé a
renvoyé « There is no business object matching the criteria ». Cette réponse
n'établit pas l'absence de déclaration dans CW.

Fonction nécessaire côté IKAMO : recherche exacte par MRN dans le périmètre
autorisé, renvoyant les clés NCT candidates et les informations permettant de
distinguer les mouvements (notamment arrivée/départ et statut). La réponse doit
distinguer aucun résultat, plusieurs résultats et erreur technique. En cas de
plusieurs candidats, l'application ne doit pas sélectionner arbitrairement le
premier. Un résultat unique doit encore être recoupé avec `get_ncts` avant fusion.

Le client local sait désormais appeler le contrat proposé
[`cargowise_find_arrival_by_mrn`](CONTRAT-IKAMO-MRN.md), après extraction du MRN,
puis relire et vérifier la déclaration trouvée. La fonction serveur reste à
fournir et à déployer : elle n'est pas exposée par le MCP interrogé directement
avec l'autorisation OAuth le 17 septembre 2026. Si la déclaration
d'arrivée n'existe pas encore, sa création et l'attribution du DM nécessitent un
circuit métier CW distinct : les outils IKAMO actuellement exposés ne proposent
pas de création ni d'envoi de l'annonce aux douanes.

| Cas | Résultat attendu |
|---|---|
| Un transit T1, un T2 et un T-CH représentatifs | Chaque famille produit les champs minimum à partir de sources vérifiables ; toute absence est identifiée pour correction. |
| Plusieurs transits pour une arrivée | Aucun transit perdu ou dupliqué ; parties, colis et poids restent associés au bon transit ; portée du contrôle explicite. |
| DM ou champ d'annonce manquant | Le dossier reste à compléter avant utilisation opérationnelle ; aucun identifiant de substitution n'est présenté comme la donnée attendue. |
| Données illisibles ou pages manquantes | Relecture/correction tracée ; pas d'estimation automatique des marchandises. |
| Contrôle physique conforme | Le retour daté et signé est conservé avant la communication du résultat dans CW. |
| Écart sur un transit | L'écart et le transit concerné restent identifiables ; aucune case de conformité n'est cochée automatiquement. |
| Modification Word | Champs répétés, totaux et références revérifiés ; codes-barres régénérés si leur valeur change ; version finale conservée. |
| Deux échanges dans CW | Réponses attendues vérifiées avec le responsable CW, preuves conservées et cas de rejet traité. |
| Certificat remplacé | Communication douanière vérifiée dans l'environnement prévu avec l'équipe CW ; OAuth du connecteur testé séparément. |

La décision de bascule repose sur la recette signée par le métier et le responsable
CW, avec le document utilisable au lieu agréé et les échanges opérationnels.
La génération réussie d'un Word/PDF ou le passage des tests unitaires de
l'application ne suffit pas à établir ces conditions.
