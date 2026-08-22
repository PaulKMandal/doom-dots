# Codex-first research workflow redesign

## Verdict

Living primarily inside Codex is feasible. The original repository already had the difficult execution foundations—local-canonical Git, hidden snapshots, isolated server worktrees, durable tmux, trusted commits, and frozen jobs—but it treated research as one implementation turn followed by one results summary. The redesigned layer makes the research conversation persistent while bounded worker/auditor processes handle code and evidence.

The immediate workflow does not require moving server files to a laptop for ordinary research discussion:

```text
managed PI conversation in Emacs/tmux
  -> committed implementation checkpoint
  -> frozen experiment + sealed artifact manifest
  -> independent implementation/method audit
  -> interpretation with alternatives, pivots, and kill criteria
  -> same PI conversation reads the result
```

## What is implemented

### Research judgment

- The global and repository AGENTS templates now require an experimental contract, end-to-end semantic validation, adversarial self-review, evidence classification, alternative explanations, bounded decisive follow-ups, future directions, reusable contributions, and explicit kill criteria.
- A negative result ends a run, not the conversation. Codex may still recommend stopping, but only by naming the failed claim, evidence quality, stopping criterion, opportunity cost, and reusable work.
- Completed jobs use two separate read-only Codex passes:
  1. an independent audit traces the invoked config, data/split, implementation, model/checkpoint, decoding, aggregation, and metric;
  2. interpretation reads that audit and classifies the evidence as invalid, incomplete, valid negative, mixed, or positive.

This is intentionally not forced optimism. Invalid results cannot kill a scientific claim; valid negative results can.

### One continuous research session

The interactive `$CODEX_JOBCTL` broker now supports:

```sh
"$CODEX_JOBCTL" request --name NAME [options] -- COMMAND ARG...
"$CODEX_JOBCTL" list
"$CODEX_JOBCTL" status RUN_ID
"$CODEX_JOBCTL" logs RUN_ID
"$CODEX_JOBCTL" artifacts RUN_ID
"$CODEX_JOBCTL" analyze RUN_ID
"$CODEX_JOBCTL" analysis RUN_ID
```

The first command is the existing trusted frozen launch. The other commands let the same live TUI inspect a run, verify its sealed artifact inventory, start the independent audit/interpretation, and retrieve the report. The TUI remains open while the experiment and reviewer run independently.

### Emacs

- `SPC r c e` starts or reattaches to the managed read/write Codex TUI in an Emacs vterm.
- `SPC r c v` pastes the selected region into that composer without submitting it.
- The existing `SPC r c i` external-kitty path remains available.
- `SPC r c a` remains a deliberately read-only monitor.

This preserves the established hidden-worktree and trusted-commit safety boundary. It is a useful immediate editor integration, not yet a native message/diff/approval UI.

