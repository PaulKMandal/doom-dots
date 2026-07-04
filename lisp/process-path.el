;;; lisp/process-path.el -*- lexical-binding: t; -*-

(require 'cl-lib)
(require 'subr-x)

(defun my/process-path--split (path)
  "Split PATH using `path-separator', ignoring empty entries."
  (when (and path (not (string-empty-p path)))
    (split-string path path-separator t)))

(defun my/process-path--dedupe-existing (paths)
  "Return PATHS without duplicates, keeping only existing directories."
  (let (seen result)
    (dolist (path paths (nreverse result))
      (when (and path (stringp path))
        (let ((path (directory-file-name (expand-file-name path))))
          (when (and (file-directory-p path)
                     (not (member path seen)))
            (push path seen)
            (push path result)))))))

(defun my/process-path--nix-profile-dirs ()
  "Return common NixOS profile bin directories."
  (list (expand-file-name "~/.nix-profile/bin")
        (format "/etc/profiles/per-user/%s/bin" (user-login-name))
        "/run/current-system/sw/bin"
        "/nix/var/nix/profiles/default/bin"
        "/usr/local/bin"
        "/usr/bin"
        "/bin"))

(defun my/process-path--find-executable (program)
  "Find PROGRAM after refreshing common Nix profile paths."
  (or (executable-find program)
      (cl-some (lambda (dir)
                 (let ((candidate (expand-file-name program dir)))
                   (and (file-executable-p candidate) candidate)))
               (my/process-path--nix-profile-dirs))))

(defun my/process-path--configure-git-ssh ()
  "Give Git an absolute ssh executable when one is available."
  (unless (or (getenv "GIT_SSH")
              (getenv "GIT_SSH_COMMAND"))
    (when-let ((ssh (my/process-path--find-executable "ssh")))
      (setenv "GIT_SSH" ssh)
      (with-eval-after-load 'magit
        (add-to-list 'magit-git-environment (concat "GIT_SSH=" ssh))))))

(defun my/process-path-setup ()
  "Synchronize `exec-path' and PATH for GUI Emacs on NixOS.

Doom's captured environment can miss profile binaries when Emacs is launched
from a desktop session.  Git can still find `git' while failing later when Git
spawns `ssh'.  Add common Nix profile directories to both Emacs's exec-path and
process PATH, then configure Git's ssh helper by absolute path when possible."
  (let* ((keep-nil (memq nil exec-path))
         (paths (my/process-path--dedupe-existing
                 (append (my/process-path--nix-profile-dirs)
                         (my/process-path--split (getenv "PATH"))
                         (cl-remove-if #'null exec-path)))))
    (setq exec-path (append paths (and keep-nil (list nil))))
    (setenv "PATH" (mapconcat #'identity paths path-separator))
    (my/process-path--configure-git-ssh)))

(defun my/process-path-diagnose ()
  "Display the Git/SSH executables visible to this Emacs process."
  (interactive)
  (message "git=%s ssh=%s GIT_SSH=%s PATH=%s"
           (or (executable-find "git") "missing")
           (or (executable-find "ssh") "missing")
           (or (getenv "GIT_SSH") "unset")
           (or (getenv "PATH") "unset")))

(provide 'process-path)
