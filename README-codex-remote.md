# Durable remote Codex from Doom Emacs

This configuration keeps the laptop checkout canonical while Codex runs in an
isolated server worktree under `tmux`. The existing rsync/SSH experiment path is
preserved.

The two Codex modes return work differently:

- one-shot `codex exec` tasks still return a sanitized delta as ordinary local
  modifications;
- managed interactive tasks start from a clean named local branch, instruct
  Codex to create small coherent commits, and let the laptop pull those commits
  repeatedly while the TUI remains open.

Interactive checkpoint pulls preserve Codex's individual commit messages and
author metadata. They are integrated in a temporary worktree and fast-forwarded
onto the current laptop branch only after a clean three-way replay. A conflict
never modifies the canonical checkout.

The frozen experiment-job layer remains separate. Interactive Codex may request
one job from an exact committed checkpoint; the trusted runner freezes that
revision and launches the job immediately in a dedicated worktree while the TUI
continues running.

## Existing remote workflow, now with automatic checkpoint reconciliation

The familiar bindings remain the normal interface:

| Binding | Behavior |
| --- | --- |
| `SPC r s` | pull any new committed interactive-Codex checkpoints, then rsync the laptop project to the normal server checkout |
| `SPC r r` | pull checkpoints, sync only when that pull advanced the laptop branch, then run the configured remote command |
| `SPC r R` | pull checkpoints, always sync, then run |
| `SPC r u` / `U` | pull, then setup remotely / pull, always sync, then setup |
| `SPC r q` / `Q` | pull, then smoke test remotely / pull, always sync, then smoke test |
| `SPC r T` | pull checkpoints, sync only when needed, then run configured remote tests |
| `SPC r t` | open a vterm in the normal server checkout |

Thus the lowercase commands retain their old no-sync behavior when Codex has no
new commits. When a live checkpoint is imported, the same keypress automatically
rsyncs before running so the normal server checkout cannot lag behind the newly
advanced laptop branch.

The Codex worktree is never placed in `my/remote-dir`, so `rsync --delete`
cannot erase unfinished interactive work.

## Added bindings

### Codex editing commands

The Codex commands are under `SPC r c`:

| Binding | Action |
| --- | --- |
| `SPC r c d` | check local/server prerequisites and Codex authentication |
| `SPC r c s` | start an ordinary one-shot `codex exec` task without job authorization |
| `SPC r c S` | start one-shot Codex with authorization to request one frozen experiment job |
| `SPC r c t` | show task, live-checkpoint, and local orchestration status |
| `SPC r c a` | monitor a live Codex task read-only inside Emacs |
| `SPC r c i` | start or reattach to autonomous interactive Codex; one frozen job is authorized |
| `SPC r c I` | compatibility alias for the same job-enabled interactive workflow |
| `SPC r c p` | manually pull the latest committed interactive checkpoint without ending the TUI |
| `SPC r c j` | open the ordinary one-shot Codex prompt/watcher in kitty |
| `SPC r c l` | show preserved task, Codex, environment, and test logs |
| `SPC r c r` | publish a preserved orphaned/failed worktree without rerunning Codex |
| `SPC r c f` | pull interactive commits, or import a completed one-shot result |
| `SPC r c x` | request Codex-task cancellation while preserving its worktree |
| `SPC r c c` | archive an imported task and remove its worktree/refs |
| `SPC r c X` | explicitly discard a task and its unimported work |
| `SPC r c g` | install/update the managed global `~/.codex/AGENTS.md` block on the server |
| `SPC r c A` | create from the research template, or open, the project `AGENTS.md` |

With a region active, `SPC r c s` or `SPC r c S` sends the region as the prompt.
With a prefix argument, either command opens a multiline prompt buffer; submit
with `C-c C-c` or cancel with `C-c C-k`.

`SPC r c s` remains the one-shot mode. It does not expose granular internal
Codex commits: the runner publishes one sanitized result commit and imports its
net delta as local modifications. `SPC r c S` adds the older finalize-then-launch
job path.

`SPC r c j` starts that ordinary one-shot mode from an external terminal and has
no frozen-job authorization. Closing its watcher does not cancel the task.

`SPC r c i` is the persistent conversational mode. Starting a new interactive
task requires a clean, named local branch because the server's real commit chain
will later be integrated into that branch. Doom creates the isolated server
worktree, launches Codex under durable `tmux`, and opens kitty. Running the same
binding again reattaches to the existing TUI and conversation.

