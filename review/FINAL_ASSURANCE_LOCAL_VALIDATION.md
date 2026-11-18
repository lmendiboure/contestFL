# Vérification locale de la campagne consolidée

- Dépôt de référence : v4 étendue + correctifs causal/Flower/Netem + multi-round terminé.
- Patch liveness v1 : intégré dans le patch consolidé.
- Comparateur : contrôleur de cascade **indépendant off-chain**, même ledger Solidity.
- Tests de projet : **124 tests, 114 réussis, 10 ignorés** (dépendances blockchain facultatives indisponibles localement), zéro échec.
- Contrôle `run_final_assurance.sh check` : réussi sur deux copies propres, avec et sans patch liveness v1 déjà appliqué.
- Les tests locaux valident les modèles et scripts, **pas** le comportement EVM.
- Les tests Besu/Docker et les mesures de gas doivent être exécutés sur Ubuntu.
- Aucune mesure de cascade indépendante sur Besu n'est fournie ici ; aucune supériorité n'est revendiquée à l'avance.
- La campagne `run` ne rejoue pas les données v3, v4 ou les 200 rounds Flower.
