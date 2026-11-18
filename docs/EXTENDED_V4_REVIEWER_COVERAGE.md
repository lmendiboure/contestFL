# JISAS-D-26-07235 — réponse expérimentale avec v3 + v4 étendue

**Attention :** le code v4 étendu est préparé et testé hors chaîne, mais les mesures nouvelles sont à exécuter. Aucun résultat non obtenu n'est revendiqué.

| Commentaire | Preuve expérimentale à combiner après exécution | Ce qui resterait à faire pour une réponse entièrement défendable |
|---|---|---|
| R1.1 / R4.1 — chaîne causale / contournements | v3 : MOOT/concurrent, confiance resolver ; v4 : ADMIT→INCLUDE→AGGREGATE et désactivation, traces EVM | Cartographie détaillée des règles et checks ; schéma Solidity compressé, pas de graphe arbitraire ; preuve de raffinement ou énoncé précis des responsabilités off-chain |
| R1.2 / R3 W2 — baselines Eager, abort, cascade | v3 : comparaison appariée avec Eager, abort et réaudit ; v4 : trois fautes successives à 25/100/500 clients | Maintenir la distinction `aggregate_reaudit` vs vraie cascade ; expliciter l'assurance différente d'Eager ; si le gain n'apparaît pas, ne pas l'inventer |
| R1.4 / R4.4 — grande fenêtre, coûts et latence E2E, throughput | v3 : fenêtre 11 blocs ; v4 étendue : même chaîne causale, taille de mise à jour 16 KiB et 1 MiB, round Flower partagé entre Eager/ContestFL et mesure séquentielle de bout en bout | Le débit multi-round en régime permanent n'est pas mesuré ; si c'est revendiqué, il faut une véritable expérience multi-round, sinon dire explicitement « equivalent completed rounds per hour under sequential one-round execution » |
| R1.5 / R2 — profondeur 256, roots 500 clients, cycle Merkle | v4 étendue : preuves d'admission sur arbre 256 et 32, 500 clients ; résultats historiques root-only | **Partiel** : le pipeline de réception, disponibilité des preuves, non-inclusion et full lifecycle ne sont pas implémentés pour le root-only. Ne pas généraliser les gains aux fonctions absentes |
| R1.6 / R4.6 — flooding, quotas, p95/p99, timeouts | v3 : 48 essais de contention ; v4 étendue : répéter avec `expireChallenge` réel et classifier `C1_miss` séparément, tails et blocs saturés | Expiration est provoquée par injection « pas de réponse resolver » et **n'est pas** un taux naturel d'indisponibilité ; quotas par adresse contournables par identités multiples |
| R3 W1 / R2 — montée en charge, RTT, « cross-organization » | v4 étendue : 25/100/500 clients avec taille constante, 100×1 MiB, option 500×1 MiB ; Netem RTT 100 ms | C'est une **sensibilité réseau sur hôte unique** ; ne pas affirmer déploiement multi-site ou disponibilité réelle d'object-store |
| R3 W3 / R4.5 — key activation, shared retry | v4 chaîne 1→2→3, 3→1, modèle formel dynamique déjà présent | La preuve de correspondance avec un DAG arbitraire et les budgets par niveau reste distincte |
| R2 / R4.3 — terminaison et fallbacks | Expériences v4 avec 3 reprises partagées + formal bounded check | **Pas résolu par des benchmarks** : corriger Eq. (8), la preuve et la définition des fallbacks par clé |
| R1.7 / R2 — C1, disponibilité de preuve, confiance certificats | v3 trust-boundary et watcher ; v4 timeout and challenge acceptance | Clarifier les hypothèses C1/T3, donner un contrat de certificats sémantique ; impossible de prouver l'autonomie du smart contract par ces seules mesures |
| R1.8 — adaptateur non texte | Adapters `AggregateAdapter` (replay numérique) + canonicité des artefacts Flower | Identifier précisément les preuves numériques vérifiées vs les hashes enregistrés sur-chain |

## Position scientifique conseillée

La contribution centrale peut être affirmée fortement : *ContestFL définit une correction/versioning dépendance-aware et une finalisation déterministe, prouvées **sous des conditions explicites** ; le prototype Besu mesure des chemins réels de correction, et la v4 étendue caractérise leurs coûts, délais, limites de saturation et changement d'échelle.*

La portée n'a pas à être « fortement réduite » si les théorèmes sont correctement établis. Mais aucune campagne ne transforme une hypothèse sur la sincérité du resolver, la disponibilité des témoins ou la couverture C1 en garantie inconditionnelle. Renforcer la crédibilité ne consiste pas à effacer ces prémisses.