Managed interactive sessions use GPT-5.6 Sol at extra-high reasoning, approval
policy `never`, a `workspace-write` sandbox, public dependency-network access,
a task-private Nix/uv/Python cache, and stable `Codex Remote` Git author and
committer identity. Codex is instructed to commit each validated logical unit
and never amend, rebase, reset, or otherwise rewrite a commit created in the
managed session because the laptop may publish it at any time.

Closing kitty, detaching with `C-b d`, losing SSH, or suspending the laptop only
detaches. While Codex remains open, use the ordinary `SPC r` sync/run/test
commands; they pull any new commits automatically. `SPC r c p` is available for
a pull without any subsequent remote action. `SPC r c f` remains a compatible
manual pull entry point.

When the session is genuinely finished, `/exit` or `/quit` lets the runner
commit any remaining safe dirty files, refresh a changed environment, run the
configured tests, and publish the final commit chain. A final normal command or
`SPC r c f` imports any last commits and acknowledges the task.

The `s`, `S`, `j`, `i`, and `I` entry points still share one outstanding Codex
task per project. Frozen experiment jobs are separate and can continue after the
source Codex task is imported or archived.

### Frozen experiment-job commands

Experiment-job commands are under `SPC r j`:

| Binding | Action |
| --- | --- |
| `SPC r j l` | list all frozen jobs for the current project |
| `SPC r j s` | select a job and show its manifest/runtime status |
| `SPC r j t` | select a job and show recent bootstrap, run, and analysis logs |
| `SPC r j a` | select an active job and monitor its `tmux` pane read-only |
| `SPC r j x` | select and stop an active job after confirmation |
| `SPC r j i` | start a read-only Codex interpretation of a finished job |
| `SPC r j r` | show the latest structured interpretation as Markdown |

These commands select from the project-scoped run registry. They do not require
the source Codex editing task to remain active.

## Requirements

### Laptop

- Git
- OpenSSH client
- Python 3.10 or newer
- kitty (the configured external terminal for `SPC r c i` and `SPC r c j`)
- the supplied Doom configuration

The backend uses only the Python standard library. No Python virtual environment
or additional package installation is required for the orchestration code.

### Server

The login environment selected by `my/remote-host` must provide:

- Bash
- Git
- `tmux`
- `flock`
- Python 3.10 or newer
- Codex CLI, already authenticated for the remote user
- at least 512 MiB free under the remote Codex state area

The backend searches the server login `PATH` for `python3.14` through
`python3.10`, then `python3`, and freezes the selected helper into each task's
state directory. The durable runner itself starts under `bash -lc`, so the
normal login environment—including Nix profile and uv paths—is available to
Codex-generated commands.

Authenticate once on the server, for example:

```sh
ssh -t rhel-test 'bash -lc "codex login --device-auth"'
ssh rhel-test 'bash -lc "codex login status && codex --version"'
```

Codex credentials are not copied from the laptop. The remote user's existing
Codex configuration and authentication are used.

## Installation

Use the modified repository archive, or apply the supplied patch from the root
of the Doom configuration repository. Then ensure the backends are executable
and reload Doom:

```sh
chmod +x bin/codex-remote bin/codex-remote-job

DOOM_BIN="${DOOM_BIN:-$HOME/.config/emacs/bin/doom}"
"$DOOM_BIN" sync
"$DOOM_BIN" doctor
```

If `doom` is already on `PATH`, `doom sync` and `doom doctor` are equivalent.
A NixOS/Home Manager rebuild is not required by this patch series because the
provided Doom repository contains no Nix packaging files; the executable lives
inside the Doom configuration and has no nonstandard Python dependencies.

Restart Emacs or evaluate/reload `config.el`, open a configured project, and run
`SPC r c d`.

## Project configuration

The Codex frontend reuses these existing buffer-local project settings:

- `my/remote-host`
- `my/remote-dir`
- `my/remote-setup-cmd`
- `my/remote-test-cmd`

The following optional variables specialize the isolated Codex worktree:

- `my/codex-remote-bootstrap-cmd`: setup command run once before Codex. When
  nil, `my/remote-setup-cmd` is used.
- `my/codex-remote-test-cmd`: test command run after Codex. When nil,
  `my/remote-test-cmd` is used.
- `my/codex-remote-data-links`: explicit server paths temporarily symlinked
  inside the isolated worktree, expressed as `SOURCE=RELATIVE_TARGET`.
- `my/codex-remote-model`: optional model override. Interactive tasks default to
  `gpt-5.6-sol` when this is nil.
