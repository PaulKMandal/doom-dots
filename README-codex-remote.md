# Durable remote Codex from Doom Emacs

This configuration adds a hidden Git transport and an isolated server worktree
for Codex while leaving the existing rsync/SSH experiment workflow intact.
The laptop checkout remains canonical: Codex receives an exact hidden snapshot,
runs on the server under `tmux`, and returns only its additional changes as
ordinary unstaged local modifications.

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

The new commands are under `SPC r c`:

| Binding | Action |
| --- | --- |
| `SPC r c d` | check local/server prerequisites and Codex authentication |
| `SPC r c s` | start a remote Codex task |
| `SPC r c t` | show task and local orchestration status |
| `SPC r c a` | monitor a live task in a read-only built-in Term buffer |
| `SPC r c i` | open a read-write attachment in an external kitty window |
| `SPC r c l` | show runner, Codex, test, and final-message logs |
| `SPC r c f` | fetch, integrate, and apply the completed Codex delta locally |
| `SPC r c x` | request cancellation while preserving the worktree |
| `SPC r c c` | archive an already-imported task and remove remote worktree/refs |
| `SPC r c X` | explicitly discard a task and its unimported work |

With a region active, `SPC r c s` sends the region as the prompt. With a prefix
argument (`C-u SPC r c s`), it opens a multiline prompt buffer; submit with
`C-c C-c` or cancel with `C-c C-k`.

`SPC r c a` shows the durable noninteractive run through Emacs's built-in
Term emulator and attaches to `tmux` read-only. It does not depend on the
native `vterm` module. The monitor is available only while the runner pane is
live; after exit, use `SPC r c l` for preserved logs. Use `SPC r c x` to cancel
an active task rather than sending input through the monitor.

`SPC r c i` opens a separate kitty OS window and attaches read-write to the
same server-side tmux session. Closing that window, detaching with `C-b d`, or
losing the SSH connection does not stop the task; run `SPC r c i` again to
reattach. This is an interactive terminal/tmux attachment to the durable
`codex exec` run, not a separate conversational Codex TUI. Input can interrupt
the runner, so use the read-only `SPC r c a` monitor when observation alone is
intended.

## Requirements

### Laptop

- Git
- OpenSSH client
- Python 3.10 or newer
- kitty (the configured external terminal for `SPC r c i`)
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

Apply the patch series from the root of the Doom configuration repository, then
ensure the backend is executable and reload Doom:

```sh
chmod +x bin/codex-remote

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
- `my/codex-remote-model`: optional model override.
- `my/codex-remote-profile`: optional server-side Codex profile.
- `my/codex-remote-reasoning-effort`: `minimal`, `low`, `medium`, `high`, or
  `xhigh`.
- `my/codex-remote-enable-search`: non-nil enables live Codex web search.
- `my/codex-remote-timeout`: short SSH connection timeout, default 5 seconds.
- `my/codex-remote-max-untracked-bytes`: per-file transfer limit, default
  20 MiB.

`my/codex-remote-external-terminal-command` is a global customization rather
than a project-local setting. Its default value is
`("kitty" "--title" "Remote Codex")`; the frontend appends the resolved SSH
executable and tmux attachment arguments.

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

Place stable project instructions in a checked-in `AGENTS.md`, including:

- the Nix/uv setup and test commands Codex should use;
- generated-file policy;
- experiment constraints;
- paths Codex must not modify;
- whether large data is read-only and how it should be accessed.

## Normal workflow

1. Edit the local checkout normally. Staged, unstaged, and safe untracked source
   files may all be present.
2. Run `SPC r c d` once for the project/server combination.
3. Run `SPC r c s` and provide the task prompt.
4. Continue local work or disconnect/suspend the laptop. The server-side
   `tmux` process continues.
5. Inspect `SPC r c t` or `SPC r c l`, monitor read-only with `SPC r c a`, or
   open the external read-write tmux attachment with `SPC r c i` as needed.
6. When the state is importable, run `SPC r c f`.
7. Review the resulting ordinary local changes in Emacs or Magit.
8. Use `SPC r s` then `SPC r r`, or `SPC r R`, to run the reconciled local
   state in the normal experiment checkout.
9. After a successful import, `SPC r c c` may archive the server worktree.
   Archive/discard removes the retained `tmux` session, worktree, and hidden
   refs while keeping task metadata and logs. Starting the next task also
   archives the prior imported task automatically.

After ordinary `SPC r s`, a nonblocking status probe notifies you when a
completed Codex result is still waiting to be imported. It does not change or
block the existing rsync command and does not import automatically.

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
- `NOOP`: Codex made no changes; import acknowledges the task.
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
can import the ready failure states so you can inspect or repair them locally.

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

On a conflict, the error buffer reports the integration path and Doom opens it
in Magit when available. Version 1 deliberately does not automate the final
conflict resolution. Inspect the worktree, decide which edits should survive,
then either apply the desired resolution manually to the canonical checkout and
explicitly discard the task, or discard the preserved integration worktree,
reconcile the local conflicting lines, and retry the import.

The import is branch-aware. If the checked-out branch differs from the branch
on which the task started, import stops. `C-u SPC r c f` deliberately overrides
that check and applies the Codex delta to the current branch.

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

`SPC r c t` classifies a vanished active runner as `ORPHANED`; the worktree,
logs, prompt, frozen helper, and refs are retained. Inspect with logs/status.
Use explicit discard only after deciding the work is no longer needed.

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
~/.local/state/codex-remote/<project-id>/<task-id>/
~/.local/state/codex-remote/locks/<project-id>.lock
```

Local orchestration metadata and temporary conflict worktrees live under:

```text
~/.local/state/codex-remote/<project-id>/
```

Do not delete these directories while a task is active. `SPC r c c` and
`SPC r c X` perform guarded cleanup.

## Tests

From the Doom repository root:

```sh
PYTHONDONTWRITEBYTECODE=1 \
  python3 -m unittest discover -s tests -v

python3 -m py_compile bin/codex-remote tests/test_codex_remote.py

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
true-conflict isolation, result publication, cancellation during bootstrap,
lock-file-triggered environment refresh, configured tests, and Codex command
construction.

A real acceptance test still requires your actual SSH alias and authenticated
server. Use a disposable project change first, verify the remote paths printed
by `SPC r c d`, disconnect while the task runs, and confirm that import leaves
`HEAD` and the index unchanged.

## Rollback

The feature is isolated to:

- `bin/codex-remote`
- `lisp/codex-remote.el`
- the `load!`, keybindings, and popup rule added to `config.el`
- tests and this documentation

Reverting the patch series removes the feature without changing
`lisp/remote-dev.el` or any preexisting remote binding. Remote task state is not
automatically deleted when code is reverted; archive or discard active tasks
first, or retain the state directories for manual recovery.
