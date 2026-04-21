(defvar-local my/remote-host nil)
(defvar-local my/remote-dir nil)
(defvar-local my/remote-run-cmd nil)

(defun my/project-root ()
  (or (when (fboundp 'projectile-project-root)
        (ignore-errors (projectile-project-root)))
      (when-let ((pr (project-current nil)))
        (car (project-roots pr)))
      (user-error "Not inside a project")))

(defun my/remote-check ()
  (unless my/remote-host
    (user-error "Set my/remote-host in .dir-locals.el"))
  (unless my/remote-dir
    (user-error "Set my/remote-dir in .dir-locals.el"))
  (unless my/remote-run-cmd
    (user-error "Set my/remote-run-cmd in .dir-locals.el")))

(defun my/project-sync ()
  (interactive)
  (my/remote-check)
  (let* ((root (file-name-as-directory (expand-file-name (my/project-root))))
         (mkdir-cmd
          (format "ssh %s %s"
                  (shell-quote-argument my/remote-host)
                  (shell-quote-argument
                   (format "mkdir -p %s" my/remote-dir))))
         (rsync-cmd
          (format
           (concat "rsync -az --delete "
                   "--exclude '.git/' "
                   "--exclude '.direnv/' "
                   "--exclude '.venv/' "
                   "--exclude '__pycache__/' "
                   "--exclude '.mypy_cache/' "
                   "--exclude '.pytest_cache/' "
                   "--exclude '.ruff_cache/' "
                   "%s %s:%s")
           (shell-quote-argument root)
           (shell-quote-argument my/remote-host)
           (shell-quote-argument (file-name-as-directory my/remote-dir)))))
    (compile (format "%s && %s" mkdir-cmd rsync-cmd))))

(defun my/project-run-remote ()
  (interactive)
  (my/remote-check)
  (unless my/remote-run-cmd
    (user-error "Set my/remote-run-cmd in .dir-locals.el"))
  (let ((cmd
         (format "ssh %s %s"
                 (shell-quote-argument my/remote-host)
                 (shell-quote-argument
                  (format "cd %s && %s"
                          my/remote-dir
                          my/remote-run-cmd)))))
    (compile cmd)))

(defun my/project-remote-terminal ()
  (interactive)
  (my/remote-check)
  (let ((host my/remote-host)
        (dir  my/remote-dir))
    (unless (and host dir)
      (user-error "Open a file in the project first so .dir-locals.el is applied"))
    (vterm "*remote-vterm*")
    (vterm-send-string
     (format "ssh -t %s 'cd %s; exec bash -l'"
             host dir))
    (vterm-send-return)))