- `my/codex-remote-profile`: optional server-side Codex profile.
- `my/codex-remote-reasoning-effort`: `minimal`, `low`, `medium`, `high`, or
  `xhigh` for one-shot tasks. Managed interactive `SPC r c i`/`I` sessions are
  pinned to `xhigh`, so an older project-local `high` value cannot silently
  reduce their reasoning level.
- `my/codex-remote-enable-search`: non-nil enables live Codex web search.
- `my/codex-remote-timeout`: short SSH connection timeout, default 5 seconds.
- `my/codex-remote-max-untracked-bytes`: per-file transfer limit, default
  20 MiB.

`my/codex-remote-external-terminal-command` is a global customization rather
than a project-local setting. Its default value is
`("kitty" "--title" "Remote Codex")`; the frontend appends the resolved SSH
executable and tmux attachment arguments.

`my/codex-remote-job-program` defaults to `bin/codex-remote-job` in the Doom
repository. `my/codex-remote-job-terminal-command` defaults to
`("kitty" "--title" "Remote Codex Job")`. Doom passes the current project's
resolved options explicitly to the terminal frontend. The same values are also
stored with mode `0600` under the repository's private Git metadata at
`git rev-parse --git-path codex-remote/config.json`, allowing the command to be
run directly from a laptop terminal without parsing `.dir-locals.el`.

Example `.dir-locals.el`:

```elisp
((nil . ((my/remote-host . "rhel-test")
         (my/remote-dir . "/home/rhel/Projects/dataset-artifacts")
         (my/remote-setup-cmd
          . "nix develop .#server --command bash -lc 'uv sync --frozen --extra cuda --group dev'")
         (my/remote-test-cmd
          . "nix develop .#server --command bash -lc 'uv run --no-sync pytest'")
         ;; Optional explicit overrides for the isolated Codex worktree.
         (my/codex-remote-bootstrap-cmd
          . "nix develop .#server --command bash -lc 'uv sync --frozen --extra cuda --group dev'")
         (my/codex-remote-test-cmd
          . "nix develop .#server --command bash -lc 'uv run --no-sync pytest'")
         (my/codex-remote-data-links
          . ("/srv/datasets/project=data"))
         (my/codex-remote-reasoning-effort . "high"))))
```

The bootstrap command must leave all nonignored repository files unchanged.
Creating ignored `.venv`, `.direnv`, caches, or other environment state is fine.
Use locked/frozen dependency commands where the project supports them.

For managed interactive sessions, the runner sets `XDG_CACHE_HOME`,
`UV_CACHE_DIR`, and `PIP_CACHE_DIR` to a task-private directory outside the Git
worktree and grants Codex write access only to that cache in addition to the
worktree. It enables Codex's command-network proxy with public destinations
allowed, local/private destinations blocked, and only the standard
`/nix/var/nix/daemon-socket/socket` Unix socket allowed. This permits normal
public dependency resolution and Nix daemon builds without exposing SSH agents,
D-Bus sockets, private services, or the rest of the server account. `uv add`,
`uv sync`, `nix develop`, `nix build`, and `nix flake check` are in scope when
needed by the requested implementation. Host activation and service-management
commands such as `sudo`, `nixos-rebuild`, `home-manager switch`, `nix profile`,
`nix-env`, and `systemctl` remain explicitly out of scope.

The Codex-specific command overrides, data-link paths, model names, and
profiles are intentionally not globally trusted. The first time a project sets
one of those values, review the exact value in the directory-local prompt and
save only that exact value as safe. Do not add a blanket predicate that accepts
arbitrary strings: the bootstrap/test values execute on the server, and data
links expose the named server content to Codex.

For compatibility with the existing workflow, a nil Codex-specific bootstrap
or test value inherits `my/remote-setup-cmd` or `my/remote-test-cmd`. The
preexisting `remote-dev.el` marks those older variables safe when they are
single-line strings. Therefore, start Codex only from project repositories
whose `.dir-locals.el` you trust, or set explicit Codex-specific overrides and
approve their exact values.

Data links are explicit because ignored datasets and checkpoints are not part of
the hidden Git snapshot. Do not link credentials or unrelated private server
content. Codex can read linked content, and trusted project test commands run
outside the Codex command sandbox. A symlink does not make its source read-only;
source ownership and permissions must enforce read-only access when required.
The backend rejects symlinked target parents so a configured link cannot be
redirected outside the isolated worktree.

Run `SPC r c g` once per server account to install the managed global working
agreement in `~/.codex/AGENTS.md`. The command preserves content outside its
marked managed block, so personal server-wide instructions can coexist with the
Doom-managed policy.

