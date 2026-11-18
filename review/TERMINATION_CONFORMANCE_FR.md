# ContestFL — audit du théorème de terminaison et de son instanciation EVM

## Résultat de la vérification (12 novembre 2026)

**La preuve abstraite est cohérente sous les hypothèses explicitement ajoutées ; la garantie de terminaison bornée n'est PAS implémentée pour toutes les phases de la version Solidity évaluée.** Il ne faut pas confondre les deux propriétés.

### Protocole abstrait

La mesure de rang `P = somme des jetons historiques restants + premières activations non utilisées` fournit une décroissance strictement positive pour toute nouvelle fenêtre non primaire, **à condition** que chaque remplacement provisoire doive effectivement consommer un jeton ou une première activation non réutilisable. La résolution d'une fenêtre gelée termine si chaque clé vacante d'un univers fini est traitée une seule fois en ordre topologique, avec timeout/fallback borné. La borne conservatrice est :

```
Δr ≤ Δinit + Δfin + Emax (Δwin_max + Δres_max + Mr Δslot_max)
Emax = 1 + Σ b_l + F ; Mr ≤ 2n + 1.
```

Le terme `Δslot` doit comprendre attente du coordinateur, soumission, certificat, attente/fallback du resolver, inclusion blockchain ou expiration. La preuve repose aussi sur la **fermeture gelée**, sur un ensemble fini de clés et sur une réaction bornée d'un acteur honnête habilité à déclencher l'action de repli. Ce n'est pas un théorème de délai absolu sous partition réseau arbitraire.

Le vérificateur deux clients confirme, pour ses bornes d'exploration, les chemins d'activation/désactivation, les deux politiques de jetons et la terminaison de son abstraction. Cela ne suffit pas à établir le raffinement du contrat.

### Contre-exemple exécutable au niveau de la logique du contrat

Dans `contracts/ContestFLExperiment.sol`, on peut atteindre :

1. `openRound`, soumissions, décisions et `publishInitialState` -> `CHALLENGE`.
2. `openChallenge(AGGREGATE)` -> contestation ouverte.
3. `resolveChallenge(..., REVISED, ...)` -> `RESOLVING`, `openChallenges=0`, `needsReplacement=true`.
4. Le coordinateur cesse de répondre ; le resolver cesse de répondre. Un autre acteur honnête est toujours actif et pourrait soumettre des transactions.
5. `finalize` refuse la phase `RESOLVING`. `expireChallenge` refuse la contestation déjà `REVISED` ; l'unique chemin `publishCoordinatorReplacement` exige `onlyCoordinator`, tandis que `publishResolverFallback` et `abortRound` exigent `onlyResolver`.

Le contrat n'a ni `expireReplacement` public, ni délai de progression explicite en `RESOLVING`. L'état peut donc persister indéfiniment sans violer une règle de transition EVM. Un autre manque existe en `SUBMIT` : pas de délai de soumission ni d'abandon permissionless. Ce contre-exemple est déterminé par les guards Solidity ; l'audit source est reproductible par `python3 review/check_termination_conformance.py`. Il ne prétend pas remplacer un test EVM dynamique.

### Décision scientifique

- **Théorème abstrait** : garder une conclusion forte conditionnelle, avec les hypothèses de progrès affichées.
- **Prototype mesuré** : ne pas promettre liveness inconditionnelle du contrat. La gestion des rôles et les timeouts existants ne suffisent pas.
- **Pour rendre le contrat conforme** : ajouter des deadlines de publication et de résolution stockées on-chain, des sorties fail-closed publiques et testées (`expireSubmission`, `expireReplacement`), et des délais vérifiables à chaque transition bloquante ; tester sous acteurs silencieux et, seulement ensuite, réévaluer le coût des nouvelles transitions. Ce serait une **nouvelle version du contrat** : ne pas réattribuer automatiquement les chiffres v3/v4 à la version changée.

Le résultat négatif ne ruine pas la contribution principale : la preuve porte sur un modèle plus général que le banc fixe, mais cette distinction doit être explicitement présentée.
