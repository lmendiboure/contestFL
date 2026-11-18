# ContestFL — v4 étendue JISAS (expériences ciblées)

## Objet

Ce paquet **remplace le lancement v4 précédent**, en reprenant son test de trois corrections dépendantes et en ajoutant les compléments les plus utiles aux reviewers : montée en charge réelle sur Besu, profondeur de preuve Merkle 256, contrôle de la couverture C1 et des expirations, passage Flower → artefacts canoniques → Eager/ContestFL. Il n'exécute **pas** la campagne v3 `focused` déjà obtenue.

**Statut au moment de la livraison :** validations statiques / Python effectuées, mais **aucune nouvelle observation Besu v4 étendue n'a été produite dans l'environnement de développement**. Toute affirmation numérique nouvelle est conditionnée à l'exécution sur ta machine.

## Installation — choisir UNE option

### A. Patch cumulatif recommandé (dépôt actuel v3.2, sans l'ancien patch v4)

Copier `ContestFL_JISAS_v4_extended_from_v3_2.patch` dans `~/Bureau/contestFL-main`, puis :

```bash
cd ~/Bureau/contestFL-main
source .venv/bin/activate
git apply --check ContestFL_JISAS_v4_extended_from_v3_2.patch
git apply ContestFL_JISAS_v4_extended_from_v3_2.patch
```

Si tu as déjà appliqué le patch **v4 simple**, n'applique pas ce patch cumulatif : pars plutôt du dossier ZIP complet dans un **nouveau répertoire** (option B), ou applique uniquement le patch différentiel `ContestFL_JISAS_v4_extended_from_v4.patch` (également fourni).

### B. Archive complète

Décompresser dans un **nouveau répertoire**. Ne pas écraser ton dépôt et ne pas déplacer les `review_outputs` de v3. Remettre un `.env` adapté dans le nouveau dossier. La nouvelle exécution produit ses propres données. Si tu souhaites réutiliser automatiquement le CSV v3 pour l'analyse de mélange de fautes, indiquer explicitement `EXT_V3_RESULTS_DIR` (voir plus bas).

## Exécution simple

```bash
cd ~/Bureau/contestFL-main
source .venv/bin/activate

# Contrôles Python et syntaxe sans Docker
./review/run_v4_extended.sh check

# Besu : campagne courte de validation, sans télécharger Flower
BASE_RUN_ID="extended_smoke_$(date -u +%Y%m%dT%H%M%S)" \
  ./review/run_v4_extended.sh smoke

# Campagne complète sur la machine, une seule commande
BASE_RUN_ID="extended_jisas_$(date -u +%Y%m%dT%H%M%S)" \
  ./review/run_v4_extended.sh run
```

Exécuter **un seul benchmark Besu à la fois**. Les scripts bootstrapent un réseau dédié, déploient les contrats, et le nettoient en sortie. Ils refusent d'écraser un dossier de résultats de même identifiant.

### Campagnes `run` incluses

