;;; codex-remote-ert.el --- tests for remote Codex frontend -*- lexical-binding: t; -*-

(require 'ert)
(require 'cl-lib)

(defconst codex-remote-test-root
  (file-name-directory
   (directory-file-name
    (file-name-directory (or load-file-name buffer-file-name)))))
(defvar doom-user-dir (file-name-as-directory codex-remote-test-root))
(load-file (expand-file-name "lisp/codex-remote.el" codex-remote-test-root))

(ert-deftest codex-remote-safe-local-values ()
  (should (my/codex-remote--safe-reasoning "xhigh"))
  (should-not (my/codex-remote--safe-reasoning "extreme"))
  ;; Commands and server paths intentionally require exact-value approval.
  (should-not (get 'my/codex-remote-bootstrap-cmd 'safe-local-variable))
  (should-not (get 'my/codex-remote-test-cmd 'safe-local-variable))
  (should-not (get 'my/codex-remote-data-links 'safe-local-variable))
  (should-not (get 'my/codex-remote-model 'safe-local-variable))
  (should-not (get 'my/codex-remote-profile 'safe-local-variable)))

(ert-deftest codex-remote-common-arguments-preserve-project-context ()
  (let ((my/codex-remote-backend "/tmp/codex-remote")
        (context '(:root "/tmp/project/"
                   :host "rhel-test"
                   :remote-dir "/home/rhel/Projects/project"
                   :timeout 5
                   :max-untracked 4096)))
    (should
     (equal
      (my/codex-remote--common-args "status" context)
      '("/tmp/codex-remote" "status"
        "--project-root" "/tmp/project/"
        "--host" "rhel-test"
        "--remote-dir" "/home/rhel/Projects/project"
        "--timeout" "5"
        "--max-untracked-bytes" "4096")))))

(ert-deftest codex-remote-start-command-adds-project-options ()
  (let ((my/codex-remote-backend "/tmp/codex-remote")
        (context '(:root "/tmp/project/"
                   :host "rhel-test"
                   :remote-dir "/srv/project"
                   :timeout 5
                   :max-untracked 2048
                   :bootstrap "nix develop --command true"
                   :test "nix develop --command pytest"
                   :data-links ("/srv/data=data")
                   :model "gpt-test"
                   :profile "server"
                   :reasoning "high"
                   :search t)))
    (let ((command (my/codex-remote--start-command context)))
      (should (equal (seq-take command 2) '("/tmp/codex-remote" "start")))
      (should (member "--prompt-file" command))
      (should (member "--bootstrap-cmd" command))
      (should (member "--test-cmd" command))
      (should (member "/srv/data=data" command))
      (should (member "gpt-test" command))
      (should (member "server" command))
      (should (member "high" command))
      (should (member "--enable-search" command)))))

(ert-deftest codex-remote-json-parsing-and-key-access ()
  (with-temp-buffer
    (insert "diagnostic before JSON\n")
    (insert "{\"ok\":true,\"task\":{\"state\":\"READY\"}}\n")
    (insert "diagnostic after JSON\n")
    (let* ((response (my/codex-remote--parse-buffer (current-buffer)))
           (task (my/codex-remote--get response 'task)))
      (should (my/codex-remote--get response 'ok))
      (should (equal (my/codex-remote--get task 'state) "READY")))))

(ert-deftest codex-remote-status-lines-include-result-and-tests ()
  (let* ((task '((state . "READY_TESTS_FAILED")
                 (task_id . "task-1")
                 (project_name . "paper")
                 (result_sha . "abc123")
                 (tests . ((command . "pytest") (exit_code . 1)))))
         (text (string-join (my/codex-remote--task-lines task) "\n")))
    (should (string-match-p "READY_TESTS_FAILED" text))
    (should (string-match-p "task-1" text))
    (should (string-match-p "abc123" text))
    (should (string-match-p "pytest" text))))

(provide 'codex-remote-ert)
;;; codex-remote-ert.el ends here
