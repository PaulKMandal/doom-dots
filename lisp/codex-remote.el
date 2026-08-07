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

(defvar-local my/codex-remote-bootstrap-cmd nil
  "Optional command used to prepare a new Codex worktree.

When nil, `my/remote-setup-cmd' is used.  The command runs once before Codex and
must leave all nonignored repository files unchanged.")

(defvar-local my/codex-remote-test-cmd nil
  "Optional command run after Codex finishes.

When nil, `my/remote-test-cmd' is used.")

(defvar-local my/codex-remote-data-links nil
  "Remote data links exposed inside the isolated Codex worktree.

Each entry has the form REMOTE-ABSOLUTE-PATH=WORKTREE-RELATIVE-PATH.  The
backend creates temporary symlinks, excludes them from the result commit, and
verifies that Codex did not replace them.")

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

(defun my/codex-remote--task-lines (task)
  "Return human-readable status lines for TASK."
  (if (or (null task)
          (equal (my/codex-remote--get task 'state) "NONE"))
      '("State: NONE" "No remote Codex task exists for this project.")
    (let* ((tests (my/codex-remote--get task 'tests))
           (tmux (my/codex-remote--get task 'tmux))
           (fields
            `(("State" . ,(my/codex-remote--get task 'state))
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
         (command (my/codex-remote--common-args "doctor" context)))
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

(defun my/codex-remote--start-command (context)
  "Build the start command for CONTEXT."
  (let ((command (my/codex-remote--common-args "start" context)))
    (setq command (append command '("--prompt-file" "-")))
    (when-let ((value (plist-get context :bootstrap)))
      (setq command (append command (list "--bootstrap-cmd" value))))
    (when-let ((value (plist-get context :test)))
      (setq command (append command (list "--test-cmd" value))))
    (dolist (link (plist-get context :data-links))
      (setq command (append command (list "--data-link" link))))
    (when-let ((value (plist-get context :model)))
      (setq command (append command (list "--model" value))))
    (when-let ((value (plist-get context :profile)))
      (setq command (append command (list "--profile" value))))
    (when-let ((value (plist-get context :reasoning)))
      (setq command (append command (list "--reasoning-effort" value))))
    (when (plist-get context :search)
      (setq command (append command '("--enable-search"))))
    command))

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

(defun my/codex-remote-start (&optional edit-prompt)
  "Start a durable remote Codex task.

Use the active region as the prompt when present.  With prefix EDIT-PROMPT,
open a multiline prompt buffer; otherwise read a short prompt in the minibuffer."
  (interactive "P")
  (let ((context (my/codex-remote--context)))
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
       (read-string "Remote Codex task: "))))))

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

(defun my/codex-remote--external-terminal-executable ()
  "Return the configured external terminal executable."
  (let ((program (car my/codex-remote-external-terminal-command)))
    (unless (and (stringp program) (not (string-empty-p program)))
      (user-error
       "Set my/codex-remote-external-terminal-command to a nonempty command"))
    (or (and (file-name-absolute-p program)
             (file-executable-p program)
             program)
        (and (fboundp 'my/process-path--find-executable)
             (my/process-path--find-executable program))
        (executable-find program)
        (user-error "Could not find external terminal executable: %s" program))))

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
         (tmux (my/codex-remote--get task 'tmux)))
    (unless session
      (user-error "Task %s has no tmux session" state))
    (unless (my/codex-remote--get tmux 'exists)
      (user-error "Task %s has no tmux session; use SPC r c l for logs" state))
    (when (my/codex-remote--get tmux 'pane_dead)
      (user-error
       "Task %s has already exited%s; use SPC r c l for logs"
       state
       (if-let ((status (my/codex-remote--get tmux 'pane_dead_status)))
           (format " with status %s" status)
         "")))
    session))

(defun my/codex-remote--open-tmux (context task)
  "Monitor TASK's live tmux pane in Emacs's built-in terminal emulator."
  (let* ((session (my/codex-remote--require-live-tmux task))
         (task-id (my/codex-remote--get task 'task_id)))
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

(defun my/codex-remote-interactive ()
  "Open the current live Codex tmux session in an external terminal.

The attachment is read-write.  Closing the terminal or losing SSH detaches the
client only; the server-side tmux session and Codex task continue running."
  (interactive)
  (let* ((context (my/codex-remote--context))
         (command (my/codex-remote--common-args "status" context)))
    (my/codex-remote--run
     "interactive" command context
     :on-success
     (lambda (response buffer)
       (kill-buffer buffer)
       (let ((task (my/codex-remote--get response 'task)))
         (when (equal (my/codex-remote--get task 'state) "NONE")
           (user-error "No remote Codex task exists for this project"))
         (my/codex-remote--open-external-tmux context task))))))

(defun my/codex-remote--apply-error (response buffer)
  "Handle apply failure RESPONSE from BUFFER."
  (if (equal (my/codex-remote--error-code response) "INTEGRATION_CONFLICT")
      (let* ((details (my/codex-remote--get response 'details))
             (path (my/codex-remote--get details 'conflict_path)))
        (my/codex-remote--display-raw-error buffer response)
        (when (and path (file-directory-p path))
          (require 'magit)
          (magit-status-setup-buffer path)))
    (my/codex-remote--display-raw-error buffer response)))

(defun my/codex-remote-apply (&optional allow-branch-change)
  "Fetch and apply a completed Codex delta as unstaged local changes.

With prefix ALLOW-BRANCH-CHANGE, deliberately apply a task that started on a
different branch to the currently checked-out branch."
  (interactive "P")
  (let* ((context (my/codex-remote--context))
         (root (plist-get context :root))
         (command (my/codex-remote--common-args "apply" context)))
    (my/codex-remote--save-project-buffers root)
    (when allow-branch-change
      (setq command (append command '("--allow-branch-change"))))
    (my/codex-remote--run
     "apply" command context
     :on-success
     (lambda (response buffer)
       (kill-buffer buffer)
       (when (fboundp 'magit-refresh-all)
         (magit-refresh-all))
       (message "%s" (or (my/codex-remote--get response 'message)
                          "Remote Codex result imported")))
     :on-error #'my/codex-remote--apply-error)))

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

(defconst my/codex-remote--importable-states
  '("READY" "READY_TESTS_FAILED" "READY_CODEX_FAILED"
    "READY_TESTS_DIRTY" "READY_ENVIRONMENT_FAILED"
    "READY_ENVIRONMENT_DIRTY" "READY_ENVIRONMENT_UNVERIFIED"
    "CANCELLED_READY" "NOOP" "CANCELLED_NOOP")
  "Remote states that have a result or acknowledged no-op ready for import.")

(defun my/codex-remote--notify-after-sync (&rest _)
  "Nonblockingly report a completed Codex task after ordinary `SPC r s'."
  (condition-case nil
      (let* ((context (my/codex-remote--context))
             (command (my/codex-remote--common-args "status" context)))
        (my/codex-remote--run
         "sync-check" command context
         :quiet t
         :on-success
         (lambda (response buffer)
           (when (buffer-live-p buffer)
             (kill-buffer buffer))
           (let* ((task (my/codex-remote--get response 'task))
                  (state (my/codex-remote--get task 'state)))
             (when (member state my/codex-remote--importable-states)
               (message "Remote Codex task is %s; use SPC r c f to import it before the next sync/run"
                        state))))
         :on-error
         (lambda (_response buffer)
           (when (buffer-live-p buffer)
             (kill-buffer buffer)))))
    (error nil)))

(when (and (fboundp 'my/project-sync)
           (not (advice-member-p #'my/codex-remote--notify-after-sync
                                 #'my/project-sync)))
  (advice-add #'my/project-sync :after #'my/codex-remote--notify-after-sync))

(provide 'codex-remote)
