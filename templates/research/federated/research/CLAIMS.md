# Federated composition claim ledger

| ID | Claim | Alternatives | Decisive evidence | Kill criterion | Status |
|---|---|---|---|---|---|
| C-001 | Sparse paired evidence composition recovers real subject-level multimodal gain. | Gain is calibration, class prior, or availability-mask information rather than cross-modal synergy. | E0/E1 against calibrated late fusion plus within-label subject shuffling. | No material drop under within-label shuffle, or >10% paired bridge needed. | proposed |
| C-002 | Versioned evidence contracts tolerate asynchronous expert evolution without fusion retraining. | Performance comes from static experts or frequent hidden fusion updates. | E4 staleness, unequal update rates, architecture swaps, calibration drift, and retraining-cost accounting. | Fusion retraining cost approaches coordinated FL or four-version performance falls below 90% of static. | proposed |
| C-003 | No-round composition offers a useful accuracy/coordination frontier. | HA-Fedformer, Harmony, FedAFD, or vertical FL dominates under matched assumptions. | E2 matched data, communication, public-anchor, and synchronization accounting. | Existing method wins with comparable coordination/privacy assumptions on two datasets. | proposed |
