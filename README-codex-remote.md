# Durable remote Codex from Doom Emacs

This configuration adds a hidden Git transport and an isolated server worktree
for Codex while leaving the existing rsync/SSH experiment workflow intact.
The laptop checkout remains canonical: Codex receives an exact hidden snapshot,
runs on the server under `tmux`, and returns only its additional changes as
ordinary unstaged local modifications.

It also adds a separate frozen experiment-job layer. An explicitly authorized
Codex task may submit one structured launch request, but Codex cannot detach the
process itself. The trusted runner validates the request, requires the configured
smoke/test command to pass, freezes the exact result revision into a dedicated
worktree, and launches a job that is independent of both Emacs and the Codex
session.

## Behavior preserved from the existing configuration

The existing bindings retain their current meanings:

| Binding | Existing behavior |
| --- | --- |
| `SPC r s` | rsync the local project to the normal server checkout |
| `SPC r r` | run the configured command in the already-synced server checkout |
| `SPC r R` | sync, then run the configured command |
| `SPC r u` / `U` | setup remotely / sync then setup |
| `SPC r q` / `Q` | smoke test remotely / sync then smoke test |
| `SPC r T` | run the configured remote tests |
| `SPC r t` | open a vterm in the normal server checkout |

In particular, lowercase `SPC r r` does **not** sync first. After importing a
Codex result, use `SPC r s` followed by `SPC r r`, or use `SPC r R`.

The Codex worktree is never placed in `my/remote-dir`, so the existing
`rsync --delete` operation cannot erase unfinished Codex work.

## Added bindings

### Codex editing commands

The Codex commands are under `SPC r c`:

| Binding | Action |
| --- | --- |
| `SPC r c d` | check local/server prerequisites and Codex authentication |
| `SPC r c s` | start an ordinary managed noninteractive `codex exec` task |
| `SPC r c S` | start Codex with authorization to request one frozen experiment job |
| `SPC r c t` | show task and local orchestration status |
| `SPC r c a` | monitor a live Codex task in a read-only built-in Term buffer |
| `SPC r c i` | start or reattach to an ordinary managed interactive Codex TUI in kitty |
| `SPC r c I` | start or reattach to interactive Codex with one frozen job authorized |
| `SPC r c j` | open the ordinary one-shot Codex prompt/watcher in kitty |
| `SPC r c l` | show preserved task, Codex, environment, and test logs |
| `SPC r c r` | safely publish a preserved orphaned/failed worktree without rerunning Codex |
| `SPC r c f` | fetch, integrate, and apply the completed Codex delta locally |
| `SPC r c x` | request Codex-task cancellation while preserving its worktree |
| `SPC r c c` | archive an already-imported task and remove its worktree/refs |
| `SPC r c X` | explicitly discard a task and its unimported work |
| `SPC r c g` | install/update the managed global `~/.codex/AGENTS.md` block on the server |
| `SPC r c A` | create from the research template, or open, the project `AGENTS.md` |

Lowercase `s` and `i` never authorize a detached or long-running launch. Uppercase
`S` and `I` authorize exactly one runner-mediated request for the new task. An
already-running interactive task retains the policy with which it started;
reattaching with `I` does not upgrade an ordinary task.

With a region active, `SPC r c s` or `SPC r c S` sends the region as the prompt.
With a prefix argument, either command opens a multiline prompt buffer; submit
with `C-c C-c` or cancel with `C-c C-k`.

`SPC r c s` is the ordinary one-shot mode: it sends a task prompt to
noninteractive `codex exec`, then the runner finalizes and publishes the result
automatically. `SPC r c S` uses the same editing and import path but additionally
allows Codex to create one structured experiment request through
`"$CODEX_JOBCTL"`. The runner—not Codex—decides whether the authorization,
source, environment, and smoke-test gates permit launch.

`SPC r c j` starts the same ordinary one-shot editing mode from an external
terminal. It intentionally has no frozen-job authorization. The terminal accepts
a multiline prompt until `Ctrl-D`, submits it through the same `codex-remote
start` backend, and watches the durable task's status and logs. Closing the
watcher or pressing `Ctrl-C` after launch does not cancel the server-side Codex
task. Import its completed code changes with `SPC r c f`.

`SPC r c i` is the ordinary conversational mode. If the project has no
outstanding task, it creates the same hidden snapshot and isolated server
worktree as `SPC r c s`, launches the Codex TUI under durable remote `tmux`, and
opens it in kitty. New interactive sessions use GPT-5.6 Sol at extra-high
reasoning and run without approval pauses inside a `workspace-write` sandbox.
The extra-high setting is enforced for this managed interactive path even when
an older project `.dir-locals.el` still requests `high`.
Outbound public-network access is enabled inside that sandbox for project
dependency resolution, while loopback, private-network destinations, and Unix
sockets remain blocked except for the standard Nix daemon socket. A task-private
cache is exposed for Nix/uv/Python tooling. The agent may edit the worktree and
its dependency lock files, but the sandbox does not grant write access to host
or system files. Project-specific model and reasoning settings still override
the defaults.

