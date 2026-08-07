;;; -*- lexical-binding: t -*-
(custom-set-variables
 ;; custom-set-variables was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 '(safe-local-variable-directories
   '("/home/nix/Documents/Research/statistical-adversaries/"
     "/home/nix/.config/doom/" "~/.config/emacs/"))
 '(safe-local-variable-values
   '((my/remote-sync-excludes ".direnv/" ".venv/" "__pycache__/" ".mypy_cache/"
      ".pytest_cache/" ".ruff_cache/" ".cache/" ".nix-driver-libs/" "wandb/"
      "results/" "outputs/" "checkpoint-*/" "*.pyc" "*.pt" "*.bin"
      "*.safetensors")
     (my/remote-run-cmd
      . "nix develop .#server --command bash -lc 'CUDA_VISIBLE_DEVICES=0 uv run --no-sync python run.py --do_train --do_eval --task qa --dataset squad --output_dir results/squad_seed42 --overwrite_output_dir --max_length 384 --per_device_train_batch_size 32 --per_device_eval_batch_size 64 --num_train_epochs 3 --save_only_final_model --save_dynamics --fp16 --seed 42 --report_to none'")
     (my/remote-smoke-cmd
      . "nix develop .#server --command bash -lc 'CUDA_VISIBLE_DEVICES=0 scripts/run_qa_smoke.sh'")
     (my/remote-test-cmd
      . "nix develop .#server --command bash -lc 'uv run --no-sync pytest'")
     (my/remote-setup-cmd
      . "nix develop .#server --command bash -lc 'uv sync --frozen --extra cuda --group dev'")
     (my/remote-dir . "/home/rhel/Projects/dataset-artifacts")
     (my/remote-host . "rhel-test"))))
(custom-set-faces
 ;; custom-set-faces was added by Custom.
 ;; If you edit it by hand, you could mess it up, so be careful.
 ;; Your init file should contain only one such instance.
 ;; If there is more than one, they won't work right.
 )
