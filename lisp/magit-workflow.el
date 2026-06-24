;;; lisp/magit-workflow.el -*- lexical-binding: t; -*-

;; Pull integrates a selected upstream into the checked-out branch.  Expose
;; Magit's repository-wide fetch actions beside it instead of changing pull's
;; branch-local behavior.
(after! magit-pull
  (setq magit-pull-or-fetch t))

(map! :leader
      :desc "Fetch all remotes and prune" "g A"
      #'magit-fetch-all-prune)

(defun my/magit-set-current-branch-upstream ()
  "Set the upstream branch of the current branch."
  (interactive)
  (require 'magit)
  (let* ((branch (or (magit-get-current-branch)
                     (user-error "No Git branch is checked out")))
         (upstream (magit-read-upstream-branch
                    branch
                    (format "Set upstream of %s" branch))))
    (magit-set-upstream-branch branch upstream)
    (when (derived-mode-p 'magit-mode)
      (magit-refresh))
    (message "Set upstream of %s to %s" branch upstream)))

(map! :leader
      :desc "Set current branch upstream" "g u"
      #'my/magit-set-current-branch-upstream)

(after! magit-branch
  (transient-append-suffix
    'magit-branch "C"
    '("U" "set upstream" my/magit-set-current-branch-upstream)))

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
