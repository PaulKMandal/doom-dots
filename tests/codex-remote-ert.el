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

(ert-deftest codex-remote-interactive-command-adds-project-options-without-prompt ()
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
    (let ((command (my/codex-remote--interactive-command context)))
      (should (equal (seq-take command 2)
                     '("/tmp/codex-remote" "interactive")))
      (should-not (member "--prompt-file" command))
      (should (member "--bootstrap-cmd" command))
      (should (member "--test-cmd" command))
      (should (member "/srv/data=data" command))
      (should (member "gpt-test" command))
      (should (member "server" command))
      (should (member "high" command))
      (should (member "--enable-search" command)))))

(ert-deftest codex-remote-interactive-action-starts-attaches-or-blocks ()
  (should
   (eq (my/codex-remote--interactive-action
        '((state . "RUNNING") (execution_mode . "interactive")))
       'attach))
  (dolist (state '("NONE" "IMPORTED" "DISCARDED" "ARCHIVED"))
    (should
     (eq (my/codex-remote--interactive-action
          `((state . ,state) (execution_mode . "interactive")))
         'start)))
  (should
   (eq (my/codex-remote--interactive-action
        '((state . "RUNNING") (execution_mode . "exec")))
       'blocked))
  (should
   (eq (my/codex-remote--interactive-action
        '((state . "READY") (execution_mode . "interactive")))
       'blocked))
  (should
   (eq (my/codex-remote--interactive-action
        '((state . "FINALIZING") (execution_mode . "interactive")))
       'blocked)))

(ert-deftest codex-remote-json-parsing-and-key-access ()
  (with-temp-buffer
    (insert "diagnostic before JSON\n")
    (insert "{\"ok\":true,\"task\":{\"state\":\"READY\"}}\n")
    (insert "diagnostic after JSON\n")
    (let* ((response (my/codex-remote--parse-buffer (current-buffer)))
           (task (my/codex-remote--get response 'task)))
      (should (my/codex-remote--get response 'ok))
      (should (equal (my/codex-remote--get task 'state) "READY")))))

(ert-deftest codex-remote-command-output-falls-back-from-empty-stdout ()
  (should
   (equal
    (my/codex-remote--command-output
     '((stdout . "") (stderr . "Logged in using ChatGPT"))
     "(authenticated)")
    "Logged in using ChatGPT")))

(ert-deftest codex-remote-tmux-status-distinguishes-session-from-process ()
  (should
   (equal
    (my/codex-remote--tmux-status-label
     '((exists . t) (running . nil) (pane_dead . t) (pane_dead_status . 2)))
    "exited (status 2)"))
  (should
   (equal
    (my/codex-remote--tmux-status-label
     '((exists . t) (running . t) (pane_dead . nil)))
    "running"))
  (should
   (equal
    (my/codex-remote--tmux-status-label
     '((exists . nil) (running . nil)))
    "absent")))

(ert-deftest codex-remote-tmux-monitor-command-is-read-only-and-bounded ()
  (let ((args
         (my/codex-remote--tmux-monitor-args
          '(:host "rhel-test" :timeout 5)
          '((tmux_session . "codex-session")))))
    (should
     (equal
      args
      '("-tt"
        "-o" "BatchMode=yes"
        "-o" "ConnectTimeout=5"
        "-o" "ConnectionAttempts=1"
        "rhel-test"
        "env" "TERM=xterm-256color"
        "tmux" "attach-session" "-r" "-t" "codex-session")))))

(ert-deftest codex-remote-tmux-interactive-command-is-read-write-and-bounded ()
  (let ((args
         (my/codex-remote--tmux-interactive-args
          '(:host "rhel-test" :timeout 5)
          '((tmux_session . "codex-session")))))
    (should
     (equal
      args
      '("-tt"
        "-o" "BatchMode=yes"
        "-o" "ConnectTimeout=5"
        "-o" "ConnectionAttempts=1"
        "rhel-test"
        "env" "TERM=xterm-256color"
        "tmux" "attach-session" "-t" "codex-session")))
    (should-not (member "-r" args))))

(ert-deftest codex-remote-external-terminal-command-wraps-interactive-ssh ()
  (let ((my/codex-remote-external-terminal-command
         '("kitty" "--title" "Remote Codex")))
    (cl-letf (((symbol-function 'my/codex-remote--external-terminal-executable)
               (lambda () "/run/current-system/sw/bin/kitty"))
              ((symbol-function 'my/codex-remote--ssh-executable)
               (lambda () "/run/current-system/sw/bin/ssh")))
      (should
       (equal
        (my/codex-remote--external-terminal-command
         '(:host "rhel-test" :timeout 5)
         '((tmux_session . "codex-session")))
        '("/run/current-system/sw/bin/kitty"
          "--title" "Remote Codex"
          "/run/current-system/sw/bin/ssh"
          "-tt"
          "-o" "BatchMode=yes"
          "-o" "ConnectTimeout=5"
          "-o" "ConnectionAttempts=1"
          "rhel-test"
          "env" "TERM=xterm-256color"
          "tmux" "attach-session" "-t" "codex-session"))))))


(ert-deftest codex-remote-terminal-job-command-preserves-project-options ()
  (let ((my/codex-remote-backend "/tmp/codex-remote")
        (my/codex-remote-job-program "/tmp/codex-remote-job")
        (my/codex-remote-job-terminal-command
         '("kitty" "--title" "Remote Codex Job"))
        (context '(:root "/tmp/project/"
                   :host "rhel-test"
                   :remote-dir "/srv/project"
                   :timeout 5
                   :max-untracked 2048
                   :bootstrap "nix develop --command true"
                   :test "pytest -q"
                   :data-links ("/srv/data=data")
                   :model "gpt-test"
                   :profile "server"
                   :reasoning "high"
                   :search t)))
    (cl-letf (((symbol-function 'my/codex-remote--job-terminal-executable)
               (lambda () "/run/current-system/sw/bin/kitty"))
              ((symbol-function 'my/codex-remote--job-executable)
               (lambda () "/tmp/codex-remote-job")))
      (should
       (equal
        (my/codex-remote--job-command context)
        '("/run/current-system/sw/bin/kitty"
          "--title" "Remote Codex Job"
          "/tmp/codex-remote-job"
          "--project-root" "/tmp/project/"
          "--backend" "/tmp/codex-remote"
          "--host" "rhel-test"
          "--remote-dir" "/srv/project"
          "--timeout" "5"
          "--max-untracked-bytes" "2048"
          "--bootstrap-cmd" "nix develop --command true"
          "--test-cmd" "pytest -q"
          "--data-link" "/srv/data=data"
          "--model" "gpt-test"
          "--profile" "server"
          "--reasoning-effort" "high"
          "--enable-search"
          "--ignore-config"
          "--pause-at-end"))))))

(ert-deftest codex-remote-attach-refuses-dead-pane-before-opening-terminal ()
  (should-error
   (my/codex-remote--open-tmux
    '(:host "rhel-test" :timeout 5)
    '((state . "FAILED")
      (task_id . "task-1")
      (tmux_session . "codex-session")
      (tmux . ((exists . t) (running . nil)
               (pane_dead . t) (pane_dead_status . 2)))))
   :type 'user-error))

(ert-deftest codex-remote-status-lines-include-result-and-tests ()
  (let* ((task '((state . "READY_TESTS_FAILED")
                 (task_id . "task-1")
                 (project_name . "paper")
                 (result_sha . "abc123")
                 (tests . ((command . "pytest") (exit_code . 1)))))
         (text (string-join (my/codex-remote--task-lines task) "\n")))
    (should (string-match-p "READY_TESTS_FAILED" text))
    (should (string-match-p "Mode:[[:space:]]+exec" text))
    (should (string-match-p "task-1" text))
    (should (string-match-p "abc123" text))
    (should (string-match-p "pytest" text))))

(provide 'codex-remote-ert)
;;; codex-remote-ert.el ends here
