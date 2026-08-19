;;; lisp/remote-dev.el -*- lexical-binding: t; -*-

(require 'seq)
(require 'subr-x)

(defvar-local my/remote-host nil
  "SSH host used by the project remote helpers.")

(defvar-local my/remote-dir nil
  "Directory on the remote host where the project is synced/run.")

(defvar-local my/remote-run-cmd nil
  "Main remote command for this project.")

(defvar-local my/remote-setup-cmd nil
  "Optional remote command for environment setup or dependency sync.")

(defvar-local my/remote-test-cmd nil
  "Optional remote command for tests.")

(defvar-local my/remote-smoke-cmd nil
  "Optional remote command for a quick smoke/integration run.")

(defvar-local my/remote-sync-excludes nil
  "Rsync exclude patterns for this project.

Entries are rsync pattern strings passed as --exclude PATTERN.
Set this in .dir-locals.el.  Nil means no excludes.")

;; Directory-local values for these variables are expected in projects that use
;; the remote helpers.  Mark them safe by shape so Emacs does not repeatedly
;; prompt for every project-specific host/path/command string.
(defun my/remote--safe-string (value)
  "Return non-nil when VALUE is a single-line string."
  (and (stringp value)
       (not (string-match-p "[\n\r]" value))))

(put 'my/remote-host 'safe-local-variable #'my/remote--safe-string)
(put 'my/remote-dir 'safe-local-variable #'my/remote--safe-string)
(put 'my/remote-run-cmd 'safe-local-variable #'my/remote--safe-string)
(put 'my/remote-setup-cmd 'safe-local-variable #'my/remote--safe-string)
(put 'my/remote-test-cmd 'safe-local-variable #'my/remote--safe-string)
(put 'my/remote-smoke-cmd 'safe-local-variable #'my/remote--safe-string)
(put 'my/remote-sync-excludes
     'safe-local-variable
     (lambda (value) (and (listp value) (seq-every-p #'my/remote--safe-string value))))


(defun my/project-root ()
  (or (when (fboundp 'projectile-project-root)
        (ignore-errors (projectile-project-root)))
      (when-let ((pr (project-current nil)))
        (car (project-roots pr)))
      (user-error "Not inside a project")))

(defun my/remote-check (&optional require-run-cmd)
  (unless my/remote-host
    (user-error "Set my/remote-host in .dir-locals.el"))
  (unless my/remote-dir
    (user-error "Set my/remote-dir in .dir-locals.el"))
  (when (and require-run-cmd (not my/remote-run-cmd))
    (user-error "Set my/remote-run-cmd in .dir-locals.el")))

(defun my/remote--shell-join (parts)
  "Join non-nil shell command PARTS with &&."
  (string-join (seq-filter #'identity parts) " && "))

(defun my/remote--exclude-args ()
  "Return rsync --exclude arguments from `my/remote-sync-excludes'."
  (mapconcat (lambda (pattern)
               (format "--exclude %s" (shell-quote-argument pattern)))
             my/remote-sync-excludes
             " "))

(defun my/remote--ssh-command (remote-command)
  (format "ssh %s %s"
          (shell-quote-argument my/remote-host)
          (shell-quote-argument remote-command)))

(defun my/remote--cd-command (command)
  (format "cd %s && %s"
          (shell-quote-argument my/remote-dir)
          command))

(defun my/remote--sync-command ()
  "Return the existing rsync command for the current project."
  (let* ((root (file-name-as-directory (expand-file-name (my/project-root))))
         (mkdir-cmd
          (my/remote--ssh-command
           (format "mkdir -p %s" (shell-quote-argument my/remote-dir))))
         (rsync-cmd
          (format
           "rsync -az --delete %s %s %s:%s"
           (my/remote--exclude-args)
           (shell-quote-argument root)
           (shell-quote-argument my/remote-host)
           (shell-quote-argument (file-name-as-directory my/remote-dir)))))
    (my/remote--shell-join (list mkdir-cmd rsync-cmd))))

(defun my/remote--run-command (command)
  "Return the SSH command that runs COMMAND in the normal remote checkout."
  (my/remote--ssh-command (my/remote--cd-command command)))

(defun my/remote--compile (command &optional buffer-name)
  "Compile COMMAND, optionally naming its compilation buffer BUFFER-NAME."
  (let ((compilation-buffer-name-function
         (when buffer-name
           (lambda (_mode) buffer-name))))
    (compile command)))

(defun my/remote--codex-pulled-commits-p (response)
  "Return non-nil when Codex refresh RESPONSE imported at least one commit."
  (and response
       (fboundp 'my/codex-remote--get)
       (> (or (my/codex-remote--get response 'changed_commit_count) 0) 0)))

(defun my/remote--refresh-then (continuation)
  "Pull committed interactive Codex updates, then call CONTINUATION.

CONTINUATION receives the backend response.  Without the Codex integration,
run it immediately with nil so this module remains independently usable."
  (if (fboundp 'my/codex-remote-refresh-then)
      (my/codex-remote-refresh-then continuation)
    (funcall continuation nil)))

(defun my/remote--run-after-refresh
    (remote-command buffer-name &optional always-sync)
  "Run REMOTE-COMMAND after the live Codex refresh.

When ALWAYS-SYNC is non-nil, preserve the existing uppercase sync+action
semantics.  For lowercase commands, sync only when the refresh pulled new
Codex commits; otherwise preserve the original no-sync behavior."
  (let ((sync-command (my/remote--sync-command))
        (run-command (my/remote--run-command remote-command)))
    (my/remote--refresh-then
     (lambda (response)
       (my/remote--compile
        (if (or always-sync
                (my/remote--codex-pulled-commits-p response))
            (my/remote--shell-join (list sync-command run-command))
          run-command)
        buffer-name)))))

(defun my/project-sync ()
  "Pull committed Codex checkpoints, then rsync the local project remotely."
  (interactive)
  (my/remote-check)
  (let ((sync-command (my/remote--sync-command)))
    (my/remote--refresh-then
     (lambda (_response)
       (my/remote--compile sync-command)))))

(defun my/project-run-remote-command (command &optional buffer-name)
  "Run COMMAND in `my/remote-dir' on `my/remote-host'.

This low-level helper does not perform a Codex refresh; the user-facing remote
commands below do so before invoking it."
  (interactive "sRemote command: ")
  (my/remote-check)
  (my/remote--compile (my/remote--run-command command) buffer-name))

(defun my/project-remote-setup ()
  "Refresh Codex commits, then run `my/remote-setup-cmd' remotely."
  (interactive)
  (my/remote-check)
  (unless my/remote-setup-cmd
    (user-error "Set my/remote-setup-cmd in .dir-locals.el"))
  (my/remote--run-after-refresh my/remote-setup-cmd "*remote-setup*"))

(defun my/project-test-remote ()
  "Refresh Codex commits, then run `my/remote-test-cmd' remotely."
  (interactive)
  (my/remote-check)
  (unless my/remote-test-cmd
    (user-error "Set my/remote-test-cmd in .dir-locals.el"))
  (my/remote--run-after-refresh my/remote-test-cmd "*remote-test*"))

(defun my/project-smoke-remote ()
  "Refresh Codex commits, then run `my/remote-smoke-cmd' remotely."
  (interactive)
  (my/remote-check)
  (unless my/remote-smoke-cmd
    (user-error "Set my/remote-smoke-cmd in .dir-locals.el"))
  (my/remote--run-after-refresh my/remote-smoke-cmd "*remote-smoke*"))

(defun my/project-run-remote ()
  "Refresh Codex commits, then run `my/remote-run-cmd' remotely."
  (interactive)
  (my/remote-check t)
  (my/remote--run-after-refresh my/remote-run-cmd "*remote-run*"))

(defun my/project-sync-and-setup ()
  "Refresh Codex commits, sync, then run `my/remote-setup-cmd'."
  (interactive)
  (my/remote-check)
  (unless my/remote-setup-cmd
    (user-error "Set my/remote-setup-cmd in .dir-locals.el"))
  (my/remote--run-after-refresh my/remote-setup-cmd "*remote-setup*" t))

(defun my/project-sync-and-smoke ()
  "Refresh Codex commits, sync, then run `my/remote-smoke-cmd'."
  (interactive)
  (my/remote-check)
  (unless my/remote-smoke-cmd
    (user-error "Set my/remote-smoke-cmd in .dir-locals.el"))
  (my/remote--run-after-refresh my/remote-smoke-cmd "*remote-smoke*" t))

(defun my/project-sync-and-run ()
  "Refresh Codex commits, sync, then run `my/remote-run-cmd'."
  (interactive)
  (my/remote-check t)
  (my/remote--run-after-refresh my/remote-run-cmd "*remote-run*" t))

(defun my/project-remote-terminal ()
  (interactive)
  (my/remote-check)
  (let ((host my/remote-host)
        (dir  my/remote-dir))
    (unless (and host dir)
      (user-error "Open a file in the project first so .dir-locals.el is applied"))
    (vterm "*remote-vterm*")
    (vterm-send-string
     (format "ssh -t %s %s"
             (shell-quote-argument host)
             (shell-quote-argument
              (format "cd %s; exec bash -l"
                      (shell-quote-argument dir)))))
    (vterm-send-return)))