Run `SPC r c A` in each research repository to create or open a checked-in
project `AGENTS.md`. The supplied template covers immutable results, frozen
panels and splits, seeds, model/control substitutions, smoke tests, job requests,
and read-only interpretation. Tailor it to include the repository's exact Nix or
uv commands, generated-file policy, experiment constraints, protected paths, and
read-only data locations, then review and commit it normally.

A frozen-job launch requires a nonempty `my/codex-remote-test-cmd` or inherited
`my/remote-test-cmd`. The command should be a bounded unit/smoke validation, not
the full experiment. A Codex request is preserved but deliberately not launched
when no test command is configured, the environment refresh fails or dirties the
source tree, the test fails or dirties the source tree, Codex exits nonzero, or
the task is cancelled.

## Normal workflows

### One-shot task

1. Edit the local checkout normally; staged, unstaged, and safe untracked source
   files may be present.
2. Run `SPC r c s` and provide the prompt.
3. Let the server-side `tmux` task finish.
4. Run `SPC r c f` to apply the sanitized result delta as ordinary local
   modifications.
5. Review and commit locally as before.

### Interactive task with live commits

1. Commit or stash local work so the current branch is clean and named.
2. Run `SPC r c i` and give Codex the implementation request in its TUI.
3. Codex works in the isolated server checkout and creates coherent commits.
4. Leave the TUI running. Whenever code should reach the laptop and normal
   experiment checkout, use the command you already intended to use:
   - `SPC r s` pulls and syncs;
   - `SPC r r`, `SPC r T`, `SPC r q`, or `SPC r u` pull first and sync only if
     a new commit was imported;
   - uppercase combined commands still always sync.
5. Run `SPC r c i` again whenever conversational input is needed.
6. Use `/exit` or `/quit` only when the interactive session is finished.

A pull publishes only the server's committed `HEAD`. Uncommitted in-progress
Codex edits remain private to the interactive worktree until the agent creates a
coherent commit. The status buffer reports whether the checkpoint worktree is
currently dirty.

When new commits exist, the laptop index and tracked files must be clean so
the branch can advance without flattening or silently mixing local WIP into
Codex's commit history. Unrelated untracked files may remain; a pull stops safely
when an incoming commit would overwrite one of their paths. Commit or stash
tracked edits and repeat the same sync/run/test binding. No separate `SPC r c`
choreography is needed after that.

If local commits and Codex commits conflict, the backend preserves the rebase in
an isolated integration worktree and leaves the canonical checkout unchanged.
Resolve it there, complete the rebase, and rerun the same pull or remote command.

### Terminal one-shot watcher

`SPC r c j` opens kitty, accepts a multiline prompt until `Ctrl-D`, and watches
the same durable one-shot mode as `SPC r c s`. Closing the watcher does not
cancel the server task. Its completed result is imported with `SPC r c f`.

### Cleanup

After the final interactive or one-shot result is imported, `SPC r c c` archives
the task. Starting the next task also archives a prior imported task
automatically. Archive/discard removes the retained Codex tmux session,
worktree, and hidden refs while retaining terminal metadata and logs.

## Frozen experiment jobs

### Launch protocol

Managed interactive sessions started with `SPC r c i` are authorized to request
one frozen experiment job. `SPC r c I` remains a compatibility alias for the
same behavior. For a one-shot implementation-and-launch task, use
`SPC r c S`; ordinary `SPC r c s` and `SPC r c j` remain non-launching.

In an interactive session, Codex first commits the exact source revision to run
and completes reasonable foreground validation. It then invokes the helper
exposed in its environment:

```sh
"$CODEX_JOBCTL" request \
  --name "heldout transfer confirmation" \
  --gpus 0,1 \
  --completion-marker outputs/heldout_COMPLETE \
  --resume-command "python -m experiments.transfer --resume --tag heldout" \
  --metadata panel=confirmation \
  --metadata seed=17 \
  -- python -m experiments.transfer --tag heldout --seed 17
```

The command after `--` is stored and executed as an argv array rather than a
second shell string. Metadata values are descriptive provenance; they do not
replace the exact command or repository-specific run manifest.

For an interactive request, the trusted runner processes the request while the
Codex TUI remains open:

1. remove and validate the request file outside the Codex sandbox;
2. require a clean worktree so the requested source is an exact commit;
3. safety-check and publish that committed checkpoint without rewriting prior
   checkpoints;
