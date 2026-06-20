;;; $DOOMDIR/config.el -*- lexical-binding: t; -*-

;; Place your private configuration here! Remember, you do not need to run 'doom
;; sync' after modifying this file!


;; Some functionality uses this to identify you, e.g. GPG configuration, email
;; clients, file templates and snippets. It is optional.
;; (setq user-full-name "John Doe"
;;       user-mail-address "john@doe.com")

;; Doom exposes five (optional) variables for controlling fonts in Doom:
;;
;; - `doom-font' -- the primary font to use
;; - `doom-variable-pitch-font' -- a non-monospace font (where applicable)
;; - `doom-big-font' -- used for `doom-big-font-mode'; use this for
;;   presentations or streaming.
;; - `doom-symbol-font' -- for symbols
;; - `doom-serif-font' -- for the `fixed-pitch-serif' face
;;
;; See 'C-h v doom-font' for documentation and more examples of what they
;; accept. For example:
;;
;;(setq doom-font (font-spec :family "Fira Code" :size 12 :weight 'semi-light)
;;      doom-variable-pitch-font (font-spec :family "Fira Sans" :size 13))
;;
;; If you or Emacs can't find your font, use 'M-x describe-font' to look them
;; up, `M-x eval-region' to execute elisp code, and 'M-x doom/reload-font' to
;; refresh your font settings. If Emacs still can't find your font, it likely
;; wasn't installed correctly. Font issues are rarely Doom issues!

;; There are two ways to load a theme. Both assume the theme is installed and
;; available. You can either set `doom-theme' or manually load a theme with the
;; `load-theme' function. This is the default:
(setq doom-theme 'doom-one)

;; This determines the style of line numbers in effect. If set to `nil', line
;; numbers are disabled. For relative line numbers, set this to `relative'.
(setq display-line-numbers-type t)

;; If you use `org' and don't want your org files in the default location below,
;; change `org-directory'. It must be set before org loads!
(setq org-directory "~/org/")

(setq +latex-viewers '(pdf-tools))

(load! "lisp/remote-dev")

(map! :leader
      (:prefix ("r" . "remote")
       :desc "Sync project to remote"       "s" #'my/project-sync
       :desc "Setup/update remote env"      "u" #'my/project-remote-setup
       :desc "Run remote tests"             "T" #'my/project-test-remote
       :desc "Run remote smoke test"        "q" #'my/project-smoke-remote
       :desc "Run project remotely"         "r" #'my/project-run-remote
       :desc "Sync + setup remote env"      "U" #'my/project-sync-and-setup
       :desc "Sync + smoke test remotely"   "Q" #'my/project-sync-and-smoke
       :desc "Sync + run project remotely"  "R" #'my/project-sync-and-run
       :desc "Open vterm"                   "t" #'my/project-remote-terminal))

(set-popup-rule! "^\\*remote-vterm\\*$"
  :side 'bottom
  :size 0.3
  :select t
  :quit nil)

(load! "lisp/latex-build")

;; Whenever you reconfigure a package, make sure to wrap your config in an
;; `with-eval-after-load' block, otherwise Doom's defaults may override your
;; settings. E.g.
;;
;;   (with-eval-after-load 'PACKAGE
;;     (setq x y))
;;
;; The exceptions to this rule:
;;
;;   - Setting file/directory variables (like `org-directory')
;;   - Setting variables which explicitly tell you to set them before their
;;     package is loaded (see 'C-h v VARIABLE' to look them up).
;;   - Setting doom variables (which start with 'doom-' or '+').
;;
(after! (treemacs evil)
  (require 'treemacs-evil)

  ;; stop Evil from eating the press
  (define-key evil-treemacs-state-map [down-mouse-1] nil)
  (define-key evil-treemacs-state-map [double-down-mouse-1] nil)

  ;; give Treemacs the actual click events
  (define-key evil-treemacs-state-map [mouse-1] #'treemacs-leftclick-action)
  (define-key evil-treemacs-state-map [double-mouse-1] #'treemacs-doubleclick-action))

(defconst my/project-create-choice "[Create new project]")

(defun my/project-open-treemacs ()
  "Show the current project in Treemacs without prompting for a file."
  (interactive)
  (let ((project-window (selected-window))
        (default-directory
         (file-name-as-directory
          (or (ignore-errors (projectile-project-root))
              default-directory))))
    (require 'treemacs)
    (treemacs-add-and-display-current-project-exclusively)
    (when (window-live-p project-window)
      (select-window project-window))))

(defun my/project--read-directory ()
  "Read the directory to use for a new project."
  (let ((base (if (file-directory-p "~/Documents/")
                  "~/Documents/"
                "~/")))
    (file-name-as-directory
     (expand-file-name
      (read-directory-name "Create/use project directory: " base nil nil)))))

(defun my/project--known-projects ()
  "Return Projectile's known projects as directory names."
  (let ((projects (if (fboundp 'projectile-relevant-known-projects)
                      (projectile-relevant-known-projects)
                    projectile-known-projects))
        result)
    (dolist (project projects (nreverse result))
      (when (and project (not (string= project "")))
        (push (file-name-as-directory project) result)))))

(defun my/project-create (&optional directory)
  "Create DIRECTORY as a Projectile project and show it in Treemacs."
  (interactive)
  (require 'projectile)
  (let* ((dir (file-name-as-directory
               (expand-file-name
                (or directory (my/project--read-directory)))))
         (marker (expand-file-name ".projectile" dir)))
    (make-directory dir t)
    (unless (or (file-exists-p marker)
                (file-directory-p (expand-file-name ".git" dir)))
      (with-temp-file marker
        (insert "# Projectile project marker.\n")))
    (projectile-add-known-project dir)
    (dired dir)
    (my/project-open-treemacs)
    (message "Projectile project ready: %s" (abbreviate-file-name dir))))

(defun my/project-switch-or-create ()
  "Switch Projectile projects, with a fallback to create/register one."
  (interactive)
  (require 'projectile)
  (let ((projects (my/project--known-projects)))
    (if projects
        (let ((choice (completing-read
                       "Project: "
                       (cons my/project-create-choice projects)
                       nil nil nil 'projectile-project-history)))
          (cond
           ((string= choice my/project-create-choice)
            (my/project-create))
           ((member choice projects)
            (projectile-switch-project-by-name choice))
           ((string= choice "")
            (user-error "No project selected"))
           ((y-or-n-p (format "Create/register project at %s? " choice))
            (my/project-create choice))
           (t
            (user-error "No project selected"))))
      (when (y-or-n-p "No known Projectile projects. Create one? ")
        (my/project-create)))))

(defun my/project-find-file ()
  "Find a file in the current Projectile project, then show Treemacs."
  (interactive)
  (require 'projectile)
  (call-interactively #'projectile-find-file)
  (when (buffer-file-name)
    (my/project-open-treemacs)))

(after! projectile
  (setq projectile-switch-project-action #'my/project-open-treemacs)
  (map! :leader
        :desc "Find project file"     "p ." #'my/project-find-file
        :desc "Switch/create project" "p p" #'my/project-switch-or-create
        :desc "Create project"        "p n" #'my/project-create))

(map! "C-c t" #'treemacs-add-and-display-current-project-exclusively)

;; Here are some additional functions/macros that will help you configure Doom.
;;
;; - `load!' for loading external *.el files relative to this one
;; - `add-load-path!' for adding directories to the `load-path', relative to
;;   this file. Emacs searches the `load-path' when you load packages with
;;   `require' or `use-package'.
;; - `map!' for binding new keys
;;
;; To get information about any of these functions/macros, move the cursor over
;; the highlighted symbol at press 'K' (non-evil users must press 'C-c c k').
;; This will open documentation for it, including demos of how they are used.
;; Alternatively, use `C-h o' to look up a symbol (functions, variables, faces,
;; etc).
;;
;; You can also try 'gd' (or 'C-c c d') to jump to their definition and see how
;; they are implemented.