1. **Chaîne causale v4** (`ADMIT 1→2`, `INCLUDE 2→3`, `AGGREGATE`, puis finalisation correcte), avec trois politiques appariées et mesure réelle du gas et de la finalisation :
   - 25 clients × 16 KiB : 8 répétitions/politique ;
   - 100 clients × 16 KiB : 20 répétitions/politique ;
   - 500 clients × 16 KiB : 6 répétitions/politique ;
   - 100 clients × 1 MiB : 12 répétitions/politique (**100 MiB de données d'updates**).
   - option `EXT_HEAVY_500MB=1` : 500 clients × 1 MiB, 3 répétitions (test intensif mémoire/disque). **Nécessite suffisamment de RAM, SSD et temps**. Ne pas comparer 100×1 MiB et 500×16 KiB comme un effet pur du nombre de clients.
2. **Merkle depth 32 vs 256** : 500 clients, 3 répétitions par profondeur, admission contestée, sur le contrat `RootOnlyContestFL`. Cela mesure l'effet de la longueur du chemin de preuve et **ne prouve pas l'équivalence de toute la récupération**.
3. **Contestations sous charge** : flooding 0/90/360, quotas 0/1, quatre répétitions par configuration. C1 manquée et véritables `expireChallenge` sont comptabilisés séparément. Le **resolver est intentionnellement empêché de répondre** pour tester la transition d'abandon on-chain ; cela **ne mesure pas un taux spontané d'indisponibilité** du resolver.
4. **Flower/MNIST ↔ contrats** : trois seeds, 4 clients, 128 échantillons/client. Chaque run entraîne un vrai round Flower et exporte ses artefacts. **Le même round mesuré** est ensuite rejoué sur Eager et ContestFL en clean et en agrégat erroné. L'analyse fournit le temps séquentiel calcul/artefacts/consensus/finalisation et un **équivalent rounds/h**, sans le confondre avec le débit en régime permanent multi-rounds. L'image Docker Flower peut être longue à installer à la première exécution.
5. **RTT QBFT sensibilité** : expérience sous 100 ms RTT synthétique entre validateurs, avec 100 clients × 16 KiB, quatre répétitions, plus sonde RTT. Cela reste sur un seul hôte ; ce n'est pas un WAN multi-site réel.
6. **Ré-analyse sans nouveau benchmark** : si une campagne v3 complète est disponible, modèle de mélange des taux de fautes à partir de ses observations Eager/ContestFL. Ce sont des **espérances dérivées**, pas des expériences blockchain supplémentaires.

### Options de personnalisation

```bash
# Déploiement avec profil réduit si tu ne disposes pas de NET_ADMIN
auto_id="extended_no_netem_$(date -u +%Y%m%dT%H%M%S)"
EXT_NETEM=0 BASE_RUN_ID="$auto_id" ./review/run_v4_extended.sh run

# Forcer la sensibilité 500 clients × 1 MiB (lourde)
EXT_HEAVY_500MB=1 BASE_RUN_ID="extended_heavy_$(date -u +%Y%m%dT%H%M%S)" \
  ./review/run_v4_extended.sh run

# Source explicite de l'ancienne campagne v3 (facultatif)
EXT_V3_RESULTS_DIR=review_outputs/jisas_20261111T092443_v3_focused \
 BASE_RUN_ID="extended_manual_$(date -u +%Y%m%dT%H%M%S)" ./review/run_v4_extended.sh run
```

Pour éviter de reconstruire l'image tools, le lanceur utilise l'image Docker existante si disponible (`EXT_REBUILD_TOOLS=1` pour forcer la reconstruction). L'image Flower est reconstruite seulement si elle est absente. Pour une reproductibilité de publication stricte, enregistrer également le digest Docker de chaque image utilisée.

## Suivi de l'exécution

Depuis un **deuxième terminal**, sans interrompre le premier :

```bash
cd ~/Bureau/contestFL-main
OUT=$(ls -td review_outputs/*_v4_extended_run | head -n 1)
cat "$OUT/STAGE_STATUS.tsv"
ls -ltr "$OUT/logs" | tail
# Afficher le dernier journal modifié
tail -n 35 "$(ls -t "$OUT"/logs/*.log | head -n 1)"
```

Tout résultat incomplet et l'erreur exacte restent dans le dossier de la campagne. Si le profil échoue, transmettre **le premier log en échec et les fichiers déjà produits** : éviter de relancer la totalité avant de corriger le défaut.

## Sorties

```
review_outputs/<BASE_RUN_ID>_v4_extended_run/
  scale/n25_d4096_r8/causal_chain_{raw,transactions,evidence}.csv
  scale/n100_d4096_r20/...
  scale/n500_d4096_r6/...
  scale/n100_d262144_r12/...
  root_depth/raw/root_only_{rounds,transactions}_depth_d{32,256}_v4.csv
  root_depth/root_depth_sensitivity_summary.csv
  timeouts/late_challenge_{raw,summary}.csv
  flower/seed_*/FLOWER_ARTIFACT_REPORT.json
  flower/seed_*/paired_flower_policies.csv
  netem/network_probe.csv
  analysis/EXTENDED_V4_RESULTS.md
  analysis/extended_table_replacement.tex
  analysis/extended_*.csv
  fault_mix_derived/fault_rate_mixture_derived.csv (si v3 disponible)
  STAGE_STATUS.tsv
  REVIEW_RUN_MANIFEST.json
  logs/*.log
review_outputs/<BASE_RUN_ID>_v4_extended_run.zip
```

**C'est le ZIP final généré sur ta machine qu'il faut renvoyer**, avec l'archive v3 conservée. Un tableau de remplacement unique est produit, sans figure additionnelle automatique.

## Points à ne pas confondre

- Une contestation honnête soumise mais minée trop tard = **C1 coverage miss** ; ce n'est pas un `expireChallenge`. Une contestation admise, puis sans réponse jusqu'à l'expiration = **timeout-induced abort**, à confirmer par le reçu et l'état `ABORTED`.
- `aggregate_reaudit` partage les transitions on-chain de ContestFL ; le résultat ne démontre pas la supériorité sur une cascade générale optimisée. `abort_restart` est une politique expérimentale de redémarrage réellement implémentée sur le même banc.
- Eager est testé sur un contrat distinct qui vérifie avant finalisation : on peut comparer ses coûts observés et sa latence, mais pas prétendre à des garanties de vérification identiques sans démonstration supplémentaire.
- Flower/artefacts mesurés à 4 clients n'extrapolent pas le débit de formation d'un modèle à 500 clients. La montée en charge à 500 est une mesure **EVM + correction**, pas un entraînement Flower à 500.
- La sensibilité Merkle 256 utilise des clés `bytes32` et un arbre de profondeur 256 ; l'équivalence fonctionnelle root-only complète reste à démontrer.
- Ni les tests on-chain, ni les expériences WAN simulées ne suffisent à prouver la sécurité en présence d'un resolver autorisé malveillant ou de preuves indisponibles.
- Le théorème de terminaison à fallbacks par clé et l'obligation de raffinement du DAG dynamique sont des **travaux théoriques séparés**. Ils ne sont pas corrigés automatiquement par cette campagne.