4. create a pinned hidden source ref and dedicated detached job worktree;
5. record the run manifest and start a separate `tmux` runner;
6. return the run ID to Codex while the conversation remains available;
7. inside the frozen worktree, rerun the configured bootstrap command and the
   configured bounded test/smoke command before starting the experiment.

The interactive job request may use the original task input commit when no code
change was required. It may also use a later committed checkpoint. Uncommitted
Codex edits are never included. Exactly one request is accepted per Codex task;
subsequent experiment variants should be launched from a new managed task so
source identity and provenance remain unambiguous.

For `SPC r c S`, there is no live request broker. `$CODEX_JOBCTL` records the
request and returns immediately; after Codex exits, the existing one-shot
finalizer publishes the sanitized result, refreshes the environment, runs the
configured test command, and launches the frozen job only when all gates pass.

Codex is instructed not to use `tmux`, `nohup`, shell backgrounding, `systemd`,
or a scheduler directly. The experiment command itself runs as the ordinary
remote user rather than inside the Codex editing sandbox. This is necessary for
the repository's real Nix/uv environment, datasets, and GPUs, but it means job
authorization should be used only for a trusted repository and a reviewed task
on a nonprivileged server account. The runner validates provenance and launch
gates; it is not a general container or semantic malware detector.

The code and experiment lifecycles are independent after launch. Pull committed
source updates with the normal `SPC r` commands while Codex remains active, and
finish/import the source task normally. Archiving that task does not stop or
delete the frozen job. The job executes from its recorded source SHA, so later
Codex or laptop edits cannot alter the running source.

### Run identity and layout

Each run has a unique ID and records the exact argv, source SHA, source task,
host, platform, Python and Git versions, requested and effective GPU visibility,
known lock-file hashes, the frozen-worktree bootstrap command and outcome,
timestamps, completion marker, resume text, model/profile settings, metadata,
process identity, exit code, and analysis state.

The server run directory contains:

```text
~/.local/state/codex-remote/jobs/<project-id>/<run-id>/
├── run.json
├── status.json
├── command.txt
├── bootstrap-command.txt       # when a bootstrap command is configured
├── source-snapshot.txt
├── environment.txt
├── bootstrap.log               # when bootstrap is configured
├── run.log
├── checkpoints/
├── results/
├── analysis-schema.json        # after interpretation starts
├── analysis.json               # structured Codex result
├── analysis.jsonl              # Codex event stream
├── analysis.stderr.log
└── analysis.md
```

The frozen source worktree is separate:

```text
~/.local/share/codex-remote/job-worktrees/<project-id>/<run-id>/
```

The frozen runner first executes the same configured bootstrap command in the
new worktree. It refuses to continue if bootstrap exits nonzero, moves `HEAD`,
changes tracked files, or leaves nonignored files. Ignored local environment
state such as `.venv` may remain for the experiment command. Configured data
links are exposed only after bootstrap succeeds and exist only while the
experiment command is active. The runner verifies and removes them before
marking the run terminal, so later interpretation is limited to the frozen
source and captured run artifacts.

The launched command receives:

```text
CODEX_RUN_ID
CODEX_RUN_DIR
CODEX_RESULTS_DIR
CODEX_CHECKPOINTS_DIR
CODEX_SOURCE_SHA
CUDA_VISIBLE_DEVICES            # only when --gpus was supplied
```

Repository launchers should write durable artifacts to the results/checkpoints
paths, record their own experiment-specific configuration, avoid overwriting
completed outputs, and support resume by missing group/shard when practical.
The optional completion marker is relative to the frozen worktree, must be
absent before launch and remain absent through bootstrap, must not traverse a
symlink parent, and must finish as a regular non-symlink file. It is checked in
addition to the process exit code.

Job states are `STARTING`, `BOOTSTRAPPING`, `RUNNING`, and `STOP_REQUESTED`
while active; `SUCCEEDED`, `FAILED`, `INCOMPLETE`, `SOURCE_DIRTY`, `STOPPED`, or `ORPHANED`
when terminal. Exit code zero without newly created completion evidence is
`INCOMPLETE`, not success. A command that moves `HEAD` or changes tracked files
relative to the recorded source SHA is `SOURCE_DIRTY`; untracked worktree
artifacts are recorded in the manifest even when the run otherwise succeeds.

### Read-only interpretation