The correct rich-client endpoint is the official [Codex App Server](https://developers.openai.com/codex/app-server), which supports persistent threads, resume/fork/read/list, turns and steering, streamed messages and diffs, and approvals. Use its stable stdio JSONL transport through SSH; do not expose the experimental WebSocket endpoint publicly. A longer-term Emacs client should retain the current worktree/commit/job brokers and replace only the terminal presentation layer.

Two third-party prototypes are worth evaluating in an isolated configuration:

- [agent-shell](https://github.com/xenodium/agent-shell) with [agent-shell-tramp](https://github.com/junyi-hou/agent-shell-tramp) and the App-Server-backed [codex-acp adapter](https://github.com/agentclientprotocol/codex-acp) has the clearest remote/TRAMP story.
- [benthamite/codex](https://github.com/benthamite/codex) is closer to a native Codex-specific Emacs UI, but its documented remote story is weaker.

Do not point either prototype at the normal server checkout with unrestricted editing. It must attach to the managed isolated worktree or operate as a read-only PI/reviewer thread until commit-broker integration exists.

ChatGPT desktop also has an official [SSH remote-project connection](https://developers.openai.com/codex/remote-connections). That is an immediate no-upload fallback for discussion or read-only review. It should not replace the local-canonical editing workflow unless its writes are routed through the same broker.

### Repositories and review bundles

`bin/research-repo` provides:

```sh
# New or empty repository; defaults to rhel-test and /home/rhel/Projects/NAME
research-repo init --project-root /path/to/repo --template generic
research-repo init --project-root /path/to/chem-reaction-bench --template chemistry
research-repo init --project-root /path/to/federated-compose --template federated

research-repo doctor --project-root /path/to/repo
research-repo bundle-code --project-root /path/to/repo
```

Initialization is idempotent and conflict-safe: it refuses to overwrite a differing managed file. It is not an all-or-nothing filesystem transaction, so an interrupted `git init` or accepted earlier writes can remain and should be completed by rerunning the same command. It creates:

- the research AGENTS contract;
- `research/PROJECT.md`, claim/decision/run ledgers, and an experiment-spec template;
- versioned scaffold metadata;
- `.dir-locals.el` remote/Codex settings;
- generated-data and secret exclusions;
- a task-specific benchmark skeleton for chemistry or federated composition.

The code bundle contains current working-tree bytes for tracked and vetted untracked code/config/docs, plus Git status, working-tree patch, and a per-file hash manifest. It excludes data, results, reports, runs, checkpoints, weights, caches, environments, common secret filenames, and personal `custom.el` state.

### Reports and results

- `SPC r j p` pulls a selected job's small report profile into `reports/codex-jobs/RUN_ID/`; a differing existing destination gets a versioned sibling.
- `SPC r j P` confirms and pulls the complete results/checkpoints profile into `artifacts/codex-jobs/RUN_ID/`, also without overwriting a differing snapshot.
- The CLI equivalent is `codex-remote job-pull ... --profile report|full`.

Every new terminal run records `artifacts.manifest.json` with role, size, and SHA-256 for each regular result/checkpoint. Export refuses if those artifacts changed after finalization. The report profile includes provenance, status, environment, logs, audit/analysis, figures, tables, and small report-like result files; it omits checkpoints and large/raw outputs. The full profile is explicit and size-bounded. Legacy report pulls are metadata-only with a provenance warning; legacy full pulls seal post hoc and say so. The process-group cleanup covers ordinary foreground descendants, not a deliberately daemonized process escaping into a new session; use cgroups or the cluster scheduler for an adversarial boundary.

The ordinary laptop-to-server rsync now always excludes Git metadata and generated research storage, uses delayed deletion, and refuses more than a bounded number of deletions. It also rejects root, home, and other shallow remote destinations.

## Daily workflow

1. Open the local canonical checkout.
2. For a new repository, run `SPC r c n`, select the research template, and review `research/PROJECT.md`, `research/CLAIMS.md`, and `.dir-locals.el` before committing.
3. Run `SPC r c g` once for the server account and keep the repository `AGENTS.md` committed.
4. Run `SPC r c e`. Discuss the question, design, evidence, or code in the same TUI; use `SPC r c v` for selected editor context.
5. Require a committed evaluator/implementation checkpoint and configured test command before launching a job.
6. Let Codex use `$CODEX_JOBCTL request`. Continue the discussion or detach; the job survives laptop sleep.
7. In the same TUI, use `$CODEX_JOBCTL status/logs/artifacts`, then `analyze` and `analysis` after the run is terminal.
8. Pull code checkpoints with the existing `SPC r c p`/normal remote commands. Pull only the small report profile when local inspection is useful.
9. Use `SPC r c b` only when an external human or separate model needs a code review package.

## Remaining gaps and priority order

### P0 before scaling research

1. Build the native App Server Emacs client with persistent thread IDs and resume after TUI exit/reboot. The embedded vterm survives detach but does not make a dead TUI resumable.
2. Add a pre-launch independent reviewer for experiments whose cost exceeds a configurable threshold. The current independent audit occurs after the run.
3. Add structured read-only versus read-write data links; current directory data links are writable by design.
4. Add project identity sentinels to normal rsync in addition to the new shallow-path, exclusion, and deletion-limit guards.

### P1 quality of life

- Render a job dashboard in Emacs with run state, artifact inventory, audit disposition, and one-key report pull.
- Add `upgrade` with managed blocks for evolving existing research scaffolds without overwriting user prose.
- Generate run cards and comparison tables from typed metrics schemas, with automatic provenance links back to source SHA and split manifest.
- Add dataset/license policy checks and record-level provenance before download/training.
- Track compute budget, wall time, GPU-hours, and inference calls alongside scientific metrics.
- Add a literature/evidence ledger that pins primary-paper revisions and records which claim each citation supports.
- Add a bounded notification when a run or two-pass review finishes.

## Chemistry investigation

The skeleton is under `templates/research/chemistry`.

Scientific framing: controlled evaluation of representation, mechanistic constraints, leakage, and inference budget across reaction direction. Merely reproducing official random-split numbers is engineering; the publishable kernel is compute-matched evaluation across legacy, patent-temporal, and transformation-disjoint splits.

Key correction: [FlowER](https://doi.org/10.1038/s41586-025-09426-9) is a forward mechanism/outcome model, not a retrosynthesis baseline. Use the publication code tag `2.0.0` and released mechanism/checkpoint artifact. [R-SMILES](https://pmc.ncbi.nlm.nih.gov/articles/PMC9365080/) is root-aligned representation preprocessing around a Transformer; compare it against canonical and randomized SMILES with architecture, optimizer updates, augmentation, and total test-time calls matched.

The skeleton includes four task contracts, split/leakage invariants, manifests for revisions/checksums/licenses, phase-0 evaluator spec, a canonical record/prediction contract, and executable smoke tests. It explicitly flags noncommercial/upstream licensing risks in mechanistic data. Phase 1 retrosynthesis is single-step only; multistep route planning is deferred until a purchasable-building-block catalog, search budget, route objective, solved-route rule, and tree/route metrics are pinned.

## Federated investigation

The skeleton is under `templates/research/federated`.

The raw shared-latent idea is too close to prior multimodal FL and is not identifiable with zero paired anchors. The defensible delta is versioned inference-only expert composition: no global training rounds, common calibrated task evidence, sparse paired dependence correction, explicit model-version/staleness evaluation, and complete coordination-cost accounting.

The inspiration is [Heterogeneous Decentralized Diffusion Models](https://openaccess.thecvf.com/content/CVPR2026/html/Jiang_Heterogeneous_Decentralized_Diffusion_Models_CVPR_2026_paper.html), but its experts share an image domain and exact diffusion-coordinate conversion. Clinical modalities do not. The closest competing claim is [HA-Fedformer/UTMP](https://arxiv.org/abs/2303.15486), so ordinary “unimodal local training, multimodal prediction” is not novel.

Start with [Symile-MIMIC](https://physionet.org/content/symile-mimic/1.0.0/) CXR/ECG/labs and in-hospital mortality. The skeleton includes calibrated evidence math, expert compatibility contracts, E0 baselines, E1 paired-bridge sweep, E4 model-version stress tests, within-label subject shuffling, and preregistered go/kill criteria. It always reports absolute AUROC gain and treats the recovery fraction as non-informative unless the centralized oracle beats the strongest unimodal expert by at least 0.01 AUROC. ADNI MRI/proteomics is a later showcase only if the inexpensive first milestone survives.
