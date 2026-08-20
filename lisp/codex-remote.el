;;; lisp/codex-remote.el -*- lexical-binding: t; -*-

(require 'cl-lib)
(require 'json)
(require 'seq)
(require 'subr-x)

(declare-function make-term "term" (name program &optional startfile &rest switches))
(declare-function term-char-mode "term" ())
(declare-function term-check-proc "term" (buffer))

(defgroup my/codex-remote nil
  "Run durable Codex tasks on a configured remote project host."
  :group 'tools)

(defcustom my/codex-remote-backend
  (expand-file-name "bin/codex-remote" doom-user-dir)
  "Path to the local codex-remote backend."
  :type 'file)

(defcustom my/codex-remote-external-terminal-command
  '("kitty" "--title" "Remote Codex")
  "Command prefix used for an external interactive Codex terminal.

The first element is the terminal executable.  The local SSH executable and
the read-write tmux attachment arguments are appended to this list.  The
default opens a separate kitty OS window, matching the configured Sway
terminal."
  :type '(repeat string))

(defcustom my/codex-remote-job-program
  (expand-file-name "bin/codex-remote-job" doom-user-dir)
  "Path to the terminal frontend for managed one-shot Codex jobs."
  :type 'file)

(defcustom my/codex-remote-job-terminal-command
  '("kitty" "--title" "Remote Codex Job")
  "Command prefix used for the external one-shot Codex job terminal.

The `codex-remote-job' executable and the current project's resolved options
are appended to this list."
  :type '(repeat string))

(defcustom my/codex-remote-research-agents-template
  (expand-file-name "templates/codex/research-AGENTS.md" doom-user-dir)
  "Template used when creating a repository-level research AGENTS.md."
  :type 'file)

(defvar-local my/codex-remote-bootstrap-cmd nil
  "Optional command used to prepare a new Codex worktree.

When nil, `my/remote-setup-cmd' is used.  The command runs once before Codex and
must leave all nonignored repository files unchanged.")

(defvar-local my/codex-remote-test-cmd nil
  "Optional command run after Codex finishes.

When nil, `my/remote-test-cmd' is used.")

(defvar-local my/codex-remote-data-links nil
  "Persistent remote data links exposed inside the isolated Codex worktree.

Each entry has the form REMOTE-ABSOLUTE-PATH=WORKTREE-RELATIVE-PATH.  The
backend creates temporary symlinks, excludes them from the result commit, and
verifies that Codex did not replace them.  Directory-valued sources are also
given to Codex as explicit writable roots, so downloads written through the
worktree-relative path persist outside the ephemeral task worktree.")

(defvar-local my/codex-remote-model nil
  "Optional Codex model override for this project.")

(defvar-local my/codex-remote-profile nil
  "Optional server-side Codex profile name for this project.")

(defvar-local my/codex-remote-reasoning-effort nil
  "Optional Codex reasoning effort: minimal, low, medium, high, or xhigh.")

(defvar-local my/codex-remote-enable-search nil
  "When non-nil, enable live Codex web search for remote tasks.")

(defvar-local my/codex-remote-timeout 5
  "Short SSH connection timeout used by the Codex backend.")

(defvar-local my/codex-remote-max-untracked-bytes (* 20 1024 1024)
  "Largest nonignored untracked file included in a hidden snapshot.")

(defun my/codex-remote--safe-reasoning (value)
  "Return non-nil when VALUE is nil or a supported reasoning effort."
  (or (null value)
      (member value '("minimal" "low" "medium" "high" "xhigh"))))

;; Do not globally mark shell commands, data-link paths, models, or profiles as
;; safe directory-local values.  Emacs should prompt for each exact project
;; value so opening an untrusted repository cannot silently authorize remote
;; commands or expose arbitrary server paths.
(put 'my/codex-remote-reasoning-effort 'safe-local-variable
     #'my/codex-remote--safe-reasoning)
(put 'my/codex-remote-enable-search 'safe-local-variable #'booleanp)
(put 'my/codex-remote-timeout 'safe-local-variable
     (lambda (value) (and (integerp value) (> value 0) (<= value 60))))
(put 'my/codex-remote-max-untracked-bytes 'safe-local-variable
     (lambda (value) (and (integerp value) (> value 0))))

(defvar-local my/codex-remote--prompt-context nil)

(defconst my/codex-remote--active-states
  '("SUBMITTING" "STARTING" "BOOTSTRAPPING" "RUNNING" "FINALIZING"
    "REFRESHING_ENVIRONMENT" "TESTING" "CANCEL_REQUESTED")
  "Remote states in which a task still owns the project runner.")

(defconst my/codex-remote--new-task-states
  '("NONE" "IMPORTED" "DISCARDED" "ARCHIVED")
  "Remote states from which a new managed task may be started.")

(defconst my/codex-remote--interactive-attach-states
  '("STARTING" "BOOTSTRAPPING" "RUNNING")
  "Interactive states in which the conversational TUI may be reattached.")

(defconst my/codex-remote--warning-import-states
  '("READY_TESTS_FAILED" "READY_CODEX_FAILED" "READY_TESTS_DIRTY"
    "READY_ENVIRONMENT_FAILED" "READY_ENVIRONMENT_DIRTY"
    "READY_ENVIRONMENT_UNVERIFIED" "READY_RECOVERED_UNVERIFIED"
    "CANCELLED_READY" "READY_JOB_NOT_LAUNCHED" "READY_JOB_PREPARED")
  "Importable states that require an explicit warning in the frontend.")

(defun my/codex-remote--get (object key)
  "Read KEY from JSON alist OBJECT, accepting symbol or string keys."
  (when (listp object)
    (or (alist-get key object)
        (alist-get (symbol-name key) object nil nil #'string=))))

(defun my/codex-remote--backend-check ()
  "Verify that the backend exists and can be executed."
  (unless (file-executable-p my/codex-remote-backend)
    (user-error "Codex remote backend is missing or not executable: %s"
                my/codex-remote-backend)))

(defun my/codex-remote--context ()
  "Capture the current project and remote settings."
  (my/remote-check)
  (my/codex-remote--backend-check)
  (let ((root (file-name-as-directory
               (expand-file-name (my/project-root)))))
    (list :root root
          :host my/remote-host
          :remote-dir my/remote-dir
          :bootstrap (or my/codex-remote-bootstrap-cmd
                         my/remote-setup-cmd)
          :test (or my/codex-remote-test-cmd
                    my/remote-test-cmd)
          :data-links (copy-sequence my/codex-remote-data-links)
          :model my/codex-remote-model
          :profile my/codex-remote-profile
          :reasoning my/codex-remote-reasoning-effort
          :search my/codex-remote-enable-search
          :job-policy "launch"
          :timeout my/codex-remote-timeout
          :max-untracked my/codex-remote-max-untracked-bytes)))

(defun my/codex-remote--project-buffer-p (root buffer)
  "Return non-nil when BUFFER visits a file inside ROOT."
  (when-let ((file (buffer-local-value 'buffer-file-name buffer)))
    (file-in-directory-p (file-truename file) (file-truename root))))

(defun my/codex-remote--save-project-buffers (root)
  "Save modified file buffers below ROOT, aborting if any remain modified."
  (save-some-buffers
   nil
   (lambda ()
     (and buffer-file-name
          (file-in-directory-p (file-truename buffer-file-name)
                               (file-truename root)))))
  (let ((remaining
         (seq-filter
          (lambda (buffer)
            (and (buffer-live-p buffer)
                 (buffer-modified-p buffer)
                 (my/codex-remote--project-buffer-p root buffer)))
          (buffer-list))))
    (when remaining
      (user-error "Save or revert modified project buffers before continuing: %s"
                  (mapconcat #'buffer-name remaining ", ")))))

(defun my/codex-remote--common-args (command context)
  "Return backend arguments for COMMAND and CONTEXT."
  (list my/codex-remote-backend
        command
        "--project-root" (plist-get context :root)
        "--host" (plist-get context :host)
        "--remote-dir" (plist-get context :remote-dir)
        "--timeout" (number-to-string (plist-get context :timeout))
        "--max-untracked-bytes"
        (number-to-string (plist-get context :max-untracked))))

(defun my/codex-remote--parse-buffer (buffer)
  "Parse the final JSON object emitted into BUFFER.

Ignore unrelated diagnostic lines so an SSH or Python warning does not hide an
otherwise valid machine-readable response."
  (with-current-buffer buffer
    (catch 'response
      (dolist (line (reverse (split-string
                              (buffer-substring-no-properties
                               (point-min) (point-max))
                              "\n" t)))
        (condition-case nil
            (let ((value (json-parse-string line
                                            :object-type 'alist
                                            :array-type 'list
                                            :null-object nil
                                            :false-object nil)))
              (when (and (listp value)
                         (seq-some (lambda (entry)
                                     (and (consp entry)
                                          (member (car entry) '(ok "ok"))))
                                   value))
                (throw 'response value)))
          (error nil)))
      nil)))

(defun my/codex-remote--error-code (response)
  "Return error code from backend RESPONSE."
  (my/codex-remote--get response 'error_code))

(defun my/codex-remote--command-output (result &optional fallback)
  "Return the first nonempty stdout/stderr string from RESULT.

Use FALLBACK when the command succeeded without emitting status text."
  (let ((stdout (my/codex-remote--get result 'stdout))
        (stderr (my/codex-remote--get result 'stderr)))
    (cond ((and (stringp stdout) (not (string-empty-p stdout))) stdout)
          ((and (stringp stderr) (not (string-empty-p stderr))) stderr)
          (t fallback))))

(defun my/codex-remote--display-raw-error (buffer response)
  "Display BUFFER and summarize backend RESPONSE."
  (with-current-buffer buffer
    (special-mode))
  (display-buffer buffer)
  (message "Remote Codex: %s%s"
           (or (my/codex-remote--get response 'error)
               "backend failure")
           (if-let ((code (my/codex-remote--error-code response)))
               (format " [%s]" code)
             "")))

(cl-defun my/codex-remote--run (action command context
                                       &key stdin on-success on-error quiet)
  "Run backend COMMAND asynchronously for ACTION.

CONTEXT is the captured project plist.  Send STDIN, then call ON-SUCCESS or
ON-ERROR with the parsed JSON object and process buffer."
  (let* ((project (file-name-nondirectory
                   (directory-file-name (plist-get context :root))))
         (buffer (generate-new-buffer
                  (format "*codex-remote-%s:%s*" action project)))
         (process-name (format "codex-remote-%s-%s-%d"
                               action project (truncate (* 1000 (float-time))))))
    (with-current-buffer buffer
      (let ((inhibit-read-only t))
        (erase-buffer)
        (fundamental-mode)))
    (let ((process
           (make-process
            :name process-name
            :buffer buffer
            :command command
            :connection-type 'pipe
            :noquery t
            :sentinel
            (lambda (proc _event)
              (when (memq (process-status proc) '(exit signal))
                (let* ((response
                        (condition-case nil
                            (my/codex-remote--parse-buffer buffer)
                          (error nil)))
                       (ok (and response
                                (my/codex-remote--get response 'ok)
                                (= (process-exit-status proc) 0))))
                  (if ok
                      (if on-success
                          (funcall on-success response buffer)
                        (message "Remote Codex %s completed" action))
                    (if on-error
                        (funcall on-error response buffer)
                      (my/codex-remote--display-raw-error buffer response)))))))))
      (when stdin
        (process-send-string process stdin))
      (process-send-eof process)
      (unless quiet
        (message "Remote Codex %s started asynchronously" action))
      process)))

(defun my/codex-remote--tmux-status-label (tmux)
  "Return an accurate human-readable state for TMUX status metadata."
  (cond
   ((not (my/codex-remote--get tmux 'exists)) "absent")
   ((my/codex-remote--get tmux 'pane_dead)
    (format "exited%s"
            (if-let ((status (my/codex-remote--get tmux 'pane_dead_status)))
                (format " (status %s)" status)
              "")))
   ((my/codex-remote--get tmux 'running) "running")
   (t "present (state unknown)")))

(defun my/codex-remote--data-links-label (task)
  "Return a compact persistent-data mapping label for TASK."
  (when-let ((links (my/codex-remote--get task 'data_links)))
    (string-join
     (delq nil
           (mapcar
            (lambda (link)
              (let ((source (my/codex-remote--get link 'source))
                    (target (my/codex-remote--get link 'target)))
                (when (and source target)
                  (format "%s -> %s" target source))))
            links))
     ", ")))

(defun my/codex-remote--task-lines (task)
  "Return human-readable status lines for TASK."
  (if (or (null task)
          (equal (my/codex-remote--get task 'state) "NONE"))
      '("State: NONE" "No remote Codex task exists for this project.")
    (let* ((tests (my/codex-remote--get task 'tests))
           (checkpoint (my/codex-remote--get task 'checkpoint))
           (tmux (my/codex-remote--get task 'tmux))
           (fields
            `(("State" . ,(my/codex-remote--get task 'state))
              ("Mode" . ,(or (my/codex-remote--get task 'execution_mode)
                               "exec"))
              ("Job policy" . ,(or (my/codex-remote--get task 'job_policy)
                                     "deny"))
              ("Model" . ,(my/codex-remote--get task 'model))
              ("Reasoning" . ,(my/codex-remote--get task 'reasoning_effort))
              ("Approvals" . ,(my/codex-remote--get task 'approval_policy))
              ("Network" . ,(if (my/codex-remote--get task 'network_access)
                                  "enabled in sandbox"
                                "sandbox default"))
              ("Project env" . ,(my/codex-remote--get
                                    task 'interactive_environment))
              ("Bootstrap" . ,(when (my/codex-remote--get task 'bootstrap_cmd)
                                  (if (my/codex-remote--get
                                       task 'bootstrap_inferred)
                                      "automatic locked uv sync"
                                    "project configuration")))
              ("Data links" . ,(my/codex-remote--data-links-label task))
              ("Task" . ,(my/codex-remote--get task 'task_id))
              ("Project" . ,(my/codex-remote--get task 'project_name))
              ("Started" . ,(or (my/codex-remote--get task 'codex_started_at)
                                 (my/codex-remote--get task 'created_at)))
              ("Finished" . ,(my/codex-remote--get task 'finished_at))
              ("Server worktree" . ,(my/codex-remote--get task 'worktree))
              ("Worktree exists" . ,(if (my/codex-remote--get task 'worktree_exists)
                                          "yes"
                                        "no"))
              ("tmux session" . ,(my/codex-remote--get task 'tmux_session))
              ("tmux process" . ,(my/codex-remote--tmux-status-label tmux))
              ("Lock held" . ,(my/codex-remote--get task 'lock_held))
              ("Codex thread" . ,(my/codex-remote--get task 'codex_thread_id))
              ("Codex exit" . ,(my/codex-remote--get task 'codex_exit_code))
              ("Checkpoint" . ,(and checkpoint
                                      (my/codex-remote--get checkpoint 'sha)))
              ("Checkpoint commits" . ,(and checkpoint
                                              (my/codex-remote--get
                                               checkpoint 'commit_count)))
              ("Checkpoint dirty" . ,(and checkpoint
                                            (if (my/codex-remote--get
                                                 checkpoint 'dirty)
                                                "yes"
                                              "no")))
              ("Result" . ,(my/codex-remote--get task 'result_sha))
              ("Lock files changed" . ,(my/codex-remote--get task 'lock_files_changed))
              ("Environment refresh" . ,(when-let ((refresh
                                                     (my/codex-remote--get
                                                      task 'environment_refresh)))
                                           (or (my/codex-remote--get refresh 'exit_code)
                                               (my/codex-remote--get refresh 'reason))))
              ("Test command" . ,(and tests
                                       (my/codex-remote--get tests 'command)))
              ("Test exit" . ,(and tests
                                    (my/codex-remote--get tests 'exit_code)))
              ("Launched run" . ,(when-let ((job
                                              (my/codex-remote--get
                                               task 'launched_job)))
                                    (my/codex-remote--get job 'run_id)))
              ("Job launch error" . ,(my/codex-remote--get
                                        task 'job_launch_error))
              ("Error" . ,(my/codex-remote--get task 'error)))))
      (mapcar (lambda (entry)
                (format "%-17s %s"
                        (concat (car entry) ":")
                        (if (null (cdr entry)) "-" (cdr entry))))
              fields))))

(defun my/codex-remote--show-status-response (response process-buffer)
  "Display a status or doctor RESPONSE."
  (let* ((task (my/codex-remote--get response 'task))
         (local-state (my/codex-remote--get response 'local_state))
         (remote (my/codex-remote--get response 'remote))
         (buffer (get-buffer-create "*codex-remote-status*")))
    (when (buffer-live-p process-buffer)
      (kill-buffer process-buffer))
    (with-current-buffer buffer
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert (propertize "Remote Codex status\n" 'face 'bold))
        (insert (make-string 72 ?-) "\n")
        (if task
            (insert (string-join (my/codex-remote--task-lines task) "\n") "\n")
          (insert (format "Project: %s\n"
                          (or (my/codex-remote--get response 'project_name) "-")))
          (when-let ((local (my/codex-remote--get response 'local)))
            (insert (format "Local Git: %s\n" (my/codex-remote--get local 'git)))
            (insert (format "Local SSH: %s\n" (my/codex-remote--get local 'ssh)))
            (insert (format "Branch: %s\n" (or (my/codex-remote--get local 'branch)
                                                 "(detached)"))))
          (when remote
            (insert "\nRemote prerequisites\n")
            (insert (make-string 72 ?-) "\n")
            (insert (format "Broker: %s\n" (my/codex-remote--get remote 'broker)))
            (insert (format "Worktrees: %s\n" (my/codex-remote--get remote 'worktrees)))
            (insert (format "Free bytes: %s\n"
                            (my/codex-remote--get remote 'disk_free_bytes)))
            (when-let ((version (my/codex-remote--get remote 'codex_version)))
              (insert (format "Codex: %s\n"
                              (my/codex-remote--get version 'stdout))))
            (when-let ((auth (my/codex-remote--get remote 'codex_auth)))
              (insert (format "Auth: %s\n"
                              (my/codex-remote--command-output
                               auth "(authenticated)"))))))
        (when local-state
          (insert "\nLocal orchestration state\n")
          (insert (make-string 72 ?-) "\n")
          (insert (format "State: %s\n"
                          (or (my/codex-remote--get local-state 'state) "-")))
          (insert (format "Task: %s\n"
                          (or (my/codex-remote--get local-state 'task_id) "-")))
          (when-let ((branch (my/codex-remote--get local-state 'local_branch)))
            (insert (format "Starting branch: %s\n" branch))))
        (goto-char (point-min))
        (special-mode)))
    (display-buffer buffer)))

(defun my/codex-remote-doctor ()
  "Verify the local repository and remote Codex prerequisites."
  (interactive)
  (let* ((context (my/codex-remote--context))
         (command (my/codex-remote--task-command "doctor" context)))
    (my/codex-remote--run
     "doctor" command context
     :on-success #'my/codex-remote--show-status-response)))

(defun my/codex-remote-status ()
  "Show the current remote Codex task for this project."
  (interactive)
  (let* ((context (my/codex-remote--context))
         (command (my/codex-remote--common-args "status" context)))
    (my/codex-remote--run
     "status" command context
     :on-success #'my/codex-remote--show-status-response)))

(defun my/codex-remote--task-option-args (context)
  "Return managed-task option arguments from CONTEXT."
  (let (arguments)
    (when-let ((value (plist-get context :bootstrap)))
      (setq arguments (append arguments (list "--bootstrap-cmd" value))))
    (when-let ((value (plist-get context :test)))
      (setq arguments (append arguments (list "--test-cmd" value))))
    (dolist (link (plist-get context :data-links))
      (setq arguments (append arguments (list "--data-link" link))))
    (when-let ((value (plist-get context :model)))
      (setq arguments (append arguments (list "--model" value))))
    (when-let ((value (plist-get context :profile)))
      (setq arguments (append arguments (list "--profile" value))))
    (when-let ((value (plist-get context :reasoning)))
      (setq arguments (append arguments (list "--reasoning-effort" value))))
    (when (plist-get context :search)
      (setq arguments (append arguments '("--enable-search"))))
    (when-let ((value (plist-get context :job-policy)))
      (setq arguments (append arguments (list "--job-policy" value))))
    arguments))

(defun my/codex-remote--task-command (action context)
  "Build a managed task command for ACTION and CONTEXT."
  (append (my/codex-remote--common-args action context)
          (my/codex-remote--task-option-args context)))

(defun my/codex-remote--start-command (context)
  "Build the noninteractive start command for CONTEXT."
  (append (my/codex-remote--task-command "start" context)
          '("--prompt-file" "-")))

(defun my/codex-remote--interactive-command (context)
  "Build the managed interactive-TUI command for CONTEXT."
  (my/codex-remote--task-command "interactive" context))

(defun my/codex-remote--submit-prompt (context prompt &optional prompt-buffer)
  "Submit PROMPT using captured project CONTEXT.

Keep PROMPT-BUFFER alive until submission succeeds so a transient SSH or
validation failure does not destroy a multiline task description."
  (unless (and (stringp prompt) (not (string-empty-p (string-trim prompt))))
    (user-error "Codex prompt is empty"))
  (my/codex-remote--save-project-buffers (plist-get context :root))
  (my/codex-remote--run
   "start" (my/codex-remote--start-command context) context
   :stdin prompt
   :on-success
   (lambda (response process-buffer)
     (kill-buffer process-buffer)
     (when (buffer-live-p prompt-buffer)
       (kill-buffer prompt-buffer))
     (message "%s" (or (my/codex-remote--get response 'message)
                        "Remote Codex task started")))
   :on-error
   (lambda (response process-buffer)
     (my/codex-remote--display-raw-error process-buffer response)
     (when (buffer-live-p prompt-buffer)
       (pop-to-buffer prompt-buffer)))))

(defun my/codex-remote-prompt-submit ()
  "Submit the prompt in the current Codex prompt buffer."
  (interactive)
  (unless my/codex-remote--prompt-context
    (user-error "This is not a remote Codex prompt buffer"))
  (let ((prompt (buffer-substring-no-properties (point-min) (point-max)))
        (context my/codex-remote--prompt-context)
        (buffer (current-buffer)))
    (my/codex-remote--submit-prompt context prompt buffer)))

(defun my/codex-remote-prompt-cancel ()
  "Cancel editing a remote Codex prompt."
  (interactive)
  (kill-buffer (current-buffer)))

(defun my/codex-remote--open-prompt-buffer (context)
  "Open a multiline prompt buffer using CONTEXT."
  (let* ((project (file-name-nondirectory
                   (directory-file-name (plist-get context :root))))
         (buffer (get-buffer-create (format "*codex-remote-prompt:%s*" project))))
    (with-current-buffer buffer
      (erase-buffer)
      (text-mode)
      (setq-local my/codex-remote--prompt-context context)
      (use-local-map (copy-keymap text-mode-map))
      (local-set-key (kbd "C-c C-c") #'my/codex-remote-prompt-submit)
      (local-set-key (kbd "C-c C-k") #'my/codex-remote-prompt-cancel)
      (setq header-line-format
            "Remote Codex prompt — C-c C-c submit, C-c C-k cancel"))
    (pop-to-buffer buffer)))

(defun my/codex-remote--start-with-policy (policy edit-prompt)
  "Start a durable remote Codex task using launch POLICY.

Use the active region as the prompt when present.  With prefix EDIT-PROMPT,
open a multiline prompt buffer; otherwise read a short prompt in the minibuffer."
  (let* ((context (my/codex-remote--context))
         (context (plist-put context :job-policy policy))
         (label (if (equal policy "launch")
                    "Remote Codex task (one frozen job authorized): "
                  "Remote Codex task: ")))
    (cond
     ((use-region-p)
      (my/codex-remote--submit-prompt
       context
       (buffer-substring-no-properties (region-beginning) (region-end))))
     (edit-prompt
      (my/codex-remote--open-prompt-buffer context))
     (t
      (my/codex-remote--submit-prompt
       context
       (read-string label))))))

(defun my/codex-remote-start (&optional edit-prompt)
  "Start a durable remote Codex task without detached-job authorization."
  (interactive "P")
  (my/codex-remote--start-with-policy "deny" edit-prompt))

(defun my/codex-remote-start-job (&optional edit-prompt)
  "Start Codex with authorization to request one frozen experiment job.

Codex cannot launch the process directly.  It must submit one request, after
which the trusted runner requires the configured smoke/test command to pass,
freezes the result revision, and starts the independent job."
  (interactive "P")
  (my/codex-remote--start-with-policy "launch" edit-prompt))

(defun my/codex-remote-logs ()
  "Show recent logs for the current project task."
  (interactive)
  (let* ((context (my/codex-remote--context))
         (command (append (my/codex-remote--common-args "logs" context)
                          '("--tail" "400"))))
    (my/codex-remote--run
     "logs" command context
     :on-success
     (lambda (response process-buffer)
       (let ((log (or (my/codex-remote--get response 'log) ""))
             (buffer (get-buffer-create "*codex-remote-logs*")))
         (kill-buffer process-buffer)
         (with-current-buffer buffer
           (let ((inhibit-read-only t))
             (erase-buffer)
             (insert log)
             (goto-char (point-min))
             (special-mode)))
         (display-buffer buffer))))))

(defun my/codex-remote--ssh-executable ()
  "Return the SSH executable visible to this Emacs process."
  (or (and (fboundp 'my/process-path--find-executable)
           (my/process-path--find-executable "ssh"))
      (executable-find "ssh")
      (user-error "Could not find ssh in Emacs's process environment")))

(defun my/codex-remote--configured-executable (program description)
  "Resolve configured PROGRAM or signal an error naming DESCRIPTION."
  (unless (and (stringp program) (not (string-empty-p program)))
    (user-error "Configure a nonempty %s executable" description))
  (or (and (file-name-absolute-p program)
           (file-executable-p program)
           program)
      (and (fboundp 'my/process-path--find-executable)
           (my/process-path--find-executable program))
      (executable-find program)
      (user-error "Could not find %s executable: %s" description program)))

(defun my/codex-remote--external-terminal-executable ()
  "Return the configured interactive external terminal executable."
  (my/codex-remote--configured-executable
   (car my/codex-remote-external-terminal-command)
   "external terminal"))

(defun my/codex-remote--job-executable ()
  "Return the executable terminal one-shot job frontend."
  (my/codex-remote--configured-executable
   my/codex-remote-job-program
   "codex-remote-job"))

(defun my/codex-remote--job-terminal-executable ()
  "Return the configured one-shot job terminal executable."
  (my/codex-remote--configured-executable
   (car my/codex-remote-job-terminal-command)
   "Codex job terminal"))

(defun my/codex-remote--tmux-attach-args (context task &optional read-only)
  "Return SSH arguments for TASK's tmux session.

When READ-ONLY is non-nil, attach the tmux client without allowing input."
  (append
   (list "-tt"
         "-o" "BatchMode=yes"
         "-o" (format "ConnectTimeout=%s" (plist-get context :timeout))
         "-o" "ConnectionAttempts=1"
         (plist-get context :host)
         "env" "TERM=xterm-256color"
         "tmux" "attach-session")
   (when read-only (list "-r"))
   (list "-t" (my/codex-remote--get task 'tmux_session))))

(defun my/codex-remote--tmux-monitor-args (context task)
  "Return SSH arguments for a read-only tmux monitor of TASK."
  (my/codex-remote--tmux-attach-args context task t))

(defun my/codex-remote--tmux-interactive-args (context task)
  "Return SSH arguments for a read-write tmux attachment to TASK."
  (my/codex-remote--tmux-attach-args context task nil))

(defun my/codex-remote--require-live-tmux (task)
  "Return TASK's tmux session name, or signal a useful user error."
  (let* ((session (my/codex-remote--get task 'tmux_session))
         (state (my/codex-remote--get task 'state))
         (identifier (or (my/codex-remote--get task 'task_id)
                         (my/codex-remote--get task 'run_id)
                         state))
         (tmux (my/codex-remote--get task 'tmux)))
    (unless session
      (user-error "%s has no tmux session" identifier))
    (unless (my/codex-remote--get tmux 'exists)
      (user-error "%s has no live tmux session; inspect its logs" identifier))
    (when (my/codex-remote--get tmux 'pane_dead)
      (user-error
       "%s has already exited%s; inspect its logs"
       identifier
       (if-let ((status (my/codex-remote--get tmux 'pane_dead_status)))
           (format " with status %s" status)
         "")))
    session))

(defun my/codex-remote--open-tmux (context task)
  "Monitor TASK's live tmux pane in Emacs's built-in terminal emulator."
  (let* ((session (my/codex-remote--require-live-tmux task))
         (task-id (or (my/codex-remote--get task 'task_id)
                      (my/codex-remote--get task 'run_id))))
    (require 'term)
    (let* ((name (format "codex-remote-tmux:%s" task-id))
           (buffer-name (format "*%s*" name))
           (existing (get-buffer buffer-name)))
      (if (and existing (term-check-proc existing))
          (pop-to-buffer existing)
        (when existing
          (kill-buffer existing))
        (let ((buffer
               (apply #'make-term
                      name
                      (my/codex-remote--ssh-executable)
                      nil
                      (my/codex-remote--tmux-monitor-args context task))))
          (with-current-buffer buffer
            (term-char-mode)
            (when-let ((process (get-buffer-process buffer)))
              (set-process-query-on-exit-flag process nil)))
          (pop-to-buffer buffer))))))

(defun my/codex-remote--external-terminal-command (context task)
  "Return the external-terminal command for TASK."
  (append
   (cons (my/codex-remote--external-terminal-executable)
         (cdr my/codex-remote-external-terminal-command))
   (list (my/codex-remote--ssh-executable))
   (my/codex-remote--tmux-interactive-args context task)))

(defun my/codex-remote--open-external-tmux (context task)
  "Open TASK's live tmux pane in an external read-write terminal."
  (my/codex-remote--require-live-tmux task)
  (let* ((task-id (my/codex-remote--get task 'task_id))
         (process
          (make-process
           :name (format "codex-remote-interactive-%s-%d"
                         task-id
                         (truncate (* 1000 (float-time))))
           :buffer nil
           :command (my/codex-remote--external-terminal-command context task)
           :connection-type 'pipe
           :noquery t
           :sentinel
           (lambda (proc _event)
             (when (and (memq (process-status proc) '(exit signal))
                        (not (= (process-exit-status proc) 0)))
               (message
                "Remote Codex external terminal exited with status %s"
                (process-exit-status proc)))))))
    (message
     "Opened external Codex terminal for %s; closing it detaches while tmux continues"
     task-id)
    process))

(defun my/codex-remote-attach ()
  "Open a read-only monitor for the current live remote Codex task."
  (interactive)
  (let* ((context (my/codex-remote--context))
         (command (my/codex-remote--common-args "status" context)))
    (my/codex-remote--run
     "attach" command context
     :on-success
     (lambda (response buffer)
       (kill-buffer buffer)
       (let ((task (my/codex-remote--get response 'task)))
         (when (equal (my/codex-remote--get task 'state) "NONE")
           (user-error "No remote Codex task exists for this project"))
         (my/codex-remote--open-tmux context task))))))

(defun my/codex-remote--task-execution-mode (task)
  "Return TASK's execution mode, treating older tasks as noninteractive."
  (or (my/codex-remote--get task 'execution_mode) "exec"))

(defun my/codex-remote--interactive-action (task)
  "Return how `SPC r c i' should handle TASK."
  (let ((state (or (my/codex-remote--get task 'state) "NONE"))
        (mode (my/codex-remote--task-execution-mode task)))
    (cond
     ((and (member state my/codex-remote--interactive-attach-states)
           (equal mode "interactive"))
      'attach)
     ((member state my/codex-remote--new-task-states)
      'start)
     (t 'blocked))))

(defun my/codex-remote--start-interactive (context)
  "Start a managed interactive Codex TUI using captured CONTEXT."
  (my/codex-remote--save-project-buffers (plist-get context :root))
  (my/codex-remote--run
   "interactive-start"
   (my/codex-remote--interactive-command context)
   context
   :on-success
   (lambda (response buffer)
     (kill-buffer buffer)
     (let ((task (my/codex-remote--get response 'task)))
       (condition-case err
           (my/codex-remote--open-external-tmux context task)
         (error
          (message
           "Managed Codex task %s started, but the external terminal could not open: %s"
           (or (my/codex-remote--get task 'task_id) "-")
           (error-message-string err))))))))

(defun my/codex-remote--interactive-with-policy (policy)
  "Start or reattach to a managed interactive Codex TUI using POLICY.

A new session uses the same hidden local snapshot, isolated server worktree,
result publication, and safe local import path as `my/codex-remote-start'.  If
an interactive session is already active, this command simply reattaches to
its existing tmux session without resnapshotting or saving local buffers."
  (let* ((context (plist-put (my/codex-remote--context) :job-policy policy))
         (command (my/codex-remote--common-args "status" context)))
    (my/codex-remote--run
     "interactive-status" command context
     :on-success
     (lambda (response buffer)
       (let* ((task (my/codex-remote--get response 'task))
              (state (or (my/codex-remote--get task 'state) "NONE"))
              (mode (my/codex-remote--task-execution-mode task)))
         (pcase (my/codex-remote--interactive-action task)
           ('attach
            (kill-buffer buffer)
            (my/codex-remote--open-external-tmux context task))
           ('start
            (kill-buffer buffer)
            ;; Do not prompt to save buffers from inside a process sentinel.
            (run-at-time 0 nil #'my/codex-remote--start-interactive context))
           (_
            (my/codex-remote--show-status-response response buffer)
            (message
             "Outstanding %s Codex task is %s; import, archive, or discard it before starting an interactive TUI"
             mode state))))))))

(defun my/codex-remote-interactive ()
  "Start or reattach to managed interactive Codex with frozen-job authorization."
  (interactive)
  (my/codex-remote--interactive-with-policy "launch"))

(defun my/codex-remote-interactive-job ()
  "Start or reattach to interactive Codex with one frozen job authorized.

An already-running interactive task is only reattached; its original launch
policy is not upgraded."
  (interactive)
  (my/codex-remote--interactive-with-policy "launch"))


(defun my/codex-remote--job-command (context)
  "Return the external terminal command for a one-shot job using CONTEXT.

The terminal frontend remains an ordinary editing task.  Frozen-job launch
authorization is deliberately available only through the explicit uppercase
Doom commands, so do not pass the internal job-policy option here."
  (let ((ordinary-context (plist-put (copy-sequence context) :job-policy nil)))
    (append
     (cons (my/codex-remote--job-terminal-executable)
           (cdr my/codex-remote-job-terminal-command))
     (list (my/codex-remote--job-executable)
           "--project-root" (plist-get context :root)
           "--backend" my/codex-remote-backend
           "--host" (plist-get context :host)
           "--remote-dir" (plist-get context :remote-dir)
           "--timeout" (number-to-string (plist-get context :timeout))
           "--max-untracked-bytes"
           (number-to-string (plist-get context :max-untracked)))
     (my/codex-remote--task-option-args ordinary-context)
     (unless (plist-get context :search) '("--disable-search"))
     '("--ignore-config" "--pause-at-end"))))

(defun my/codex-remote-job ()
  "Open an external terminal to prompt for and watch a managed one-shot job.

The resulting task is identical to `my/codex-remote-start' and remains
importable through `my/codex-remote-apply'."
  (interactive)
  (let* ((context (my/codex-remote--context))
         (root (plist-get context :root)))
    (my/codex-remote--save-project-buffers root)
    (let ((process
           (make-process
            :name (format "codex-remote-job-%d"
                          (truncate (* 1000 (float-time))))
            :buffer nil
            :command (my/codex-remote--job-command context)
            :connection-type 'pipe
            :noquery t
            :sentinel
            (lambda (proc _event)
              (when (and (memq (process-status proc) '(exit signal))
                         (not (= (process-exit-status proc) 0)))
                (message "Remote Codex job terminal exited with status %s"
                         (process-exit-status proc)))))))
      (message "Opened terminal prompt/watcher for a managed remote Codex job")
      process)))


;; Frozen experiment jobs ----------------------------------------------------

(defun my/codex-job--command (action context run-id &rest extra)
  "Return backend ACTION for RUN-ID using CONTEXT and EXTRA arguments."
  (append (my/codex-remote--common-args action context)
          (list "--run-id" run-id)
          extra))

(defun my/codex-job--display-command (command)
  "Render JSON COMMAND argv for status buffers."
  (if (listp command)
      (mapconcat (lambda (value)
                   (shell-quote-argument (format "%s" value)))
                 command " ")
    "-"))

(defun my/codex-job--lines (job)
  "Return readable status lines for frozen experiment JOB."
  (let* ((analysis (my/codex-remote--get job 'analysis))
         (bootstrap (my/codex-remote--get job 'bootstrap))
         (source-integrity (my/codex-remote--get job 'source_integrity))
         (tmux (my/codex-remote--get job 'tmux))
         (fields
          `(("State" . ,(my/codex-remote--get job 'state))
            ("Phase" . ,(my/codex-remote--get job 'phase))
            ("Run" . ,(my/codex-remote--get job 'run_id))
            ("Name" . ,(my/codex-remote--get job 'name))
            ("Created" . ,(my/codex-remote--get job 'created_at))
            ("Started" . ,(my/codex-remote--get job 'started_at))
            ("Finished" . ,(my/codex-remote--get job 'finished_at))
            ("Source SHA" . ,(my/codex-remote--get job 'source_sha))
            ("Source task" . ,(my/codex-remote--get job 'source_task_id))
            ("GPUs" . ,(or (my/codex-remote--get job 'gpus) "inherited"))
            ("Command" . ,(my/codex-job--display-command
                             (my/codex-remote--get job 'command)))
            ("Bootstrap" . ,(my/codex-remote--get job 'bootstrap_cmd))
            ("Bootstrap exit" . ,(and bootstrap
                                      (my/codex-remote--get bootstrap 'exit_code)))
            ("Exit" . ,(my/codex-remote--get job 'exit_code))
            ("Completion marker" . ,(my/codex-remote--get
                                       job 'completion_marker))
            ("Marker present"
             . ,(when-let ((marker (my/codex-remote--get
                                    job 'completion_marker)))
                  (unless (string-empty-p marker)
                    (if (my/codex-remote--get
                         job 'completion_marker_present)
                        "yes"
                      "no"))))
            ("Tracked source clean"
             . ,(when source-integrity
                  (if (my/codex-remote--get source-integrity 'tracked_clean)
                      "yes"
                    "no")))
            ("Source HEAD unchanged"
             . ,(when source-integrity
                  (if (my/codex-remote--get
                       source-integrity 'head_matches_source)
                      "yes"
                    "no")))
            ("Untracked run files"
             . ,(when-let ((paths (and source-integrity
                                      (my/codex-remote--get
                                       source-integrity 'untracked_paths))))
                  (length paths)))
            ("Worktree" . ,(my/codex-remote--get job 'worktree))
            ("Run directory" . ,(my/codex-remote--get job 'state_dir))
            ("tmux session" . ,(my/codex-remote--get job 'tmux_session))
            ("tmux process" . ,(my/codex-remote--tmux-status-label tmux))
            ("Process alive" . ,(my/codex-remote--get job 'process_alive))
            ("Analysis" . ,(and analysis
                                  (my/codex-remote--get analysis 'state)))
            ("Error" . ,(my/codex-remote--get job 'error)))))
    (mapcar (lambda (entry)
              (format "%-20s %s"
                      (concat (car entry) ":")
                      (if (or (null (cdr entry))
                              (equal (cdr entry) ""))
                          "-"
                        (cdr entry))))
            fields)))

(defun my/codex-job--show-status-response (response process-buffer)
  "Display a frozen-job status RESPONSE from PROCESS-BUFFER."
  (let ((job (my/codex-remote--get response 'job))
        (buffer (get-buffer-create "*codex-job-status*")))
    (when (buffer-live-p process-buffer)
      (kill-buffer process-buffer))
    (with-current-buffer buffer
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert (propertize "Frozen experiment job\n" 'face 'bold))
        (insert (make-string 76 ?-) "\n")
        (insert (string-join (my/codex-job--lines job) "\n") "\n")
        (goto-char (point-min))
        (special-mode)))
    (display-buffer buffer)))

(defun my/codex-jobs--show-list-response (response process-buffer)
  "Display the experiment-job list in RESPONSE."
  (let ((jobs (my/codex-remote--get response 'jobs))
        (buffer (get-buffer-create "*codex-jobs*")))
    (when (buffer-live-p process-buffer)
      (kill-buffer process-buffer))
    (with-current-buffer buffer
      (let ((inhibit-read-only t))
        (erase-buffer)
        (insert (propertize "Frozen experiment jobs\n" 'face 'bold))
        (insert (make-string 100 ?-) "\n")
        (if jobs
            (dolist (job jobs)
              (insert
               (format "%-42s %-14s %-24s %s\n"
                       (or (my/codex-remote--get job 'run_id) "-")
                       (or (my/codex-remote--get job 'state) "-")
                       (or (my/codex-remote--get job 'name) "-")
                       (or (my/codex-remote--get job 'created_at) "-"))))
          (insert "No frozen experiment jobs exist for this project.\n"))
        (goto-char (point-min))
        (special-mode)))
    (display-buffer buffer)))

(defun my/codex-jobs-list ()
  "List frozen experiment jobs for the current project."
  (interactive)
  (let* ((context (my/codex-remote--context))
         (command (my/codex-remote--common-args "jobs" context)))
    (my/codex-remote--run
     "jobs" command context
     :on-success #'my/codex-jobs--show-list-response)))

(defun my/codex-job--select (context callback)
  "Select a job for CONTEXT, then call CALLBACK with its run ID."
  (my/codex-remote--run
   "job-select"
   (my/codex-remote--common-args "jobs" context)
   context
   :quiet t
   :on-success
   (lambda (response buffer)
     (kill-buffer buffer)
     (let ((jobs (my/codex-remote--get response 'jobs)))
       (if (not jobs)
           (message "No frozen experiment jobs exist for this project")
         (let ((choices
                (mapcar
                 (lambda (job)
                   (let ((run-id (my/codex-remote--get job 'run_id)))
                     (cons
                      (format "%s  [%s]  %s"
                              run-id
                              (or (my/codex-remote--get job 'state) "-")
                              (or (my/codex-remote--get job 'name) "-"))
                      run-id)))
                 jobs)))
           ;; Prompt outside the process sentinel so minibuffer interaction is
           ;; not nested inside process cleanup.
           (run-at-time
            0 nil
            (lambda ()
              (let* ((choice (completing-read "Experiment job: " choices nil t))
                     (run-id (cdr (assoc choice choices))))
                (funcall callback run-id))))))))))

(defun my/codex-job-status ()
  "Select and show one frozen experiment job."
  (interactive)
  (let ((context (my/codex-remote--context)))
    (my/codex-job--select
     context
     (lambda (run-id)
       (my/codex-remote--run
        "job-status" (my/codex-job--command "job-status" context run-id)
        context :on-success #'my/codex-job--show-status-response)))))

(defun my/codex-job-logs ()
  "Select a frozen experiment job and show its recent logs."
  (interactive)
  (let ((context (my/codex-remote--context)))
    (my/codex-job--select
     context
     (lambda (run-id)
       (my/codex-remote--run
        "job-logs"
        (my/codex-job--command "job-logs" context run-id "--tail" "500")
        context
        :on-success
        (lambda (response process-buffer)
          (let ((log (or (my/codex-remote--get response 'log) ""))
                (buffer (get-buffer-create "*codex-job-logs*")))
            (kill-buffer process-buffer)
            (with-current-buffer buffer
              (let ((inhibit-read-only t))
                (erase-buffer)
                (insert log)
                (goto-char (point-min))
                (special-mode)))
            (display-buffer buffer))))))))

(defun my/codex-job-attach ()
  "Select an active experiment job and monitor its tmux pane read-only."
  (interactive)
  (let ((context (my/codex-remote--context)))
    (my/codex-job--select
     context
     (lambda (run-id)
       (my/codex-remote--run
        "job-attach"
        (my/codex-job--command "job-status" context run-id)
        context
        :on-success
        (lambda (response buffer)
          (kill-buffer buffer)
          (my/codex-remote--open-tmux
           context (my/codex-remote--get response 'job))))))))

(defun my/codex-job-stop ()
  "Select and stop an active frozen experiment job."
  (interactive)
  (let ((context (my/codex-remote--context)))
    (my/codex-job--select
     context
     (lambda (run-id)
       (when (yes-or-no-p (format "Stop experiment job %s? " run-id))
         (my/codex-remote--run
          "job-stop" (my/codex-job--command "job-stop" context run-id)
          context
          :on-success
          (lambda (response buffer)
            (kill-buffer buffer)
            (message "Stop requested for experiment job %s"
                     (my/codex-remote--get
                      (my/codex-remote--get response 'job) 'run_id)))))))))

(defun my/codex-job-interpret ()
  "Start a read-only Codex interpretation of a finished experiment job."
  (interactive)
  (let ((context (my/codex-remote--context)))
    (my/codex-job--select
     context
     (lambda (run-id)
       (my/codex-remote--run
        "job-interpret"
        (my/codex-job--command "job-summarize" context run-id)
        context
        :on-success
        (lambda (response buffer)
          (kill-buffer buffer)
          (let ((analysis (my/codex-remote--get response 'analysis)))
            (message "Experiment interpretation for %s is %s"
                     run-id
                     (or (my/codex-remote--get analysis 'state)
                         "starting")))))))))

(defun my/codex-job-analysis ()
  "Select and show the latest structured interpretation for an experiment."
  (interactive)
  (let ((context (my/codex-remote--context)))
    (my/codex-job--select
     context
     (lambda (run-id)
       (my/codex-remote--run
        "job-analysis"
        (my/codex-job--command "job-analysis" context run-id)
        context
        :on-success
        (lambda (response process-buffer)
          (let* ((markdown (or (my/codex-remote--get response 'markdown) ""))
                 (job (my/codex-remote--get response 'job))
                 (analysis (my/codex-remote--get job 'analysis))
                 (buffer (get-buffer-create "*codex-job-analysis*")))
            (kill-buffer process-buffer)
            (with-current-buffer buffer
              (let ((inhibit-read-only t))
                (erase-buffer)
                (if (string-empty-p markdown)
                    (insert (format "No completed analysis is available. Current analysis state: %s\n"
                                    (or (my/codex-remote--get analysis 'state)
                                        "not started")))
                  (insert markdown))
                (goto-char (point-min))
                (if (fboundp 'markdown-mode)
                    (markdown-mode)
                  (special-mode))))
            (display-buffer buffer))))))))


;; AGENTS.md setup -----------------------------------------------------------

(defun my/codex-remote-install-global-agents ()
  "Install or update the managed global Codex instructions on the server."
  (interactive)
  (let ((context (my/codex-remote--context)))
    (when (yes-or-no-p
           (format "Install managed global Codex instructions on %s? "
                   (plist-get context :host)))
      (my/codex-remote--run
       "install-agents"
       (my/codex-remote--common-args "install-agents" context)
       context
       :on-success
       (lambda (response buffer)
         (kill-buffer buffer)
         (message "Installed managed global Codex instructions at %s"
                  (my/codex-remote--get response 'path)))))))

(defun my/codex-remote-project-agents ()
  "Create or open this repository's research-oriented AGENTS.md."
  (interactive)
  (let* ((context (my/codex-remote--context))
         (root (plist-get context :root))
         (target (expand-file-name "AGENTS.md" root)))
    (unless (file-readable-p my/codex-remote-research-agents-template)
      (user-error "Research AGENTS template is unavailable: %s"
                  my/codex-remote-research-agents-template))
    (unless (file-exists-p target)
      (copy-file my/codex-remote-research-agents-template target nil)
      (message "Created %s; review and commit it with the repository" target))
    (find-file target)))


(defun my/codex-remote--open-conflict-worktree (response)
  "Open RESPONSE's preserved integration worktree in Magit."
  (let* ((details (my/codex-remote--get response 'details))
         (path (my/codex-remote--get details 'conflict_path)))
    (unless (and path (file-directory-p path))
      (user-error "The preserved integration worktree is unavailable"))
    (require 'magit)
    (magit-status-setup-buffer path)
    (message
     "Resolve the integration, complete its rebase, then rerun SPC r c f")))

(defun my/codex-remote--apply-success (response buffer)
  "Handle successful import RESPONSE from BUFFER."
  (kill-buffer buffer)
  (when (fboundp 'magit-refresh-all)
    (magit-refresh-all))
  (let ((source-state (my/codex-remote--get response 'source_state))
        (message-text (or (my/codex-remote--get response 'message)
                          "Remote Codex result imported")))
    (message "%s%s"
             message-text
             (if (member source-state my/codex-remote--warning-import-states)
                 (format " (imported from warning state %s)" source-state)
               ""))))

(defun my/codex-remote--refresh-project-buffers (root)
  "Revert unmodified visiting buffers below ROOT after a Git fast-forward."
  (dolist (buffer (buffer-list))
    (with-current-buffer buffer
      (when (and buffer-file-name
                 (not (buffer-modified-p))
                 (file-exists-p buffer-file-name)
                 (file-in-directory-p (file-truename buffer-file-name)
                                      (file-truename root))
                 (not (verify-visited-file-modtime buffer)))
        (condition-case err
            (revert-buffer :ignore-auto :noconfirm)
          (error
           (message "Could not refresh %s after Codex pull: %s"
                    (buffer-name buffer)
                    (error-message-string err))))))))

(defun my/codex-remote--pull-success
    (response buffer context &optional continuation)
  "Handle committed-checkpoint RESPONSE and then call CONTINUATION.

CONTEXT identifies the project whose unmodified visiting buffers should be
refreshed after a successful fast-forward.  CONTINUATION receives RESPONSE and
is used by the ordinary remote sync/run commands so pulling a live Codex
checkpoint remains an invisible preflight."
  (when (buffer-live-p buffer)
    (kill-buffer buffer))
  (let ((count (or (my/codex-remote--get response 'changed_commit_count) 0))
        (message-text (my/codex-remote--get response 'message)))
    (when (> count 0)
      (my/codex-remote--refresh-project-buffers (plist-get context :root))
      (when (fboundp 'magit-refresh-all)
        (magit-refresh-all))
      (message "%s" (or message-text
                         (format "Pulled %d Codex commit(s)" count))))
    (when continuation
      (funcall continuation response))))

(cl-defun my/codex-remote--run-pull (context &key continuation quiet)
  "Pull committed interactive checkpoints for CONTEXT.

When CONTINUATION is non-nil, invoke it after a successful pull/no-op.  A quiet
automatic preflight defers `LOCAL_DIRTY_FOR_COMMIT_PULL' and lets the requested
remote action retain its original behavior; explicit pulls and every other
integration failure remain strict."
  (let ((command (my/codex-remote--common-args "pull" context)))
    (my/codex-remote--run
     "pull" command context
     :quiet quiet
     :on-success
     (lambda (response buffer)
       (my/codex-remote--pull-success response buffer context continuation))
     :on-error
     (lambda (response buffer)
       (if (and quiet
                continuation
                (equal (my/codex-remote--error-code response)
                       "LOCAL_DIRTY_FOR_COMMIT_PULL"))
           (progn
             (when (buffer-live-p buffer)
               (kill-buffer buffer))
             (message
              (concat
               "Codex commits are waiting, but local tracked edits are still "
               "in progress; continuing this remote action without importing them"))
             (funcall continuation
                      `((ok . t)
                        (changed_commit_count . 0)
                        (pull_deferred . t)
                        (deferred_error . ,response))))
         (my/codex-remote--display-raw-error buffer response)
         (message "Remote action stopped because live Codex commits could not be pulled"))))))

(defun my/codex-remote-pull ()
  "Pull the latest committed interactive Codex checkpoint without stopping it."
  (interactive)
  (let* ((context (my/codex-remote--context))
         (root (plist-get context :root)))
    (my/codex-remote--save-project-buffers root)
    (my/codex-remote--run-pull context)))

(defun my/codex-remote-refresh-then (continuation)
  "Pull any live Codex commits, then call CONTINUATION with the response.

This is the bridge used by the normal `SPC r' commands.  A project without an
interactive task produces a fast no-op response and continues normally."
  (let* ((context (my/codex-remote--context))
         (root (plist-get context :root)))
    (my/codex-remote--save-project-buffers root)
    (my/codex-remote--run-pull
     context :continuation continuation :quiet t)))

(defun my/codex-remote--run-apply (context &optional allow-branch-change
                                           preserve-local push-backup)
  "Run the backend import for CONTEXT with the requested recovery options."
  (let ((command (my/codex-remote--common-args "apply" context)))
    (when allow-branch-change
      (setq command (append command '("--allow-branch-change"))))
    (when preserve-local
      (setq command (append command '("--preserve-local-branch"))))
    (when push-backup
      (setq command (append command '("--push-backup" "--backup-remote" "origin"))))
    (my/codex-remote--run
     "apply" command context
     :on-success #'my/codex-remote--apply-success
     :on-error
     (lambda (response buffer)
       (my/codex-remote--apply-error
        context response buffer allow-branch-change)))))

(defun my/codex-remote--preserve-local-and-retry (context allow-branch-change)
  "Preserve local work on a backup branch, then retry import for CONTEXT."
  (let ((push (yes-or-no-p
               "Push the local backup branch to origin before resetting the original branch? ")))
    (my/codex-remote--save-project-buffers (plist-get context :root))
    (my/codex-remote--run-apply context allow-branch-change t push)))

(defun my/codex-remote--prompt-conflict-action
    (context response allow-branch-change)
  "Prompt for a safe action after integration conflict RESPONSE."
  (let ((choice
         (read-char-choice
          (concat
           "Codex conflicts with current local work: "
           "[r] resolve in isolated worktree, "
           "[b] preserve local work on a timestamped branch and retry, "
           "[a] abort: ")
          '(?r ?b ?a))))
    (pcase choice
      (?r (my/codex-remote--open-conflict-worktree response))
      (?b (my/codex-remote--preserve-local-and-retry
           context allow-branch-change))
      (?a (message "Codex import aborted; canonical checkout remains unchanged")))))

(defun my/codex-remote--prompt-branch-change (context response)
  "Ask whether RESPONSE should be applied to the currently checked-out branch."
  (let* ((details (my/codex-remote--get response 'details))
         (start (or (my/codex-remote--get details 'start_branch) "(detached)"))
         (current (or (my/codex-remote--get details 'current_branch) "(detached)")))
    (if (yes-or-no-p
         (format "Task started on %s, but current branch is %s. Apply to current branch? "
                 start current))
        (my/codex-remote--run-apply context t)
      (message "Codex import aborted; no branch was switched"))))

(defun my/codex-remote--apply-error
    (context response buffer allow-branch-change)
  "Handle apply failure RESPONSE from BUFFER for CONTEXT."
  (let ((code (my/codex-remote--error-code response)))
    (my/codex-remote--display-raw-error buffer response)
    (cond
     ((equal code "BRANCH_CHANGED")
      (run-at-time 0 nil #'my/codex-remote--prompt-branch-change
                   context response))
     ((member code '("INTEGRATION_CONFLICT"
                     "INTEGRATION_CONFLICT_PENDING"
                     "INTEGRATION_EXISTS"))
      (let* ((details (my/codex-remote--get response 'details))
             (kind (my/codex-remote--get details 'integration_kind)))
        (if (equal kind "commit-checkpoint")
            (run-at-time 0 nil #'my/codex-remote--open-conflict-worktree
                         response)
          (run-at-time 0 nil #'my/codex-remote--prompt-conflict-action
                       context response allow-branch-change)))))))

(defun my/codex-remote--confirm-import-state
    (context allow-branch-change response buffer)
  "Inspect status RESPONSE before importing a result for CONTEXT."
  (let* ((task (my/codex-remote--get response 'task))
         (state (or (my/codex-remote--get task 'state) "NONE"))
         (mode (my/codex-remote--task-execution-mode task)))
    (kill-buffer buffer)
    (cond
     ((and (equal mode "interactive")
           (member state my/codex-remote--active-states))
      (my/codex-remote--run-apply context allow-branch-change))
     ((member state my/codex-remote--warning-import-states)
      (run-at-time
       0 nil
       (lambda ()
         (when (yes-or-no-p
                (format "Remote Codex result is %s. Import it anyway? " state))
           (my/codex-remote--run-apply context allow-branch-change)))))
     (t
      (my/codex-remote--run-apply context allow-branch-change)))))

(defun my/codex-remote-apply (&optional allow-branch-change)
  "Pull interactive commits or apply a completed one-shot Codex delta.

With prefix ALLOW-BRANCH-CHANGE, deliberately apply a task that started on a
different branch to the currently checked-out branch.  Otherwise a branch
change is presented as an explicit prompt."
  (interactive "P")
  (let* ((context (my/codex-remote--context))
         (root (plist-get context :root))
         (command (my/codex-remote--common-args "status" context)))
    (my/codex-remote--save-project-buffers root)
    (my/codex-remote--run
     "apply-preflight" command context
     :on-success
     (lambda (response buffer)
       (my/codex-remote--confirm-import-state
        context allow-branch-change response buffer)))))

(defun my/codex-remote-cancel ()
  "Request cancellation of the active task without discarding its worktree."
  (interactive)
  (when (yes-or-no-p "Cancel the active remote Codex task and preserve its work? ")
    (let* ((context (my/codex-remote--context))
           (command (my/codex-remote--common-args "cancel" context)))
      (my/codex-remote--run
       "cancel" command context
       :on-success
       (lambda (response buffer)
         (kill-buffer buffer)
         (message "Cancellation requested for %s"
                  (my/codex-remote--get
                   (my/codex-remote--get response 'task) 'task_id)))))))

(defun my/codex-remote-recover ()
  "Finalize a preserved orphaned/failed worktree without rerunning Codex."
  (interactive)
  (when (yes-or-no-p
         "Recover the preserved worktree without rerunning Codex or server tests? ")
    (let* ((context (my/codex-remote--context))
           (command (my/codex-remote--common-args "recover" context)))
      (my/codex-remote--run
       "recover" command context
       :on-success
       (lambda (response buffer)
         (message "%s" (or (my/codex-remote--get response 'message)
                            "Remote Codex worktree recovered"))
         (my/codex-remote--show-status-response response buffer))))))

(defun my/codex-remote-clean ()
  "Archive the server worktree after a successful local import."
  (interactive)
  (let* ((context (my/codex-remote--context))
         (command (my/codex-remote--common-args "clean" context)))
    (my/codex-remote--run
     "clean" command context
     :on-success
     (lambda (response buffer)
       (kill-buffer buffer)
       (message "Archived remote Codex task %s"
                (my/codex-remote--get
                 (my/codex-remote--get response 'task) 'task_id))))))

(defun my/codex-remote-discard ()
  "Explicitly discard the current remote task and its isolated worktree."
  (interactive)
  (when (yes-or-no-p
         "Discard the current remote Codex task/worktree? This can destroy unimported edits. ")
    (let* ((context (my/codex-remote--context))
           (command (append (my/codex-remote--common-args "clean" context)
                            '("--discard"))))
      (my/codex-remote--run
       "discard" command context
       :on-success
       (lambda (response buffer)
         (kill-buffer buffer)
         (message "Discarded remote Codex task %s"
                  (my/codex-remote--get
                   (my/codex-remote--get response 'task) 'task_id)))))))

(provide 'codex-remote)