After a job is terminal, `SPC r j i` starts a separate Codex process with
read-only sandboxing and no approvals. It is required to inspect the manifest,
exit status, completion marker, expected groups/rows/shards, malformed or
zero-byte artifacts, metrics and uncertainty, anomalies, and supported versus
unsupported conclusions. A JSON Schema constrains the final result; the runner
also renders it to `analysis.md`. `SPC r j r` displays that Markdown report.
Interpretation cannot repair, relaunch, stop, or delete the run.

### Persistence and reboot behavior

Closing Emacs, suspending the laptop, losing SSH, exiting Codex, importing its
source changes, or archiving the Codex task does not stop a launched experiment.
A server reboot still terminates ordinary processes and `tmux`. On the next
status check, a vanished active process is marked `ORPHANED`; the source
worktree, manifest, logs, checkpoints, results, and recorded resume command are
retained. Automatic restart is intentionally not attempted because safe resume
semantics are experiment-specific.

No automatic experiment-job cleanup is performed. This protects provenance but
means old frozen worktrees and run directories should be reviewed and removed
manually only after their artifacts and source identity are no longer needed.

## State model

Important states include:

- `STARTING`, `BOOTSTRAPPING`, `RUNNING`, `FINALIZING`,
  `REFRESHING_ENVIRONMENT`, `TESTING`: active.
- `READY`: changes and configured tests completed successfully.
- `READY_TESTS_FAILED`: useful changes were preserved, but tests returned
  nonzero.
- `READY_CODEX_FAILED`: Codex returned nonzero after producing changes.
- `READY_TESTS_DIRTY`: tests changed nonignored repository files; the published
  result remains the pre-test Codex result.
- `READY_ENVIRONMENT_FAILED`: `uv.lock` or `flake.lock` changed and the
  post-change bootstrap/environment refresh failed.
- `READY_ENVIRONMENT_DIRTY`: the post-lock-change environment refresh modified
  nonignored repository files.
- `READY_ENVIRONMENT_UNVERIFIED`: a lock file changed but no bootstrap command
  was configured to refresh the server environment.
- `READY_RECOVERED_UNVERIFIED`: `SPC r c r` published an orphaned/failed
  worktree without rerunning Codex, the environment refresh, or server tests.
- `READY_JOB_NOT_LAUNCHED`: Codex requested an experiment, but one of the
  authorization/validation gates prevented launch; the code result remains
  importable and the exact reason is retained.
- `READY_JOB_PREPARED`: a validated request was recorded under the backend's
  non-launching preparation policy. This policy is available to the backend but
  is not bound in the default Doom UI.
- `NOOP`: Codex made no changes; import acknowledges the task. A successful
  frozen job can still have a `NOOP` source task when no code change was needed.
- `CANCELLED_READY` / `CANCELLED_NOOP`: cancellation completed with or without
  changes.
- `BLOCKED_UNSAFE_RESULT`: publication was blocked by the safety filter.
- `ORPHANED`: an active task lost both its runner session and lock, or failed
  during startup. Its worktree and logs are preserved.
- `IMPORTED`: the result was applied locally and acknowledged remotely.
- `ARCHIVED` / `DISCARDED`: the remote worktree, hidden task refs, and retained
  `tmux` session were removed. The terminal status record and logs remain for
  provenance, so status intentionally reports the terminal state rather than
  reverting to `NONE`.

Failed tests or environment refreshes do not discard useful changes. `SPC r c f`
warns before importing a ready failure state so you can inspect or repair the
result locally.

When `uv.lock` or `flake.lock` changes, the runner re-executes the configured
bootstrap command before testing. This lets a command such as `uv sync --frozen`
reconcile the task-specific `.venv`, or lets `nix develop` realize the changed
lock. A failed or source-dirty refresh is recorded distinctly and tests are not
run against that ambiguous environment. Without a bootstrap command, the result
is importable but marked `READY_ENVIRONMENT_UNVERIFIED` rather than `READY`.

## Snapshot and result safety

The two execution modes intentionally use different input and result forms.

### One-shot tasks

A one-shot task creates an exact hidden snapshot with a temporary Git index.
Starting it does not switch branches or modify visible `HEAD`, the real index,
staging organization, or the working tree. The snapshot may include committed
content, staged and unstaged tracked changes, and nonignored safety-checked
untracked source files. The returned result is one sanitized commit whose net
delta is applied locally as ordinary unstaged modifications; internal Codex
scratch commits are not exposed.

### Managed interactive tasks

A managed interactive task requires a clean named branch and uses the branch's
actual `HEAD` as its input. That stable base allows Codex's real commits to be
pulled repeatedly and preserved as commits on the laptop. Starting the task does
not switch the local branch or modify its index or working tree.

