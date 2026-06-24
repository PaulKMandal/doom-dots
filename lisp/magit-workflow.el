;;; lisp/magit-workflow.el -*- lexical-binding: t; -*-

;; Pull integrates a selected upstream into the checked-out branch.  Expose
;; Magit's repository-wide fetch actions beside it instead of changing pull's
;; branch-local behavior.
(after! magit-pull
  (setq magit-pull-or-fetch t))

(map! :leader
      :desc "Fetch all remotes and prune" "g A"
      #'magit-fetch-all-prune)

(defun my/magit--remote-branches-at-head ()
  "Return remote branches whose tip is the current HEAD."
  (seq-remove
   (lambda (branch)
     (string-suffix-p "/HEAD" branch))
   (magit-git-lines
    "for-each-ref"
    "--format=%(refname:short)"
    "--points-at=HEAD"
    "refs/remotes")))

(defun my/magit--read-remote-branch-for-detached-head ()
  "Read the remote branch that a detached HEAD should track."
  (let* ((branches
          (seq-remove
           (lambda (branch)
             (string-suffix-p "/HEAD" branch))
           (magit-list-remote-branch-names)))
         (at-head (seq-filter (lambda (branch)
                                (member branch branches))
                              (my/magit--remote-branches-at-head)))
         (default (car at-head)))
    (unless branches
      (user-error "No remote branches are available; fetch first"))
    (magit-completing-read
     "Remote branch to track"
     branches nil t nil 'magit-revision-history default)))

(defun my/magit-attach-detached-head ()
  "Create a local branch at detached HEAD and set its remote upstream.

This preserves commits and working-tree changes made while HEAD was detached."
  (interactive)
  (require 'magit-branch)
  (when (magit-get-current-branch)
    (user-error "A local branch is already checked out"))
  (let* ((upstream (my/magit--read-remote-branch-for-detached-head))
         (parts (magit-split-branch-name upstream))
         (remote (car parts))
         (branch (cdr parts)))
    (when (magit-branch-p branch)
      (user-error "Local branch %s already exists; use b b and select it"
                  branch))
    (magit-call-git "checkout" "-b" branch)
    (magit-set-upstream-branch branch upstream)
    (unless (equal remote (magit-get "remote.pushDefault"))
      (magit-set remote "branch" branch "pushRemote"))
    (magit-refresh)
    (message "Created %s at HEAD; tracking %s" branch upstream)))

(defun my/magit-set-current-branch-upstream ()
  "Set the current branch upstream, or attach a detached HEAD first."
  (interactive)
  (require 'magit-branch)
  (let ((branch (magit-get-current-branch)))
    (if branch
        (let ((upstream (magit-read-upstream-branch
                         branch
                         (format "Set upstream of %s" branch))))
          (magit-set-upstream-branch branch upstream)
          (when (derived-mode-p 'magit-mode)
            (magit-refresh))
          (message "Set upstream of %s to %s" branch upstream))
      (call-interactively #'my/magit-attach-detached-head))))

(map! :leader
      :desc "Set or repair current branch upstream" "g u"
      #'my/magit-set-current-branch-upstream)

(after! magit-branch
  ;; The stock `b b' command treats a remote branch as an arbitrary revision
  ;; and detaches HEAD.  Use Magit's branch-aware checkout instead: selecting
  ;; a remote branch creates a same-named local branch and configures tracking.
  (transient-replace-suffix
    'magit-branch 'magit-checkout
    '("b" "switch local/tracking branch" magit-branch-checkout))
  (transient-append-suffix
    'magit-branch "C"
    '("U" "set/repair upstream" my/magit-set-current-branch-upstream)))

(defun my/magit-publish-current-branch (args)
  "Push the current branch to a same-named branch and set its upstream."
  (interactive
   (progn
     (require 'magit-push)
     (list (magit-push-arguments))))
  (require 'magit-push)
  (let* ((branch (or (magit-get-current-branch)
                     (user-error "No Git branch is checked out")))
         (remote (magit-read-remote
                  (format "Publish %s to remote" branch))))
    (run-hooks 'magit-credential-hook)
    (magit-run-git-async
     "push" "-v" args "--set-upstream" remote
     (format "refs/heads/%s:refs/heads/%s" branch branch))))

(map! :leader
      :desc "Publish current Git branch" "g P"
      #'my/magit-publish-current-branch)

(after! magit-push
  (transient-append-suffix
    'magit-push "p"
    '("U" "publish and set upstream" my/magit-publish-current-branch)))
