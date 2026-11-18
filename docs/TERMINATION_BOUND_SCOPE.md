# Theorem 3 / Eq. (8): bounded-termination repair obligations

The prototype has a *single global* non-renewable retry pool (`retryBudget`) and a **terminal round-level** resolver fallback. The abstract paper algorithm permits per-level retry budgets and describes per-key fallbacks; therefore a proof that counts only one fallback is **not valid** for all paper-level executions.

## Correct accounting requirement

Let `E` be an execution after the last network stabilization point. Define:

- `N_w(E)`: number of sequential challenge windows (include any renewed window after publication or key activation).
- `N_res(E)`: sequential response/arbitration stages.
- `N_p(E)`: sequential publication stages.
- `N_f(E)`: distinct fallback invocations **including every key-level fallback**.
- `N_fin(E)`: terminal finalization or abort stages.

Under (i) finite maxima `\bar N_w`, `\bar N_res`, `\bar N_p`, `\bar N_f`, `\bar N_fin` **derived from the actual transition rules**; (ii) fixed upper deadline per stage, including fallback; (iii) post-stabilization transaction inclusion and response liveness; and (iv) fail-closed termination when evidence is unavailable, we may state a safe *conditional stage bound*:

```text
B_recovery <= Nw_max * W_challenge
            + Nr_max * W_response
            + Np_max * W_publication
            + Nf_max * W_fallback
            + Nfin_max * W_terminal
```

Here all `W` and `B` are in *blocks* (not seconds). Conversion to wall-clock additionally assumes a bound on block production under the network/fault model. If the maximum number of active keys `K` or the number of times an active key can be recreated is unbounded, `Nf_max` and `Nw_max` cannot simply be asserted finite.

For the **experimental Solidity contract**, a single retry counter is incremented exactly once at each accepted coordinator replacement. It cannot exceed the configured round budget `R`. After that, *at most one terminal round fallback* may occur, and no new challenge window is opened by that fallback. Consequently **under the contract's normal phase rules and ledger liveness** the sequence of accepted replacement rounds has length `<= R`, and there are `<= R+1` ordinary challenge windows. These counts exclude transaction congestion, a malicious/failed resolver, or a challenge whose response deadline is already exceeded; the latter leads to fail-closed abort by an explicit expiry transaction if it is ordered.

This **does not** transfer to the abstract per-key fallback model without extra lemmas. A valid paper-level proof must supply:

1. a finite bound on total decision keys ever activated (including reject→admit), with a finite bound on reactivation;
2. a non-renewable progress measure which decreases under **each** retry, activation, fallback, and descendant repair stage;
3. a bound on sequentially serviced per-key fallback operations (not just a boolean «fallback used»);
4. sound certificate/availability assumptions or safe abort on deadline;
5. explicit ledger finality and synchrony conditions.

`formal/dynamic_dependency_check.py` explores two clients and restricted budgets; it is **bounded model exploration**, not a parameterized proof. Do not claim revised Eq. (8) follows solely from that checker.
