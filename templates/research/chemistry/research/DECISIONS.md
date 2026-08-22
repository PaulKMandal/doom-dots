# Decision log

## D-001 — Separate task contracts

- Date: {{CREATED_DATE}}
- Decision: Forward endpoint, atom-mapped elementary-step prediction, unmapped pathway search, and single-step retrosynthesis have separate inputs, targets, metrics, and tables.
- Reason: FlowER is a forward mechanism/outcome model; putting it in a retro table without an inverse model would be a category error.

## D-002 — Controlled R-SMILES comparison

- Date: {{CREATED_DATE}}
- Decision: Treat R-SMILES as a representation and hold architecture, updates, data, seeds, and inference calls fixed against canonical/randomized SMILES.
- Revisit when: a method contribution beyond root alignment is explicitly implemented.

## D-003 — Dataset identity

- Date: {{CREATED_DATE}}
- Decision: “USPTO-50K” or “USPTO-Full” is never a sufficient identifier. Record source URL, processing revision, checksums, counts, mapper, and split checksum.
