# ContestFL — dernière campagne consolidée (terminaison + cascade)

## Périmètre et sécurité

Cette campagne **n'efface pas** les sorties v3, v4 ni les 200 rounds Flower. Elle déploie le contrat corrigé, lance deux sondes de terminaison et de gas puis compare deux politiques de vérification sur les mêmes scénarios, à 25, 100 et 500 clients. **Ne pas lancer en même temps qu'un autre benchmark ContestFL.**

La comparaison « cascade » est une implémentation **indépendante du contrôleur d'audit off-chain**, mais réutilise le substrat blockchain commun (contrat, fenêtres, rôle du resolver). Elle n'est **pas** un protocole blockchain concurrent avec son propre contrat. Le rapport distingue donc explicitement coût de réaudit, coût on-chain et limites de causalité.

## Prérequis

Ubuntu/Linux, Docker Engine + Compose, Make, Python 3.11+ et `.venv` installé comme pour la v4. Le répertoire doit avoir reçu le patch multi-round de la campagne terminée, mais **pas** le patch de terminaison v1 si vous appliquez le correctif combiné « depuis multi-round ». Un fichier `.env` existant est conservé. Les images Docker peuvent être réutilisées.

```
cd ~/Bureau/contestFL-main
source .venv/bin/activate

git apply --check ContestFL_FINAL_assurance_from_multiround.patch
git apply ContestFL_FINAL_assurance_from_multiround.patch

./review/run_final_assurance.sh check
BASE_RUN_ID="final_smoke_$(date -u +%Y%m%dT%H%M%S)" ./review/run_final_assurance.sh smoke
BASE_RUN_ID="final_jisa_$(date -u +%Y%m%dT%H%M%S)" ./review/run_final_assurance.sh run
```

**Si le patch de terminaison v1 est déjà appliqué**, ne pas réappliquer ce patch combiné : utiliser le patch « après terminaison » livré séparément.

## Ce que mesure `run`

1. Compile et déploie le contrat liveness corrigé.
2. Déploie sur la même chaîne la version Solidity historique (fixture SHA-256 vérifié) ; reproduit un chemin nominal et une correction, puis mesure le gas ancien/nouveau, fonction par fonction.
3. Vérifie les deux sorties permissionless `expireSubmission` et `expireReplacement`, le rejet des publications hors délai, le fallback à temps et les contestations concurrentes avec deadline différée.
4. Exécute des comparaisons **appariées** des contrôleurs ContestFL et `independent_level_cascade`, sur les mêmes données et le même contrat corrigé, pour 25 clients (5 répétitions), 100 (10), 500 (5).
5. Ajoute un contrôle **sans faute**, 100 clients et 5 répétitions.
6. Analyse les CSV bruts, refuse les paires incomplètes/erronées et produit `FINAL_AUDIT.md` et `paired_summary.csv`.
7. Enregistre `MANIFEST.json`, les empreintes du code, les reçus de transactions et une archive ZIP autonome de résultats.

Le `smoke` exécute le même processus sur 10 clients, avec une répétition par scénario. Il est indispensable avant `run`.

Les fenêtres de challenge sont fixées à 11 blocs, les réponses à 120 blocs, le budget de reprise à 3, la charge à 4096 valeurs par mise à jour. Les paramètres historiques ne sont pas modifiés.

## Interprétation et décision

- Si les tests de liveness échouent, **ne pas** déclarer la correction validée : conserver les journaux et corriger le code avant de remplacer les résultats du manuscrit.
- Si les chemins nominaux ancien/nouveau présentent un delta de gas, le quantifier. Les anciens résultats restent valides pour leur bytecode historique, pas automatiquement pour le nouveau.
- Si les deux politiques suivent les mêmes transitions EVM, un gas quasi identique est attendu : ce n'est **pas** un résultat négatif pour ContestFL, mais cela **interdit** d'affirmer un avantage on-chain sur une cascade optimisée partageant le même ledger.
- Le réaudit complet des 2N décisions et de l'agrégat doit être comptabilisé séparément, sans convertir du temps CPU en gas.
- Un résultat favorable ne justifie pas une revendication de supériorité face à **tous** les protocoles de cascade ; les garanties d'un protocole blockchain indépendant ne sont pas couvertes par ce contrôleur.
- On ne relance aucune ancienne expérience. Si aucune anomalie de cohérence n'est détectée, remplacer seulement les passages pertinents du manuscrit et les réponses reviewers.

## Récupération des sorties

```
RUN_DIR=$(ls -td review_outputs/*_final_assurance_run | head -1)
echo "$RUN_DIR"
cat "$RUN_DIR/STAGE_STATUS.tsv"
cat "$RUN_DIR/analysis/FINAL_AUDIT.md"
```

Envoie l'archive `review_outputs/<identifiant>_final_assurance_run.zip` pour audit indépendant. Si un stage échoue, le script s'arrête et conserve les sorties précédentes ; il ne faut ni les supprimer ni renommer ce stage en PASS.