Run `SPC r c i` again to reattach. Closing kitty, detaching with `C-b d`, losing
SSH, or suspending the laptop detaches only the client. Because approvals are
set to `never`, an operation outside the sandbox fails rather than waiting for
you; reattach to inspect any genuine blocker. Exit the TUI with `/exit` or
`/quit`; the enclosing runner then finalizes, validates, and publishes the
worktree. `SPC r c I` behaves identically but permits one runner-mediated
experiment request.

`SPC r c a` is a read-only monitor for either task mode through Emacs's built-in
Term emulator. After the pane exits, use `SPC r c l` for preserved logs. Use
`SPC r c x` for cancellation rather than sending control input through the
read-only monitor.

The `s`, `S`, `j`, `i`, and `I` entry points share the same
one-outstanding-Codex-task-per-project rule. A task must be imported, archived,
or explicitly discarded before another can start. Frozen experiment jobs are
separate objects and may continue after their source Codex task is imported or
archived.

For one-shot tasks, `SPC r c l` includes the structured Codex event stream,
stderr, final message, runner log, and test logs. For interactive tasks it
preserves runner, environment-refresh, and test logs, but not a complete terminal
transcript.

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

Both modes begin from an exact hidden snapshot of the canonical laptop checkout
and use the same isolated server worktree, result publication, import, conflict,
and cleanup machinery.

### One-shot task

1. Edit the local checkout normally. Staged, unstaged, and safe untracked source
   files may all be present.
2. Run `SPC r c d` once for the project/server combination.
3. Run `SPC r c s` and provide the task prompt.
4. Continue local work or disconnect/suspend the laptop. The server-side
   `tmux` process continues.
5. Inspect `SPC r c t` or `SPC r c l`; use `SPC r c a` for a read-only live
   monitor.
6. When the state is importable, run `SPC r c f`.

### Terminal one-shot job

From Doom, run `SPC r c j`. Kitty opens, asks for a multiline prompt, and
submits on `Ctrl-D`. It then follows state changes and runner/Codex/test logs.
Closing the window or pressing `Ctrl-C` after launch detaches only the watcher;
the tmux-backed server task continues.

The same frontend can be run directly from a laptop terminal inside the local
canonical repository:

```sh
~/.config/doom/bin/codex-remote-job
```

Resume watching the current one-shot task without submitting another prompt:

```sh
~/.config/doom/bin/codex-remote-job --watch
```

Use `--prompt-file task.txt` for a prepared prompt. The terminal frontend does
not import results; after it reports `READY` or another importable state, return
to Doom and run `SPC r c f`.

### Interactive TUI session

1. From the project, run `SPC r c i`.
2. Doom saves project buffers, creates the managed hidden snapshot/worktree,
   starts the ordinary Codex TUI under remote `tmux`, and opens kitty attached
   read-write to that session.
3. Use Codex normally. Closing kitty or detaching with `C-b d` leaves the TUI
   running; run `SPC r c i` again to reattach to the same task.
4. When the interactive coding session is complete, use `/exit` or `/quit`.
   The enclosing runner resumes, finalizes the worktree, refreshes the
   environment when required, runs configured tests, and publishes the result.
5. Check `SPC r c t` or `SPC r c l`, then run `SPC r c f` when the state is
   importable.

### After either mode

1. Review the resulting ordinary local changes in Emacs or Magit.
2. Use `SPC r s` then `SPC r r`, or `SPC r R`, to run the reconciled local
   state in the normal experiment checkout.
3. After a successful import, `SPC r c c` may archive the server worktree.
   Archive/discard removes the retained `tmux` session, worktree, and hidden
   refs while keeping task metadata and logs. Starting the next task also
   archives the prior imported task automatically.

After ordinary `SPC r s`, a nonblocking status probe notifies you when a
completed Codex result is still waiting to be imported. It does not change or
block the existing rsync command and does not import automatically.

## Frozen experiment jobs

### Launch protocol

Use `SPC r c S` for a one-shot implementation-and-launch task or `SPC r c I`
for an interactive session. Describe both the code/validation work and the
intended experiment in the prompt. Once the implementation is ready, Codex may
make exactly one request using the helper exposed in its environment:

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

After Codex exits, the trusted runner:

1. consumes and removes the request file so it cannot enter the returned source
   tree;
2. safety-checks and publishes a single sanitized result revision;
3. refreshes the server environment when a supported lock file changed;
4. runs the configured bounded test/smoke command against that exact result;
5. refuses launch unless Codex, environment validation, and tests all succeeded
   without dirtying nonignored source files;
6. creates a pinned hidden source ref and a dedicated detached worktree;
7. records the run manifest and starts a separate `tmux` runner;
8. recreates the configured bootstrap environment inside that fresh frozen
   worktree before exposing data links or starting the experiment command.

Codex is explicitly instructed not to use `tmux`, `nohup`, shell backgrounding,
`systemd`, or a scheduler directly. Ordinary lowercase task modes reject even a
manually created request. The uppercase command is therefore a meaningful
resource-authorization boundary, not a different prompt label.

