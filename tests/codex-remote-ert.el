;;; codex-remote-ert.el --- tests for remote Codex frontend -*- lexical-binding: t; -*-

(require 'ert)
(require 'cl-lib)

(defconst codex-remote-test-root
  (file-name-directory
   (directory-file-name
    (file-name-directory (or load-file-name buffer-file-name)))))
(defvar doom-user-dir (file-name-as-directory codex-remote-test-root))
(load-file (expand-file-name "lisp/remote-dev.el" codex-remote-test-root))
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

(ert-deftest codex-remote-pull-command-preserves-project-context ()
  (let ((my/codex-remote-backend "/tmp/codex-remote")
        (context '(:root "/tmp/project/"
                   :host "rhel-test"
                   :remote-dir "/srv/project"
                   :timeout 5
                   :max-untracked 2048)))
    (should
     (equal
      (my/codex-remote--common-args "pull" context)
      '("/tmp/codex-remote" "pull"
        "--project-root" "/tmp/project/"
        "--host" "rhel-test"
        "--remote-dir" "/srv/project"
        "--timeout" "5"
        "--max-untracked-bytes" "2048")))))

(ert-deftest codex-remote-refreshes-unmodified-project-buffers-after-pull ()
  (let* ((root (make-temp-file "codex-remote-buffer-" t))
         (file (expand-file-name "tracked.txt" root))
         buffer)
    (unwind-protect
        (progn
          (with-temp-file file (insert "before\n"))
          (setq buffer (find-file-noselect file))
          (with-temp-file file (insert "after\n"))
          ;; Ensure the visited-file timestamp cannot compare equal on a
          ;; low-resolution filesystem.
          (set-file-times file (time-add (current-time) 2))
          (my/codex-remote--refresh-project-buffers root)
          (with-current-buffer buffer
            (should (equal (buffer-string) "after\n"))
            (should-not (buffer-modified-p))))
      (when (buffer-live-p buffer)
        (kill-buffer buffer))
      (delete-directory root t))))

