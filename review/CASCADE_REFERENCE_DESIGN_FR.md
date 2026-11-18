# Comparateur level-cascade indépendant — cahier d'implémentation scientifique

## Pourquoi l'ablation v4 ne suffit pas

`aggregate_reaudit` emprunte les mêmes transitions Solidity que `contestfl`; son coût on-chain identique n'est donc **ni une mesure d'une cascade indépendante ni une preuve que celle-ci n'apporte aucun gain**. Ajouter des contestations artificielles pour rendre la cascade plus chère constituerait une comparaison biaisée.

## Baseline indépendante et reproductible à construire

Le comparateur doit posséder **sa propre machine d'état** (pas `review/causal_chain.py` avec une option cosmétique), et suivre la sémantique suivante :

1. Représenter explicitement les niveaux `ADMIT`, `INCLUDE` et `AGGREGATE`, les clés actives, les versions, les dépendances et les reçus d'artefacts. Une admission peut activer/supprimer une inclusion.
2. Après un verdict accepté, marquer invalide la décision cible ; à chaque niveau descendant affecté, **réauditer toutes les décisions de ce niveau** selon une politique définie avant expérience. Ne rééditer sur la chaîne que les engagements réellement nécessaires : ne pas ajouter de transactions fictives pour pénaliser la baseline.
3. Ne finaliser que si les niveaux ont été validés, si les racines correspondent et si les fenêtres et timeouts applicables sont échus. Garder le même régime de sécurité (mêmes attestations/off-chain evidence et hypothèses de resolver) que ContestFL.
4. Exécuter sur les mêmes mises à jour, seeds, taux de fautes et profondeur Merkle, avec un déploiement isolé par politique. Capturer simultanément coût de vérification CPU, nombre de preuves traitées, EVM gas, transactions et latence de finalisation.
5. Un échec de preuve, une absence de preuve ou un abort est conservé dans le dénominateur de succès ; l'expérience doit vérifier la **parité de l'état final accepté**, pas uniquement que les deux policies disent `success`.

### Deux variantes de comptabilisation à ne pas confondre

- **Cascade optimisée** (référence principale) : une seule publication par lot de niveaux revalidés, sans multiples challenges on-chain inutiles ; l'audit complet descendant reste off-chain. C'est la baseline forte.
- **Cascade niveau-par-niveau** (sensibilité, optionnelle) : un événement on-chain par niveau revalidé. N'en faire une comparaison que si le protocole concurrent nécessite réellement cette granularité ; sinon cela crée un homme de paille.

### Vérification d'équité

Tester un chemin *sans faute*, un changement `reject→admit`, un `admit→reject`, un agrégat fautif et la chaîne causale de trois fautes. Publier à la fois la charge de vérification et le gas ; sinon une baseline plus efficace parce qu'elle fait tout le travail off-chain et une baseline qui l'omet sont indiscernables.

**Critère de rejet du comparateur** : si la baseline réutilise le moteur ContestFL pour gérer les invalidations et les versions, ou si elle exécute des appels on-chain superflus seulement dans sa branche, la comparaison ne peut pas être appelée « indépendante ».

## Comment l'intégrer dans le papier

Une fois le comparateur réellement implémenté et exécuté, ajouter au plus **une ligne** au tableau RQ4 : `Independent level-cascade`, avec gas, temps, taux de corrections correctes et, dans le texte, charge de vérification. Si l'avantage n'est pas au rendez-vous, le rapporter. Ne pas ajouter de figure. **À ce stade, cette baseline n'est pas réalisée ; aucune valeur numérique ne doit lui être attribuée.**
