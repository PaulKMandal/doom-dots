;;; lisp/magit-workflow.el -*- lexical-binding: t; -*-

;; Pull integrates a selected upstream into the checked-out branch.  Expose
;; Magit's repository-wide fetch actions beside it instead of changing pull's
;; branch-local behavior.
(after! magit-pull
  (setq magit-pull-or-fetch t))

(map! :leader
      :desc "Fetch all remotes and prune" "g A"
      #'magit-fetch-all-prune)
