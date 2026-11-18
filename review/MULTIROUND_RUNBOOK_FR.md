# ContestFL — lancement de l'expérience Flower multi-round

La campagne est **indépendante** des résultats v3/v4. Le dépôt actuel doit disposer des scripts v4 (Besu 4 validateurs, `make deploy`, Dockerfile.flower) ; on applique le patch fourni sur le dépôt v4 étendu corrigé. Cette campagne ne mesure pas un pipeline FL en concurrence : elle mesure 20 rounds **consécutifs**, chacun dépendant du modèle effectivement finalisé sur la chaîne au round précédent.

## Principe expérimental

- Politiques : ContestFL et eager_full, chacune sur son réseau Besu réinitialisé.
- 5 graines de trajectoire × 20 rounds, 2 clients MNIST, 128 exemples par client et par round, 1 époque locale.
- Identiques : partitions, génération des graines par round, architecture, paramètres et positions des fautes (agrégat invalide aux rounds 6, 13, 19).
- Une trajectoire **s'arrête** au premier round non finalisé correctement : pas de décalage des graines ni de saut d'échec.
- Après chaque entraînement : artefacts canoniques à virgule fixe, validation de replay, publication, règlement, lecture de l'état final sur chaîne. Seulement si le checkpoint est accepté : construction/adoption du prochain modèle.
- Métrique : nombre de rounds correctement finalisés par heure de temps mesuré en séquence, intervalles de variation par **graines**, gas, nombre de transactions. Ce n'est pas un benchmark de pipelines multi-sites.

## Lancement

Depuis la racine du dépôt :

```bash
cd ~/Bureau/contestFL-main
source .venv/bin/activate
./review/run_flower_multiround.sh check
BASE_RUN_ID="mr_smoke_$(date -u +%Y%m%dT%H%M%S)" ./review/run_flower_multiround.sh smoke
BASE_RUN_ID="mr_jisa_$(date -u +%Y%m%dT%H%M%S)" ./review/run_flower_multiround.sh run
```

Ne lancer `run` qu'après la réussite du `smoke`, qui exécute 2 rounds (dont un fautif) pour les deux politiques et vérifie la transmission des poids. Un téléchargement initial de MNIST peut être nécessaire. Une image `contestfl-flower-mnist:local` construite lors de v4 peut être réutilisée : le code source est monté dans `/workspace`.

L'exécution écrit dans `review_outputs/<BASE_RUN_ID>_flower_multiround_run/` :

- `trajectories/s<seed>_<policy>/round_<num>/FLOWER_ARTIFACT_REPORT.json` — artefacts et entrée modèle.
- `CANDIDATE_NEXT_MODEL.npz` (avant ledger) et `FINALIZED_MODEL.npz` (uniquement après vérification du ledger).
- `rounds.csv`, `SUMMARY.json` pour chaque trajectoire ; `MULTIROUND_PAIRED.csv` et `MULTIROUND_ANALYSIS.json` à l'échelle de la campagne.
- `STAGE_STATUS.tsv` et journaux ; archive ZIP avec SHA-256.

**Ne pas réutiliser un BASE_RUN_ID** : le lanceur refuse d'écraser une campagne. En cas d'échec, conserver le dossier et envoyer le journal + `STAGE_STATUS.tsv`. Les mesures précédentes restent intactes.

## Interprétation et limites

- La mesure comprend l'entraînement réel, l'export et le protocole blockchain en série ; elle *n'est pas* du temps GPU, un débit FL pipeliné, un débit sur réseau WAN ni une étude d'accuracy statistique.
- Même partition locale à chaque round, uniquement 2 clients : évaluation fonctionnelle du chemin de succession des modèles, pas généralisation à des milliers de clients.
- Les comparaisons entre policies sont appariées par graine (5 unités indépendantes), pas par les 20 rounds corrélés.
- Aucune valeur de performance n'est revendiquée avant exécution effective sur Docker/Besu.
