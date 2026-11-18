# JISAS-D-26-07235 — couverture expérimentale après l'extension v4

Ce document distingue **préparation du code**, **résultats v3 mesurés** et **preuves non encore obtenues**. Les scénarios v4 ne deviennent des résultats que lorsque les CSV Besu ont été fournis et audités.

| Critique | Après v3 + v4 | Niveau raisonnable de réponse |
|---|---|---|
| R1.2, R3 W2 — alternatives abort/restart, cascade, Eager | v3 : benchmarks appariés à faute unique ; v4 : chaîne 3 corrections, ablation `aggregate_reaudit` ; Eager uniquement v3 | **Partiel à substantiel.** Les alternatives restent des politiques sur banc commun ; ne pas présenter `aggregate_reaudit` comme une vraie cascade générale ni promettre un avantage universel. |
| R1.1, R3 W3, R4.1, R4.5 — règles, activation/désactivation, bypass | v3 : tests MOOT/concurrent, modèle dynamique ; v4 : 1→2→3 et 3→1 sur Besu | **Partiel.** Solidity reste un schéma compressé, sans raffinement général pour un graphe arbitraire ; resolver et runners restent de confiance. |
| R1.4, R4.4 — fenêtres réalistes, Eager, latence E2E, débit FL | v3 : fenêtres 11 blocs, protocole mesuré, Eager distinct ; watcher et modèle débit/RTT | **Partiel.** Pas de débit d'entraînement FL complet ni transfert réel d'artefacts de 100 MiB ; le modèle réseau reste paramétrique. |
| R1.5, R4.2, R2 — root-only, 256 bits, lifecycle, disponibilités | v3 : ablation root-only partielle et tests de preuves sélectionnés | **Insuffisant pour une équivalence fonctionnelle complète.** Restriction des revendications ou nouvelle implémentation full-cycle nécessaire. |
| R1.6, R4.6, R2 — flooding, challenge honnête, quotas, p95/p99, abort | v3 : 48 essais, 360 tx sans quota = 0/8 à l'heure, avec quota = 8/8 | **Partiel.** Inclusion avant deadline mesurée, mais pas d'aborts endogènes dus à expiration ni de garantie Sybil / saturation prolongée. |
| R3 W1 — WAN/object-store, cross-organization | Netem 4/7 validateurs, fenêtre dimensionnée analytiquement | **Partiel.** Validateurs co-localisés ; sensibilité WAN n'est pas un déploiement multi-site. |
| R1.8 — adaptateur non texte | Le banc inclut vérification de preuves Sparse Merkle et replay de l'agrégat | **Exploitable** si le texte précise quels artefacts sont vérifiés sur chaîne, hors chaîne et par hypothèse. |
| R2, R4.3 — bound de terminaison, budgets par niveau, fallback | Modèles bornés et essais v3/v4 avec budget partagé de 3 | **Non résolu expérimentalement ou théoriquement.** Corriger preuve/Equation (8) ou limiter la propriété ; aucun benchmark ne peut substituer cette démonstration. |

## Conclusion éditoriale

**Non : ce patch seul ne clôt pas *tous* les commentaires expérimentaux.** Il renforce précisément la contribution « correction de dépendances successives ». Pour une réponse JISA sérieuse sans allonger le manuscrit, nous proposons : (1) remplacer les figures/tableaux existants par les mesures v3 solides et le résultat v4 s'il est favorable ; (2) limiter clairement les énoncés C1, proof availability, T3, Merkle full-cycle, multi-site ; (3) ajouter au minimum une mesure de **training throughput** ou reconnaître explicitement que les chiffres v3 sont des durées de protocole, et mesurer/justifier les **timeout-induced aborts** demandés par R4 ; (4) corriger la démonstration de terminaison indépendamment des expériences.