(ert-deftest codex-remote-interactive-entry-authorizes-frozen-jobs ()
  (let (seen)
    (cl-letf (((symbol-function 'my/codex-remote--interactive-with-policy)
               (lambda (policy) (setq seen policy))))
      (my/codex-remote-interactive))
    (should (equal seen "launch"))))

(ert-deftest remote-dev-lowercase-action-syncs-only-after-live-commit-pull ()
  (let (compiled)
    (cl-letf (((symbol-function 'my/remote--sync-command) (lambda () "SYNC"))
              ((symbol-function 'my/remote--run-command) (lambda (_command) "RUN"))
              ((symbol-function 'my/remote--compile)
               (lambda (command &optional _buffer) (setq compiled command)))
              ((symbol-function 'my/remote--refresh-then)
               (lambda (continuation)
                 (funcall continuation '((changed_commit_count . 2))))))
      (my/remote--run-after-refresh "pytest" "*test*")
      (should (equal compiled "SYNC && RUN")))
    (setq compiled nil)
    (cl-letf (((symbol-function 'my/remote--sync-command) (lambda () "SYNC"))
              ((symbol-function 'my/remote--run-command) (lambda (_command) "RUN"))
              ((symbol-function 'my/remote--compile)
               (lambda (command &optional _buffer) (setq compiled command)))
              ((symbol-function 'my/remote--refresh-then)
               (lambda (continuation)
                 (funcall continuation '((changed_commit_count . 0))))))
      (my/remote--run-after-refresh "pytest" "*test*")
      (should (equal compiled "RUN")))))


(ert-deftest codex-remote-automatic-refresh-defers-dirty-checkpoint-pull ()
  (let ((process-buffer (generate-new-buffer " *codex-dirty-pull-test*"))
        continued
        displayed)
    (unwind-protect
        (cl-letf (((symbol-function 'my/codex-remote--common-args)
                   (lambda (_action _context) '("codex-remote" "pull")))
                  ((symbol-function 'my/codex-remote--display-raw-error)
                   (lambda (&rest _args) (setq displayed t)))
                  ((symbol-function 'my/codex-remote--run)
                   (lambda (_action _command _context &rest options)
                     (funcall
                      (plist-get options :on-error)
                      '((ok . nil)
                        (error_code . "LOCAL_DIRTY_FOR_COMMIT_PULL")
                        (error . "tracked edits are still in progress"))
                      process-buffer))))
          (my/codex-remote--run-pull
           '(:root "/tmp/project/")
           :quiet t
           :continuation (lambda (response) (setq continued response))))
      (when (buffer-live-p process-buffer)
        (kill-buffer process-buffer)))
    (should-not displayed)
    (should continued)
    (should (equal (my/codex-remote--get continued 'changed_commit_count) 0))
    (should (my/codex-remote--get continued 'pull_deferred))
    (should-not (buffer-live-p process-buffer))))

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
                   :search t
                   :job-policy "deny")))
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
                 (model . "gpt-5.6-sol")
                 (reasoning_effort . "xhigh")
                 (approval_policy . "never")
                 (network_access . t)
                 (data_links . (((source . "/home/rhel/Data/MalLogic")
                                  (target . "data"))))
                 (result_sha . "abc123")
                 (tests . ((command . "pytest") (exit_code . 1)))))
         (text (string-join (my/codex-remote--task-lines task) "\n")))
    (should (string-match-p "READY_TESTS_FAILED" text))
    (should (string-match-p "Mode:[[:space:]]+exec" text))
    (should (string-match-p "task-1" text))
    (should (string-match-p "gpt-5\\.6-sol" text))
    (should (string-match-p "xhigh" text))
    (should (string-match-p "never" text))
    (should (string-match-p "enabled in sandbox" text))
    (should (string-match-p "data -> /home/rhel/Data/MalLogic" text))
    (should (string-match-p "abc123" text))
    (should (string-match-p "pytest" text))))

(ert-deftest codex-remote-launch-policy-is-forwarded-only-for-explicit-task-modes ()
  (let* ((my/codex-remote-backend "/tmp/codex-remote")
         (context '(:root "/tmp/project/"
                    :host "rhel-test"
                    :remote-dir "/srv/project"
                    :timeout 5
                    :max-untracked 2048
                    :job-policy "launch"))
         (start (my/codex-remote--start-command context))
         (interactive (my/codex-remote--interactive-command context)))
    (dolist (command (list start interactive))
      (let ((position (seq-position command "--job-policy" #'equal)))
        (should position)
        (should (equal (nth (1+ position) command) "launch"))))))

(ert-deftest codex-remote-frozen-job-command-preserves-run-id ()
  (let ((my/codex-remote-backend "/tmp/codex-remote")
        (context '(:root "/tmp/project/"
                   :host "rhel-test"
                   :remote-dir "/srv/project"
                   :timeout 5
                   :max-untracked 2048)))
    (should
     (equal
      (my/codex-job--command "job-status" context "run-123")
      '("/tmp/codex-remote" "job-status"
        "--project-root" "/tmp/project/"
        "--host" "rhel-test"
        "--remote-dir" "/srv/project"
        "--timeout" "5"
        "--max-untracked-bytes" "2048"
        "--run-id" "run-123")))))

(ert-deftest codex-remote-frozen-job-lines-show-source-command-and-analysis ()
  (let ((text
         (string-join
          (my/codex-job--lines
           '((state . "SUCCEEDED")
             (phase . "finished")
             (run_id . "run-123")
             (name . "heldout transfer")
             (source_sha . "abc123")
             (source_task_id . "task-1")
             (gpus . "0,1")
             (command . ("python" "run.py" "--tag" "heldout"))
             (bootstrap_cmd . "uv sync --frozen")
             (bootstrap . ((exit_code . 0)))
             (completion_marker . "outputs/COMPLETE")
             (completion_marker_present . t)
             (analysis . ((state . "SUCCEEDED")))))
          "\n")))
    (should (string-match-p "SUCCEEDED" text))
    (should (string-match-p "run-123" text))
    (should (string-match-p "abc123" text))
    (should (string-match-p "python run\\.py --tag heldout" text))
    (should (string-match-p "uv sync --frozen" text))
    (should (string-match-p "Bootstrap exit:.*0" text))
    (should (string-match-p "outputs/COMPLETE" text))))

(provide 'codex-remote-ert)
;;; codex-remote-ert.el ends here
