# {{PROJECT_NAME}} research charter

- Initialized: {{CREATED_DATE}}
- Primary question: How do representation alignment, graph structure, and mechanistic conservation change accuracy, validity, and out-of-distribution robustness under leakage-resistant, compute-matched evaluation?
- Primary contribution: a controlled benchmark across reaction direction and mechanism level, with matched inference budgets and patent/transformation-disjoint stress tests.
- Unit of analysis: an overall reaction for endpoint/retro, an elementary transition for step evaluation, and an overall reaction endpoint for pathway recovery.
- Primary lanes: scratch-trained, released-checkpoint reproduction, and pretrained/open-book, never pooled silently.
- Go criterion: phase-0 adapters agree on record identity/canonicalization and reproduce a small published slice within a predeclared tolerance.
- Kill criterion: if the benchmark cannot make dataset variants, test-time calls, and split leakage comparable, do not publish cross-method rankings; release only adapter/evaluator findings.

## Non-negotiable design choices

- Derive only the pinned reaction-center/grouping signature from raw eligible reactions before split assignment; never expose those mapper outputs as model features or vocabulary. After assignment, split before augmentation, model-facing atom-mapping alignment, vocabulary construction, or template extraction.
- Group application/grant duplicates, patent families, normalized reactions, and identical retro products.
- Report legacy, patent-temporal, and transformation-disjoint tracks separately.
- Use mixed reactant/reagent input as the primary forward endpoint task; role-separated input is a leakage diagnostic.
- Deduplicate precursor/product candidates before top-k.
- Report model calls, expanded states, latency, throughput, and peak VRAM with accuracy.
- Report stochastic samples per state, n-best retained, generated candidates, and model-forward counts; beam width alone is not a compute budget.
- Released checkpoints are reproduction-only. Every model must be retrained for a new transformation-disjoint split before cross-method comparison.
- Store all evidence under `$CODEX_RESULTS_DIR`, checkpoints under `$CODEX_CHECKPOINTS_DIR`, and only the completion sentinel at its worktree marker path.
- Exact match recovers the recorded answer, not every chemically valid answer; stratified expert review is required for non-exact predictions.
- Phase 1 retro is single-step only. A later multistep route-planning task must separately pin the building-block catalog and date, search budget, route-cost function, solved-route criterion, and tree/route-diversity metrics before it can enter any retrosynthesis-planning claim.

## First decisive hypotheses

1. Mechanistic conservation improves validity and OOD behavior even when it does not win IID endpoint exact match.
2. R-SMILES gains shrink when architecture, optimizer updates, augmentation, and total inference calls are matched.
3. Method rankings change materially under patent-temporal and transformation-disjoint splits.
4. Forward and retro rankings correlate weakly, and round-trip metrics inflate when forward/retro systems share data or representation bias.
