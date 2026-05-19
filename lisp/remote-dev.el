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
  "Extra rsync excludes for this project.  Entries are rsync pattern strings.")

(defvar my/remote-default-sync-excludes
  '(".git/"
    ".direnv/"
    ".venv/"
    "__pycache__/"
    ".mypy_cache/"
    ".pytest_cache/"
    ".ruff_cache/"
    ".cache/"
    "wandb/"
    "results/"
    "outputs/"
    "checkpoint-*/"
    "*.pyc"
    "*.pt"
    "*.bin"
    "*.safetensors")
  "Default files/directories excluded when syncing a project to a remote host.")

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

(defun my/remote--excludes ()
  (append my/remote-default-sync-excludes my/remote-sync-excludes))

(defun my/remote--exclude-args ()
  (mapconcat (lambda (pattern)
               (format "--exclude %s" (shell-quote-argument pattern)))
             (my/remote--excludes)
             " "))

(defun my/remote--ssh-command (remote-command)
  (format "ssh %s %s"
          (shell-quote-argument my/remote-host)
          (shell-quote-argument remote-command)))

(defun my/remote--cd-command (command)
  (format "cd %s && %s"
          (shell-quote-argument my/remote-dir)
          command))

(defun my/project-sync ()
  "Rsync the current project to `my/remote-host':`my/remote-dir'."
  (interactive)
  (my/remote-check)
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
    (compile (my/remote--shell-join (list mkdir-cmd rsync-cmd)))))

(defun my/project-run-remote-command (command &optional buffer-name)
  "Run COMMAND in `my/remote-dir' on `my/remote-host'."
  (interactive "sRemote command: ")
  (my/remote-check)
  (let ((compilation-buffer-name-function
         (when buffer-name
           (lambda (_mode) buffer-name))))
    (compile
     (my/remote--ssh-command
      (my/remote--cd-command command)))))

(defun my/project-remote-setup ()
  "Run `my/remote-setup-cmd' on the remote project."
  (interactive)
  (my/remote-check)
  (unless my/remote-setup-cmd
    (user-error "Set my/remote-setup-cmd in .dir-locals.el"))
  (my/project-run-remote-command my/remote-setup-cmd "*remote-setup*"))

(defun my/project-test-remote ()
  "Run `my/remote-test-cmd' on the remote project."
  (interactive)
  (my/remote-check)
  (unless my/remote-test-cmd
    (user-error "Set my/remote-test-cmd in .dir-locals.el"))
  (my/project-run-remote-command my/remote-test-cmd "*remote-test*"))

(defun my/project-smoke-remote ()
  "Run `my/remote-smoke-cmd' on the remote project."
  (interactive)
  (my/remote-check)
  (unless my/remote-smoke-cmd
    (user-error "Set my/remote-smoke-cmd in .dir-locals.el"))
  (my/project-run-remote-command my/remote-smoke-cmd "*remote-smoke*"))

(defun my/project-run-remote ()
  "Run `my/remote-run-cmd' on the remote project."
  (interactive)
  (my/remote-check t)
  (my/project-run-remote-command my/remote-run-cmd "*remote-run*"))

(defun my/project-sync-and-setup ()
  "Sync the project and then run `my/remote-setup-cmd'."
  (interactive)
  (my/remote-check)
  (unless my/remote-setup-cmd
    (user-error "Set my/remote-setup-cmd in .dir-locals.el"))
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
           (shell-quote-argument (file-name-as-directory my/remote-dir))))
         (run-cmd
          (my/remote--ssh-command
           (my/remote--cd-command my/remote-setup-cmd))))
    (compile (my/remote--shell-join (list mkdir-cmd rsync-cmd run-cmd)))))

(defun my/project-sync-and-smoke ()
  "Sync the project and then run `my/remote-smoke-cmd'."
  (interactive)
  (my/remote-check)
  (unless my/remote-smoke-cmd
    (user-error "Set my/remote-smoke-cmd in .dir-locals.el"))
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
           (shell-quote-argument (file-name-as-directory my/remote-dir))))
         (run-cmd
          (my/remote--ssh-command
           (my/remote--cd-command my/remote-smoke-cmd))))
    (compile (my/remote--shell-join (list mkdir-cmd rsync-cmd run-cmd)))))

(defun my/project-sync-and-run ()
  "Sync the project and then run `my/remote-run-cmd'."
  (interactive)
  (my/remote-check t)
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
           (shell-quote-argument (file-name-as-directory my/remote-dir))))
         (run-cmd
          (my/remote--ssh-command
           (my/remote--cd-command my/remote-run-cmd))))
    (compile (my/remote--shell-join (list mkdir-cmd rsync-cmd run-cmd)))))

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