The experiment command itself runs as the ordinary remote user rather than
inside the Codex editing sandbox. This is necessary for the repository's real
environment, datasets, and GPUs, but it also means `SPC r c S` and
`SPC r c I` should be used only for a trusted repository and a reviewed task
description on a nonprivileged server account. The runner validates provenance
and launch gates; it is not a container or a semantic malware detector for the
requested program.

The code result and experiment lifecycle are independent after launch. Import
and review the source changes with `SPC r c f`; archiving that Codex task does
not stop or delete its experiment job. The job executes from the frozen result
SHA, so subsequent Codex or local edits cannot alter the source under the run.

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

The local snapshot uses a temporary Git index and hidden ref. Starting a task
does not switch branches or modify the visible `HEAD`, real index, staging
organization, or working tree. The snapshot includes:

- committed content;
- staged changes;
- unstaged tracked changes;
- nonignored, safety-checked untracked source files.

Version 1 blocks:

- merge/rebase/cherry-pick/revert/bisect/git-am operations in progress;
- repositories containing submodules;
- modified Git LFS paths;
- suspicious untracked or result paths such as live `.env` files,
  credentials, private keys, caches, virtual environments, Nix `result*`
  links, generated outputs, and checkpoints; common placeholder names such as
  `.env.example` remain usable;
- nonregular untracked files;
- symlinks escaping the repository;
- files over the configured size limit.

The same checks inspect every committed state in the Codex history, not only the
final tree. A secret or oversized file that Codex commits and later deletes is
therefore still blocked. For an accepted result, the backend publishes a single
sanitized commit from the exact input snapshot to the final tree; Codex's
intermediate commit chain is not fetched back to the laptop.

These filename/size checks cannot detect a secret copied into an innocently
named source file; do not expose secrets to the task worktree.

## Import and conflicts

Let `S` be the exact input snapshot, `R` the server result, and `C` a fresh
snapshot of the current local state at import time. The backend replays `S..R`
onto `C` inside a temporary local worktree. It verifies that the canonical
checkout did not change during integration, then applies only `C..M` to the
canonical working tree without staging or committing it.

Expected behavior:

- different files: automatic import;
- same file, nonoverlapping regions: normally automatic import;
- incompatible edits: conflict preserved in the temporary integration
  worktree; the canonical checkout remains unchanged.

On a conflict, Doom prompts for one of three actions:

1. **Resolve in the isolated integration worktree.** The canonical checkout
   remains untouched. Resolve the files in the Magit worktree, complete the
   rebase, and rerun `SPC r c f`; the backend verifies the recorded local base
   before importing the resolved result.
2. **Preserve current local development on a timestamped branch and retry.**
   The backend creates `<branch>-local-<UTC timestamp>` containing all local
   commits plus a synthetic WIP commit for the exact current tree. Doom asks
   whether to push that branch to `origin`; when push is requested, the
   original branch is not reset unless the push succeeds. The original branch
   is then restored to the exact task-start `HEAD`, index, and working-tree
   snapshot before the normal Codex import runs.
3. **Abort.** The canonical checkout and remote result remain unchanged.

The local-backup strategy refuses when it cannot preserve the checkout safely,
including a different current branch, a Git operation in progress, submodules,
unsafe untracked files, or changed LFS paths. Recovery metadata is retained in
`local-backup.json` under the local project state directory.

The import is branch-aware. If the checked-out branch differs from the branch
on which the task started, Doom prompts before applying to the current branch;
it never switches branches automatically. `C-u SPC r c f` deliberately skips
that prompt. The timestamped-backup strategy is available only on the original
task-start branch.

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

### Lost import acknowledgement

The local result is recorded as `APPLIED_PENDING_REMOTE_ACK` before remote
acknowledgement. Re-run `SPC r c f`; it acknowledges the existing local import
without applying the patch twice.

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

The Python tests cover hidden dirty snapshots, visible Git-state preservation,
file modes and symlinks, unsafe-file filtering and template-name handling,
intermediate committed-result inspection, nonoverlapping same-file integration,
true-conflict isolation and resolved-conflict continuation, timestamped local
backup branches with exact task-input reconstruction, result publication,
cancellation during bootstrap, lock-file-triggered environment refresh,
configured tests, noninteractive and interactive Codex command construction,
managed interactive task reuse/finalization, orphaned-worktree publication,
terminal-job configuration and log following, refusal to import a live
interactive session, structured job-request validation and authorization,
mandatory prelaunch tests, frozen-worktree environment bootstrapping, fast-job
startup races, frozen-source manifests and execution, task/job separation,
read-only structured analysis commands, global `AGENTS.md` managed
block replacement, and the new Doom command construction/status renderers.

A real acceptance test still requires your actual SSH alias and authenticated
server. Use a disposable project change first, verify the remote paths printed
by `SPC r c d`, disconnect while the task runs, and confirm that import leaves
`HEAD` and the index unchanged.

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
