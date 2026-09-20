# Competitor figure plan

The analysis deliberately produces both overview figures and fixed-client
views. The final paper need not include all of them.

## Main-text candidates

1. `fig1_fault_outcome_matrix.pdf` — semantic outcomes across designs and
   faults. Full width.
2. `fig2_clean_cost_scaling.pdf` — gas, block span, and latency versus clients.
   Full width.
3. `fig3_clean_and_fault_cost_100_clients.pdf` — clean, aggregate-fault, and
   laundering costs at a fixed 100-client operating point. Full width.
4. `fig4_expected_gas_vs_dispute_rate.pdf` — trace-driven expected gas under
   increasing dispute rates, separated by client count. Full width.
5. `fig5_expected_replay_vs_dispute_rate.pdf` — eager versus on-demand replay
   projections at multiple update sizes. Full width or appendix.

## Single-column alternatives

- `fig2_clean_cost_at_10_clients.pdf`
- `fig2_clean_cost_at_50_clients.pdf`
- `fig2_clean_cost_at_100_clients.pdf`
- `fig6_eager_adapter_breakdown.pdf`
- `fig7_compact_operating_point_100_clients.pdf` — compact 2×2 IEEE-column view.

These are sized at 3.45 inches wide and retain at least 7-point text at final
size. They allow the paper to present one representative operating point in the
main text while placing the other client counts in an appendix.

## Visual conventions

- same design always uses the same color, marker, and hatch;
- colorblind-safe palette with grayscale redundancy;
- 7.0–8.4 pt typography at final size;
- 1.55 pt lines and 4.4 pt markers;
- no chart titles when the caption can carry the context;
- light horizontal grids only;
- PDF with embedded TrueType fonts and 600-dpi PNG backup.

## Recommended selection

For a constrained IEEE paper, use the outcome matrix, clean scaling, the
100-client clean/fault comparison, and the dispute-rate figure. Keep the three
fixed-client views and adapter breakdown in supplementary material. The replay
projection belongs in the main text only if the eager-versus-optimistic regime
is a central claim.
