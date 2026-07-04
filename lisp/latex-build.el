;;; lisp/latex-build.el -*- lexical-binding: t; -*-

(after! tex
  (require 'compile)

  (setq TeX-save-query nil)
  (setq-default TeX-master t)
  (when (assoc "LaTeXMk" TeX-command-list)
    (setq-default TeX-command-default "LaTeXMk"))

  (defun my/latex--standalone-document-p ()
    "Return non-nil when the current buffer declares a document class."
    (save-excursion
      (save-restriction
        (widen)
        (goto-char (point-min))
        (re-search-forward
         "^[[:space:]]*\\\\documentclass\\b" nil t))))

  (defun my/latex--master-file ()
    "Return the absolute master TeX file for the current buffer."
    (unless buffer-file-name
      (user-error "This buffer is not visiting a file"))
    (let* ((file (expand-file-name buffer-file-name))
           (directory (file-name-directory file))
           (configured-master
            (when (and (boundp 'TeX-master)
                       (stringp TeX-master)
                       (not (member TeX-master '("" "<none>"))))
              (let ((candidate (expand-file-name TeX-master directory)))
                (if (file-name-extension candidate)
                    candidate
                  (concat candidate ".tex")))))
           (root (locate-dominating-file directory "main.tex")))
      (cond
       ((my/latex--standalone-document-p) file)
       ((and configured-master (file-readable-p configured-master))
        configured-master)
       (root (expand-file-name "main.tex" root))
       (t file))))

  (defun my/latex--project-root (directory)
    "Return the project root containing DIRECTORY."
    (file-name-as-directory
     (or (when (fboundp 'projectile-project-root)
           (let ((default-directory directory))
             (ignore-errors (projectile-project-root))))
         (locate-dominating-file directory ".git")
         directory)))

  (defun my/latex--configure-master-h ()
    "Configure AUCTeX to compile the resolved master document."
    (when buffer-file-name
      (let* ((file (expand-file-name buffer-file-name))
             (master (my/latex--master-file)))
        (setq-local
         TeX-master
         (if (file-equal-p file master)
             t
           (file-name-sans-extension
            (file-relative-name master (file-name-directory file)))))))
    (when (assoc "LaTeXMk" TeX-command-list)
      (setq-local TeX-command-default "LaTeXMk"))
    (when (fboundp 'TeX-PDF-mode)
      (TeX-PDF-mode 1)))

  ;; Configure both AUCTeX's mode and Emacs's built-in fallback mode.
  (add-hook 'LaTeX-mode-hook #'my/latex--configure-master-h)
  (add-hook 'latex-mode-hook #'my/latex--configure-master-h)

  (defun my/latex--save-project-buffers (directory)
    "Save modified TeX project buffers below DIRECTORY."
    (dolist (buffer (buffer-list))
      (with-current-buffer buffer
        (when (and buffer-file-name
                   (buffer-modified-p)
                   (file-in-directory-p
                    (expand-file-name buffer-file-name) directory)
                   (member (downcase
                            (or (file-name-extension buffer-file-name) ""))
                           '("tex" "bib" "sty" "cls" "bst")))
          (save-buffer)))))

  (defun my/latex--show-pdf-right (pdf frame)
    "Reload PDF and display it in a right-side window on FRAME."
    (let* ((pdf (file-truename pdf))
           (existing-buffer (get-file-buffer pdf))
           (pdf-buffer (or existing-buffer (find-file-noselect pdf)))
           (frame (if (frame-live-p frame) frame (selected-frame))))
      (when existing-buffer
        (with-current-buffer pdf-buffer
          (ignore-errors (revert-buffer nil t))))
      (with-selected-frame frame
        (save-selected-window
          (let ((window
                 (or (display-buffer-in-side-window
                      pdf-buffer
                      '((side . right)
                        (slot . 0)
                        (window-width . 0.48)
                        (preserve-size . (t . nil))))
                     (display-buffer pdf-buffer))))
            (when (and (window-live-p window)
                       (not existing-buffer)
                       (fboundp 'pdf-view-fit-width-to-window))
              (with-selected-window window
                (when (derived-mode-p 'pdf-view-mode)
                  (pdf-view-fit-width-to-window)))))))))

  (defvar-local my/latex--output-pdf nil)
  (defvar-local my/latex--source-frame nil)

  (defun my/latex--compilation-finished-h (buffer status)
    "Show the generated PDF when BUFFER finishes successfully with STATUS."
    (when (buffer-live-p buffer)
      (with-current-buffer buffer
        (let ((pdf my/latex--output-pdf)
              (frame my/latex--source-frame))
          (if (and (string-prefix-p "finished" status)
                   pdf
                   (file-readable-p pdf))
              (progn
                (when (frame-live-p frame)
                  (ignore-errors (delete-windows-on buffer frame)))
                (my/latex--show-pdf-right pdf frame)
                (message "LaTeX build finished: %s"
                         (abbreviate-file-name pdf)))
            (when (frame-live-p frame)
              (with-selected-frame frame
                (display-buffer buffer)))
            (message "LaTeX build failed; see %s" (buffer-name buffer)))))))

  (defun my/latex--executable-path (latexmk)
    "Return a PATH containing LATEXMK's directory and `exec-path'."
    (let ((directories
           (append (list (file-name-directory latexmk))
                   exec-path
                   (parse-colon-path (or (getenv "PATH") ""))))
          result)
      (dolist (directory directories)
        (when (and (stringp directory)
                   (not (string= directory "")))
          (let ((directory
                 (directory-file-name (expand-file-name directory))))
            (unless (member directory result)
              (push directory result)))))
      (mapconcat #'identity (nreverse result) path-separator)))

  (defun my/latex--latexmk-invocation (latexmk args)
    "Return a shell-quoted LATEXMK invocation with ARGS."
    (mapconcat #'shell-quote-argument (cons latexmk args) " "))

  (defun my/latex--latexmk-command (latexmk master)
    "Return a recoverable latexmk command that compiles MASTER."
    (let* ((common-args
            (list "-pdf"
                  "-bibtex"
                  "-interaction=nonstopmode"
                  "-file-line-error"
                  "-synctex=1"
                  "-halt-on-error"
                  "-cd"
                  master))
           ;; Retry the TeX engine even when latexmk cached a failed prior run.
           (incremental-command
            (my/latex--latexmk-invocation latexmk (cons "-gt" common-args)))
           ;; If the incremental run fails, stale aux/output files are a
           ;; common cause.  Rebuild from a clean state once before surfacing
           ;; the error to the user.
           (clean-command
            (my/latex--latexmk-invocation latexmk (cons "-gg" common-args))))
      (mapconcat
       #'identity
       (list incremental-command
             "latexmk_rc=$?"
             "if [ \"$latexmk_rc\" -eq 0 ]; then exit 0; fi"
             "if [ \"$latexmk_rc\" -ge 128 ]; then exit \"$latexmk_rc\"; fi"
             "printf '\nlatexmk: incremental build failed with status %d; forcing a clean, complete rebuild\n' \"$latexmk_rc\" >&2"
             clean-command
             "latexmk_rc=$?"
             "if [ \"$latexmk_rc\" -ne 0 ]; then printf '\nlatexmk: clean rebuild failed with status %d; preserving diagnostics\n' \"$latexmk_rc\" >&2; fi"
             "exit \"$latexmk_rc\"")
       "; ")))

  (defun my/latex--compile-master (master)
    "Compile MASTER with latexmk and show its PDF on the right."
    (let* ((master (expand-file-name master))
           (directory (file-name-directory master))
           (project-root (my/latex--project-root directory))
           (pdf (concat (file-name-sans-extension master) ".pdf"))
           (latexmk (executable-find "latexmk"))
           (frame (selected-frame)))
      (unless (and (file-regular-p master)
                   (file-readable-p master)
                   (string-equal (downcase (or (file-name-extension master) ""))
                                 "tex"))
        (user-error "Not a readable TeX file: %s" master))
      (unless latexmk
        (user-error "latexmk is not available in Emacs's PATH"))
      (my/latex--save-project-buffers project-root)
      (let* ((default-directory directory)
             (compilation-always-kill t)
             (process-environment (copy-sequence process-environment))
             (command (my/latex--latexmk-command latexmk master))
             (compilation-start-hook
              (cons
               (lambda (process)
                 (with-current-buffer (process-buffer process)
                   (setq-local my/latex--output-pdf pdf
                               my/latex--source-frame frame)
                   (add-hook 'compilation-finish-functions
                             #'my/latex--compilation-finished-h nil t)))
               compilation-start-hook)))
        ;; `executable-find' searches `exec-path', but latexmk's child
        ;; processes search PATH.  Keep those two views of the TeX toolchain
        ;; synchronized so BibTeX/Biber and the LaTeX engine are reachable.
        (setenv "PATH" (my/latex--executable-path latexmk))
        (compilation-start
         command
         'compilation-mode
         (lambda (_mode)
           (format "*latexmk %s/%s output*"
                   (file-name-nondirectory
                    (directory-file-name directory))
                   (file-name-base master)))))))

  (defun my/latex-compile-and-view ()
    "Compile the resolved master and show its PDF on the right."
    (interactive)
    (my/latex--configure-master-h)
    (my/latex--compile-master (my/latex--master-file)))

  (defun my/latex-compile-other-file (master)
    "Prompt for another TeX MASTER in this project and compile it."
    (interactive
     (let* ((directory (if buffer-file-name
                           (file-name-directory buffer-file-name)
                         default-directory))
            (root (my/latex--project-root directory)))
       (list
        (read-file-name
         "Compile TeX file: " root nil t nil
         (lambda (candidate)
           (or (file-directory-p candidate)
               (and (file-regular-p candidate)
                    (string-equal
                     (downcase (or (file-name-extension candidate) ""))
                     "tex"))))))))
    (my/latex--compile-master master))

  (map! :map latex-mode-map
        :localleader
        :desc "Compile and view" "c" #'my/latex-compile-and-view
        :desc "Compile another TeX file" "C" #'my/latex-compile-other-file)
  (map! :after latex
        :map LaTeX-mode-map
        :localleader
        :desc "Compile and view" "c" #'my/latex-compile-and-view
        :desc "Compile another TeX file" "C" #'my/latex-compile-other-file))
