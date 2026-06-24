;;; lisp/magit-workflow.el -*- lexical-binding: t; -*-

;; Pull integrates a selected upstream into the checked-out branch.  Expose
;; Magit's repository-wide fetch actions beside it instead of changing pull's
;; branch-local behavior.
(after! magit-pull
  (setq magit-pull-or-fetch t))

(map! :leader
      :desc "Fetch all remotes and prune" "g A"
      #'magit-fetch-all-prune)

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
