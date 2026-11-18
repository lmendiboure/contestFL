# Conclusion scientifique préalable : preuve, cascade et résultats

## Terminaison

L'audit source a démontré que l'ancien Solidity pouvait rester bloqué en `SUBMIT` et en `RESOLVING` si les acteurs privilégiés étaient silencieux. Le correctif ajoute des délais et des aborts publics. Les contrôles Python sont terminés ; la validation EVM et la mesure du gas **restent à effectuer sur la machine Besu**. Ce correctif vise une **terminaison terminale** (`FINALIZED` ou `ABORTED`) sous disponibilité de la blockchain et inclusion à temps d'au moins une action honnête. Cela n'établit ni succès assuré, ni borne en temps physique sous réseau asynchrone, ni vérification sémantique des certificats.

## Cascade indépendante — ce que nous savons *déjà*

La campagne v4 avait montré `aggregate_reaudit` ≃ ContestFL en gas, parce que cette ablation suivait exactement les mêmes transitions Solidity. **Elle ne démontre pas une supériorité ou une équivalence à une cascade réellement indépendante.**

La nouvelle implémentation `LevelCascadeAuditor` réévalue toute la couche ADMIT, toute la couche INCLUDE et l'agrégat à partir des mises à jour et engagements, à chaque état publié. La vérification est distincte de la machine `causal_chain.py`. Les preuves d'évidence utilisent les mêmes adaptateurs, et le contrôleur passe par le même ledger et la même sémantique de challenge, ce qui isole le coût de vérification supplémentaire.

**Conclusion prévisible, à confirmer par les mesures :** sur une chaîne d'événements qui impose les mêmes décisions révisées, un réaudit de tous les niveaux ne devrait pas à lui seul modifier le nombre de transactions ni le gas on-chain. Son coût supplémentaire est principalement off-chain et croît avec le nombre de décisions recontrôlées. Le différentiel n'est pas nécessairement important en latence, car la fenêtre de challenge domine. Ce n'est pas une prédiction d'une domination générale : une cascade pouvant empêcher de publier certaines erreurs suit un autre chemin et devra être comparée comme politique proactive, à assurance équivalente.

## Décision pour l'article

Ne pas soutenir « ContestFL est moins cher qu'une cascade indépendante » tant qu'un comparateur **end-to-end indépendant** n'est pas implémenté et mesuré. Il est en revanche raisonnable de présenter : (a) l'économie de gas relative au redémarrage complet, qui est mesurée ; (b) le fait que le traitement des dépendances préserve la correction et réduit le périmètre de réaudit *dans notre modèle et notre contrôleur* ; (c) les coûts d'une cascade exhaustive sur le même ledger, si les mesures confirment l'écart de CPU.

Cela préserve la contribution principale sans affaiblir gratuitement le manuscrit. Ce que les données ne permettent pas de prouver, c'est une supériorité universelle sur des cascades optimisées.
