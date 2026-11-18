# ContestFL v4 — ciblage « correction causale successive » (JISAS)

## Objectif et statut

Ce patch **complète** les données v3 déjà mesurées. Il n'en modifie aucun CSV et ne relance pas le profil `focused`. Il cible la lacune identifiée dans la comparaison à faute unique : plusieurs révisions successives liées à la publication de nouvelles versions.

Les nouveaux tests ont été validés **hors chaîne** (tests de planification et de statistiques). Le banc Besu n'était pas exécutable dans l'environnement de préparation : les mesures sont à effectuer sur la machine de l'auteur.

## Application

Depuis `~/Bureau/contestFL-main`, où les correctifs v3.1 et v3.2 ont déjà été appliqués :

```bash
source .venv/bin/activate
git apply --check ContestFL_JISAS_causal_v4.patch
git apply ContestFL_JISAS_causal_v4.patch

# Tests rapides, sans Docker
./review/run_causal_v4.sh check

# Mini-campagne Besu, 10 clients et une répétition par politique
BASE_RUN_ID="causal_smoke_$(date -u +%Y%m%dT%H%M%S)" \
  ./review/run_causal_v4.sh smoke

# Campagne mesurée : 100 clients, 20 répétitions appariées, 1 warm-up
BASE_RUN_ID="causal_jisas_$(date -u +%Y%m%dT%H%M%S)" \
  ./review/run_causal_v4.sh run
```

**Ne pas relancer simultanément** un autre benchmark Besu (les scripts redéploient et nettoient leur réseau dédié). Les résultats préexistants dans `review_outputs` sont conservés. Le script refuse d'écraser un répertoire de résultats existant.

Si un nouveau terminal est ouvert, réactiver `.venv`. Pour suivre l'étape en cours, ouvrir un deuxième terminal :

```bash
cd ~/Bureau/contestFL-main
DIR=$(ls -td review_outputs/*_v4_causal_run | head -n 1)
tail -f "$DIR/logs/causal_chain_onchain.log"
```

Si le processus échoue, lire la **première exception** dans `causal_chain_onchain.log` et transmettre le CSV partiel ; ne pas effacer les données.

## Ce qui est réellement exercé

Une suite volontairement adversariale, sur un même tableau de 100 mises à jour `int32` de 1 MiB chacune, avec la fenêtre v3 de 11 blocs comme **paramètre mesuré/modélisé**, et 3 jetons de reprise :

1. Le client 0 est rejeté (`1`). Son admission est rectifiée vers **admis, exclu** (`2`). Le contrat incrémente `decisionVersion` et le nouveau root inclut le client dans l'ensemble admis.
2. Dans la nouvelle epoch, une preuve Merkle révèle l'**omission d'inclusion** : état `2 → 3`. Le root d'entrée d'agrégat est modifié.
3. Une publication ultérieure porte un **checkpoint d'agrégat erroné**, prouvé par replay des mises à jour. Le resolver révise la contestation et le coordinateur publie le checkpoint correct.
4. La fenêtre complète expire ; le contrat finalise le checkpoint attendu. Les versions/epochs, états, challenges ouverts, reçus et gas sont contrôlés.

Un deuxième test vérifie `3 → 1` (*admit-to-reject*) et la finalisation de l'état correspondant, avec **un seul essai**.

## Politiques comparées

- `contestfl` : trois corrections et trois republications au sein du **même round logique**. Il ne s'agit pas d'une réparation d'un DAG générique.
- `abort_restart` : chaque faute détectée déclenche un abort ; les soumissions sont retransmises pour la tentative suivante. Le modèle suppose explicitement qu'une nouvelle faute survient à chaque candidate suivante, jusqu'à la quatrième candidate correcte.
- `aggregate_reaudit` : même chemin on-chain que `contestfl`, avec un **réaudit d'agrégat hors chaîne** après chaque correction applicable. C'est une **ablation**, pas la réimplémentation d'un algorithme général de cascade. Il serait abusif de conclure à une supériorité universelle de ContestFL sur un level-cascade optimisé.

L'ordre des politiques est randomisé par répétition. Les seeds et données sont identiques pour chaque trio. Les échecs sont conservés et comptés. Les différences de gas/latence sont calculées sur les paires correctement finalisées uniquement ; les effectifs de succès sont toujours visibles.

**Eager** n'est pas testé ici : une vérification en amont peut empêcher l'apparition des mauvaises republications ultérieures. Lui injecter artificiellement la même chaîne constituerait une comparaison non équitable. Les résultats Eager du profil v3 restent présentés **séparément**.

## Résultats produits

```
review_outputs/<BASE_RUN_ID>_v4_causal_run/
  STAGE_STATUS.tsv
  logs/*.log
  causal_chain/causal_chain_raw.csv
  causal_chain/causal_chain_transactions.csv
  causal_chain/causal_chain_evidence.csv
  causal_chain/causal_chain_metadata.json
  conformance/admit_to_reject.json
  analysis/causal_policy_summary.csv
  analysis/causal_paired_effects.csv
  analysis/CAUSAL_CHAIN_REPORT.md
  REVIEW_RUN_MANIFEST.json
review_outputs/<BASE_RUN_ID>_v4_causal_run.zip
```

Les mesures brutes (y compris hash/status/gas des transactions et engagements des adaptateurs), statistiques, logs, empreintes source, versions et contrôles sont archivés automatiquement. Envoyer **l'archive ZIP générée**, de préférence intacte. Aucun nouveau graphique n'est créé : une ligne dans le tableau existant, et éventuellement quelques phrases dans la section résultats, suffiront si les données sont concluantes.

## Personnalisation

```bash
# 30 répétitions plutôt que 20, au besoin
REVIEW_CHAIN_REPS=30 BASE_RUN_ID=causal_30r ./review/run_causal_v4.sh run

# Sensibilité exploratoire sur une fenêtre plus longue
REVIEW_CHAIN_WINDOW_BLOCKS=20 BASE_RUN_ID=causal_w20 ./review/run_causal_v4.sh run
```

Une fenêtre de 11 blocs est le **paramètre de la campagne v3 locale** ; elle n'est ni une preuve de couverture C1 sous tous les débits/RTT, ni une garantie multi-site.

## Ce que ce patch ne démontre pas

Il ne valide pas un moteur de DAG dynamique arbitraire dans Solidity, ne garantit pas la correction sémantique des certificats signés par un resolver malveillant, ne valide pas une résilience Sybil, ne mesure pas le throughput d'entraînement Flower sous ContestFL vs Eager, ne démontre pas la disponibilité des témoins Merkle, et ne répare pas la borne de terminaison avec fallback par clé. Ces points doivent être abordés séparément ou faire l'objet de restrictions précises dans les revendications scientifiques.