A live checkpoint publishes only the server worktree's committed `HEAD`.
Uncommitted edits remain server-side and the status view reports that the
checkpoint is dirty. Every later checkpoint must descend from the last published
commit; an amend, rebase, or reset is blocked instead of silently replacing commits
already pulled to the laptop. Codex is therefore instructed never to rewrite commits
created in the managed session because a laptop pull may publish them at any time. If Codex
exits with safe uncommitted files, the finalizer creates one clearly identifiable
remainder commit as a recovery fallback, but the normal policy is for Codex to
commit each validated logical unit itself.

### Common safety checks

Both modes block or reject:

- merge/rebase/cherry-pick/revert/bisect/git-am operations in progress at unsafe
  boundaries;
- repositories containing submodules in paths the snapshot logic cannot safely
  represent;
- modified Git LFS paths;
- suspicious source or result paths such as live `.env` files, credentials,
  private keys, caches, virtual environments, Nix `result*` links, generated
  outputs, and checkpoints; common placeholder names such as `.env.example`
  remain usable;
- nonregular files, symlinks escaping the repository, and files over the
  configured size limit;
- whitespace/error conditions reported by `git diff --check`.

The result scanner inspects every committed state between the task input and the
published checkpoint/result, not only the final tree. A secret or oversized file
that is committed and later deleted therefore still blocks publication. These
filename and size checks cannot detect a secret copied into an innocently named
source file; do not expose secrets to the task worktree.

## Import and conflicts

### Interactive commit pulls

Let `S` be the interactive task input, `Rₙ` the latest published server
checkpoint, and `Rₙ₋₁` the last checkpoint already pulled. The backend fetches
only the new commit range `Rₙ₋₁..Rₙ`, replays it onto the current local branch in
a temporary integration worktree, and fast-forwards the canonical branch only
after the replay and final state checks succeed. Commit boundaries, messages,
authors, and ordering are retained. A later pull imports only commits that have
not already been integrated. Unmodified Emacs buffers visiting files changed by
the fast-forward are reverted automatically so the editor reflects the new
checkout immediately.

The ordinary `SPC r s`, `SPC r r`, `SPC r R`, setup, smoke, and test commands
perform this checkpoint pull as their preflight. `SPC r c p` performs the same
pull without a subsequent remote action, and `SPC r c f` remains a compatible
manual pull/import command. Exiting the TUI is not required.

When new interactive commits are available, the local index and tracked files
must be clean and the task's expected branch must be checked out. Unrelated
untracked files are preserved unless an incoming commit needs the same path. This
is the boundary that lets the branch advance without flattening Codex's history
or silently mixing local tracked WIP into those commits. If no new commit exists,
a dirty laptop checkout does not block the normal remote action. With an explicit
prefix, `C-u SPC r c f` allows a deliberate pull onto a different current branch;
branch changes are never automatic.

If the replay conflicts, the canonical checkout remains byte-for-byte unchanged.
The backend preserves the rebase in a separate `commit-integration` worktree and
opens it in Magit when available. Resolve the files there, run the normal
`git rebase --continue` sequence in that worktree, then repeat the same
sync/run/test command or `SPC r c p`/`f`. The backend verifies that the local
branch has not changed before fast-forwarding it.

### One-shot delta imports

One-shot tasks keep the previous dirty-snapshot workflow. Let `S` be the exact
hidden input snapshot, `R` the sanitized server result, and `C` a fresh snapshot
of the current local state. The backend replays `S..R` onto `C` in a temporary
worktree and, when clean, applies only the resulting delta to the canonical
working tree without staging or committing it.

A one-shot conflict also leaves the canonical checkout untouched. Doom can open
the isolated integration worktree for manual resolution, preserve current local
development on a timestamped backup branch and retry from the task input, or
abort while retaining all remote and local recovery state. The backup strategy
refuses when it cannot preserve the checkout safely, including an unrelated Git
operation, submodules, unsafe untracked files, changed LFS paths, or an
incompatible branch.

## Recovery

### Server unavailable or authentication failure

Commands use `BatchMode=yes`, a short connection timeout, and one connection
attempt. Fix SSH/DNS/host-key/authentication normally; strict host-key checking
is never disabled. Run `SPC r c d` again.

### Lost start acknowledgement

Task IDs are unique and server submission is idempotent. `SPC r c t` shows the
server task when it started despite a lost SSH reply. If no matching task exists
and local state remains unresolved, `SPC r c X` explicitly discards the stale
state and hidden input ref.

