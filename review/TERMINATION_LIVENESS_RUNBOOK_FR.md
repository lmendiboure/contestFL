# ContestFL — correction de terminaison Solidity, validation Besu indépendante

## Statut et périmètre

Cette extension traite deux contre-exemples de *liveness* du prototype `ContestFLExperiment` : un coordinateur silencieux en `SUBMIT` et une absence de publication/fallback en `RESOLVING` après une révision acceptée. Elle ne modifie pas le modèle abstrait de DAG général, et ne prouve pas la validité sémantique du resolver. Le nouveau contrat est **une variante du prototype**, à distinguer de la version utilisée dans les campagnes v3/v4.

Ne pas appliquer le patch sur le dépôt pendant la campagne **multi-round**. En particulier, ne pas lancer deux campagnes Besu utilisant le même Docker Compose et les mêmes réseaux.

## Fonctionnement

- `openRound(...)` **conserve l'ancienne signature** avec un délai SUBMIT par défaut de `max(2n+32, challengeBlocks)` blocs et un délai RESOLVING égal à `responseBlocks` ; l'ancienne ABI `getRoundStatus(...)` est conservée. Le getter public automatique `rounds(...)`, lui, change avec les champs ajoutés.
- `openRoundWithTimeouts(...)` permet de fournir explicitement `submissionBlocks` et `replacementBlocks` pour de nouvelles expériences.
- `submit`, `publishDecisions` et `publishInitialState` refusent d'agir après `submissionDeadline`.
- `expireSubmission(roundId)` est appelable par **tout** compte après cette deadline, et clôt le round en `ABORTED`.
- Après le **dernier challenge encore ouvert** d'un round où une révision a été acceptée, le contrat ouvre `replacementDeadline`. Les autres challenges encore ouverts conservent leur `responseDeadline` : ils peuvent provoquer un abort par `expireChallenge`.
- `publishCoordinatorReplacement` et `publishResolverFallback` refusent les publications tardives ; `expireReplacement(roundId)` permet à tout compte de clôturer un round en `ABORTED` quand les deux acteurs ne publient rien.
- `finalize()` reste public sur `CHALLENGE` après sa fenêtre, ou en `READY` ; les états terminaux sont définitifs.

Ce mécanisme garantit un **chemin de sortie fail-closed sous les hypothèses** : blockchain continuant à produire des blocs et transactions d'un acteur honnête finalement incluses dans un temps borné ; observabilité des challenges ouverts et appel des transitions `expire...` ou `finalize` ; cardinalité et budgets bornés. Le résultat est `FINALIZED` **ou** `ABORTED`, pas nécessairement la réussite du round.

## Installation sur le dépôt existant

Patch à appliquer après la fin du multi-round, depuis `~/Bureau/contestFL-main` :

```bash
source .venv/bin/activate
# Placer le patch téléchargé dans la racine

git apply --check ContestFL_JISA_termination_liveness_v1.patch
git apply ContestFL_JISA_termination_liveness_v1.patch

./review/run_termination_liveness.sh check
```

## Essais dynamiques (réseau Besu isolé)

**Attention :** le script prépare un réseau neuf, appelle `make down` à sa sortie, compile/déploie le nouveau contrat, puis déploie aussi une copie **exacte** du contrat v4 précédent pour une comparaison gas appariée. Ne pas l'exécuter pendant le multi-round ou une autre campagne.

```bash
BASE_RUN_ID="term_$(date -u +%Y%m%dT%H%M%S)" \
  ./review/run_termination_liveness.sh smoke
```

Résultats : `review_outputs/<BASE_RUN_ID>_termination_liveness/` et son ZIP. Le fichier `liveness_probe.json` contient :

1. `silent_coordinator_submit` : abort public après deadline, tentative de publication tardive refusée.
2. `silent_coordinator_and_resolver_replacement` : abort public après révision résolue sans remplacement, fallback tardif refusé.
3. `on_time_resolver_fallback` : publication terminale à temps, finalisation correcte.
4. `pending_challenge_then_replacement` : aucune fenêtre de remplacement prématurée ; démarrage une fois le dernier challenge résolu.
5. `pending_challenge_times_out` : réponse manquante à une contestation encore ouverte, abort public via le timeout existant.
6. Comparaisons de gas **sur le même réseau et les mêmes séquences de transactions** pour `nominal` et `one_admission_correction` (ancienne version v4 vs contrat corrigé).

La vérification locale ne compile pas Solidity dans cet environnement ; **seule une exécution Besu complète** permettra d'établir que ces scénarios passent sur l'EVM et de mesurer leur surcoût.

## Interprétation des coûts

- Les mesures historiques v3/v4 restent valides **pour l'ancien bytecode**.
- L'ajout de variables d'état, de nouvelles émissions et de conditions de phase peut augmenter le gas normal, même sans timeout exécuté.
- `delta_gas` et `delta_pct` sont des mesures de non-régression appariées sur deux chemins, **pas** une réexécution exhaustive des matrices 25/100/500 clients.
- Si les surcoûts sont non négligeables, mettre à jour les chiffres concernés ou indiquer explicitement la version du contrat associée à chaque série.

## Points qui subsistent hors de cette correction

- Aucune vérification on-chain du contenu des certificats ; le resolver de confiance peut toujours accepter des racines incorrectes.
- Pas de preuve automatique de raffinement de la machine Solidity au modèle général à clés dynamiques.
- Pas de garantie de temps réel sans hypothèses de progression/inclusion du réseau.
- Les timeouts apportent une progression vers un **état terminal**, pas un succès garanti ; un acteur malveillant peut forcer une perte de disponibilité menant à `ABORTED`.