### Lost pull or import acknowledgement

Interactive pulls record both the remote checkpoint SHA and the corresponding
local tip before acknowledging a final task. Repeating the same normal remote
command or `SPC r c p`/`f` therefore imports only genuinely new commits; an
already integrated checkpoint is a no-op. One-shot imports retain the
`APPLIED_PENDING_REMOTE_ACK` marker, so rerunning `SPC r c f` acknowledges the
existing local delta without applying it twice.

### Crash or reboot

For a Codex editing task, `SPC r c t` classifies a vanished active runner as
`ORPHANED`; the worktree, logs, task inputs, frozen helper, and refs are retained.
Use `SPC r c r` to acquire the project lock, safety-check and publish the
preserved worktree without rerunning Codex. The result becomes
`READY_RECOVERED_UNVERIFIED`, and `SPC r c f` warns before import because server
tests were not rerun.

For a frozen experiment, `SPC r j s` marks a vanished active runner/process
`ORPHANED` while preserving its independent worktree and run directory. The
recorded resume command is advisory; relaunch is not automatic. Resume through
the repository's experiment-specific, idempotent mechanism after inspecting
partial outputs and checkpoints.

### Cancellation

`SPC r c x` verifies the runner PID against the server boot ID and Linux process
start time before signalling it. Cancellation preserves useful edits for normal
finalization/import whenever possible. It is not cleanup; use archive/discard
only after the task reaches a terminal state.

### Remote storage layout

Per project, the backend uses:

```text
~/.local/share/codex-remote/repos/<project-id>.git
~/.local/share/codex-remote/worktrees/<project-id>/<task-id>
~/.local/share/codex-remote/job-worktrees/<project-id>/<run-id>
~/.local/state/codex-remote/<project-id>/<task-id>/
~/.local/state/codex-remote/jobs/<project-id>/<run-id>/
~/.local/state/codex-remote/locks/<project-id>.lock
```

Local orchestration metadata and temporary conflict worktrees live under:

```text
~/.local/state/codex-remote/<project-id>/
```

Do not delete these directories while a task or job is active. `SPC r c c` and
`SPC r c X` perform guarded cleanup only for the Codex editing task; they never
remove a frozen experiment. Experiment retention is deliberately explicit and
manual.

## Tests

From the Doom repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s tests -v

python3 -m py_compile \
  bin/codex-remote \
  bin/codex-remote-job \
  tests/test_codex_remote.py \
  tests/test_codex_remote_job.py

git diff --check
```

When Emacs is available, run the ERT frontend tests:

```sh
emacs --batch -Q \
  -l tests/codex-remote-ert.el \
  -f ert-run-tests-batch-and-exit
```

The Python suite currently contains 65 tests. It covers hidden dirty snapshots,
visible Git-state preservation, file modes and symlinks, unsafe-file filtering,
one-shot delta imports, incremental interactive checkpoint publication, history-
rewrite rejection, commit-preserving pulls, repeated pulls, unrelated-untracked-file preservation,
untracked-path collision blocking, isolated commit conflicts, clean/named
interactive start requirements, final interactive commit-
chain publication, trusted live job-request/response brokering, unchanged-input
job launches, one-shot nonblocking job requests, frozen-worktree bootstrap and
preflight tests, source-integrity checks, run manifests and state transitions,
cancellation and recovery, terminal-job configuration and log following,
read-only structured analysis, global `AGENTS.md` managed-block replacement, and
the Doom command-construction/status helpers.

A real acceptance test still requires the actual SSH alias, authenticated server,
kitty, tmux, and Codex account. For an interactive smoke test, start from a clean
disposable branch, have Codex create two commits, pull after each with ordinary
remote bindings, detach and reattach, and verify that both commit messages remain
in local history. Then request a harmless frozen job and confirm that it starts
while the TUI remains usable. For a one-shot smoke test, confirm that importing
still leaves `HEAD` and the index unchanged while applying the result as local
modifications.

## Rollback

The feature is isolated to:

- `bin/codex-remote`
- `bin/codex-remote-job`
- `lisp/codex-remote.el`
- `templates/codex/global-AGENTS.md`
- `templates/codex/research-AGENTS.md`
- the `load!`, keybindings, and popup rule added to `config.el`
- tests and this documentation

Reverting the supplied patch removes the feature without changing
`lisp/remote-dev.el` or any preexisting remote binding. Remote task state is not
automatically deleted when code is reverted; archive or discard active tasks
first, or retain the state directories for manual recovery.
