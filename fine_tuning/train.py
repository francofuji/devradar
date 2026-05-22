"""
E18.T4 — Script de fine-tuning principal.

Uso:
    python fine_tuning/train.py --task narrative [--base-model llama3.1:8b] [--epochs 3]

Flujo:
    1. prepare_dataset.py  →  train/eval JSONL
    2. Fine-tuning con unsloth+QLoRA (si disponible) o transformers+trl (CPU fallback)
    3. Exporta a GGUF  →  fine_tuning/models/{task}_{date}/
    4. evaluate.py     →  métricas finales
    5. PostgreSQL NOTIFY para progreso en la UI

Variables de entorno:
    DATABASE_URL   — PostgreSQL (para NOTIFY y lectura de ejemplos)
    OLLAMA_HOST    — para paso de evaluación con Ollama
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from fine_tuning.prepare_dataset import prepare
from fine_tuning.evaluate import evaluate

MODELS_DIR = _project_root / "fine_tuning" / "models"


# ── PostgreSQL NOTIFY helpers ────────────────────────────────────────────────

def _pg_notify(event_type: str, payload: dict) -> None:
    """Emite NOTIFY en dev_intel_events para que el SSE lo propague al browser."""
    try:
        from db import db_cursor
        body = json.dumps({"type": event_type, **payload}, ensure_ascii=True)
        with db_cursor() as cur:
            cur.execute("SELECT pg_notify('dev_intel_events', %s)", (body,))
    except Exception as exc:
        print(f"[train] pg_notify failed (non-fatal): {exc}", file=sys.stderr)


def _progress(task: str, step: str, pct: int, msg: str) -> None:
    print(f"[train/{task}] {pct:3d}%  {step}: {msg}")
    _pg_notify("training_progress", {"task": task, "step": step, "pct": pct, "msg": msg})


# ── Unsloth / transformers fine-tuning ──────────────────────────────────────

def _try_unsloth(
    task: str, base_model: str, epochs: int,
    train_path: Path, eval_path: Path, output_dir: Path,
) -> bool:
    """Intenta fine-tuning con unsloth. Retorna True si lo logró, False si no está disponible."""
    try:
        from unsloth import FastLanguageModel  # type: ignore
        import torch
    except ImportError:
        return False

    _progress(task, "unsloth_load", 20, f"Cargando {base_model} con unsloth…")

    max_seq_length = 2048
    model, tokenizer = FastLanguageModel.from_pretrained(
        model_name=base_model,
        max_seq_length=max_seq_length,
        dtype=None,
        load_in_4bit=True,
    )
    model = FastLanguageModel.get_peft_model(
        model,
        r=16,
        target_modules=["q_proj", "k_proj", "v_proj", "o_proj",
                        "gate_proj", "up_proj", "down_proj"],
        lora_alpha=16,
        lora_dropout=0,
        bias="none",
        use_gradient_checkpointing="unsloth",
        random_state=42,
    )

    from datasets import load_dataset  # type: ignore
    from trl import SFTTrainer  # type: ignore
    from transformers import TrainingArguments  # type: ignore

    train_dataset = load_dataset("json", data_files=str(train_path), split="train")
    eval_dataset  = load_dataset("json", data_files=str(eval_path),  split="train")

    _progress(task, "unsloth_train", 35, f"Entrenando {epochs} épocas ({len(train_dataset)} ejemplos)…")

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        dataset_text_field="messages",
        max_seq_length=max_seq_length,
        args=TrainingArguments(
            output_dir=str(output_dir / "checkpoints"),
            num_train_epochs=epochs,
            per_device_train_batch_size=2,
            gradient_accumulation_steps=4,
            warmup_steps=5,
            learning_rate=2e-4,
            fp16=not torch.cuda.is_bf16_supported(),
            bf16=torch.cuda.is_bf16_supported(),
            logging_steps=10,
            save_strategy="epoch",
            eval_strategy="epoch",
            report_to="none",
        ),
    )
    trainer.train()

    _progress(task, "unsloth_save", 70, "Exportando a GGUF q4_k_m…")
    model.save_pretrained_gguf(str(output_dir), tokenizer, quantization_method="q4_k_m")

    _progress(task, "unsloth_done", 80, "GGUF listo.")
    return True


def _train_transformers(
    task: str, base_model: str, epochs: int,
    train_path: Path, eval_path: Path, output_dir: Path,
) -> None:
    """Fallback CPU: fine-tuning con transformers + trl (LoRA via peft si disponible)."""
    try:
        from transformers import AutoModelForCausalLM, AutoTokenizer, TrainingArguments  # type: ignore
        from trl import SFTTrainer  # type: ignore
        from datasets import load_dataset  # type: ignore
    except ImportError as exc:
        raise RuntimeError(
            f"transformers/trl/datasets no instalados en este entorno: {exc}\n"
            "Ejecuta desde el container fine_tuning: docker compose run fine_tuning python fine_tuning/train.py ..."
        ) from exc

    _progress(task, "transformers_load", 20, f"Cargando {base_model} con transformers (CPU)…")

    # Para CPU, usamos un modelo más pequeño si el base_model no está disponible localmente.
    # Si el modelo base es un nombre Ollama (ej. llama3.1:8b), lo convertimos al HF equivalente.
    hf_model_map = {
        "llama3.1:8b":  "meta-llama/Llama-3.1-8B-Instruct",
        "llama3.1:70b": "meta-llama/Llama-3.1-70B-Instruct",
        "qwen2.5:7b":   "Qwen/Qwen2.5-7B-Instruct",
        "qwen2.5:14b":  "Qwen/Qwen2.5-14B-Instruct",
        "mistral:7b":   "mistralai/Mistral-7B-Instruct-v0.3",
    }
    hf_name = hf_model_map.get(base_model, base_model)

    try:
        tokenizer = AutoTokenizer.from_pretrained(hf_name, trust_remote_code=True)
        model = AutoModelForCausalLM.from_pretrained(
            hf_name, trust_remote_code=True, torch_dtype="auto", device_map="auto"
        )
    except Exception as exc:
        raise RuntimeError(
            f"No se pudo cargar el modelo {hf_name!r}. "
            f"Asegúrate de tener HF_TOKEN configurado y acceso al modelo: {exc}"
        ) from exc

    train_dataset = load_dataset("json", data_files=str(train_path), split="train")
    eval_dataset  = load_dataset("json", data_files=str(eval_path),  split="train")

    _progress(task, "transformers_train", 35, f"Entrenando {epochs} épocas ({len(train_dataset)} ejemplos, CPU)…")

    trainer = SFTTrainer(
        model=model,
        tokenizer=tokenizer,
        train_dataset=train_dataset,
        eval_dataset=eval_dataset,
        dataset_text_field="messages",
        max_seq_length=1024,
        args=TrainingArguments(
            output_dir=str(output_dir / "checkpoints"),
            num_train_epochs=epochs,
            per_device_train_batch_size=1,
            gradient_accumulation_steps=8,
            warmup_steps=2,
            learning_rate=2e-4,
            fp16=False,
            bf16=False,
            logging_steps=5,
            save_strategy="epoch",
            eval_strategy="epoch",
            report_to="none",
            no_cuda=True,
        ),
    )
    trainer.train()

    _progress(task, "transformers_save", 70, "Guardando modelo fine-tuneado…")
    model.save_pretrained(str(output_dir / "ft_model"))
    tokenizer.save_pretrained(str(output_dir / "ft_model"))

    # Intentar exportar a GGUF con llama.cpp si está disponible
    gguf_path = output_dir / f"{task}.gguf"
    try:
        import subprocess
        result = subprocess.run(
            ["python", "-m", "llama_cpp.convert",
             str(output_dir / "ft_model"), "--outfile", str(gguf_path),
             "--outtype", "q4_0"],
            capture_output=True, text=True, timeout=600,
        )
        if result.returncode == 0:
            _progress(task, "gguf_export", 78, f"GGUF exportado: {gguf_path.name}")
        else:
            _progress(task, "gguf_skip", 78, "GGUF no exportado (llama.cpp no disponible) — se usa ft_model/")
    except Exception:
        _progress(task, "gguf_skip", 78, "GGUF no exportado — se usa ft_model/")


# ── Main ─────────────────────────────────────────────────────────────────────

def train(
    task: str,
    base_model: str = "llama3.1:8b",
    epochs: int = 3,
    min_quality: float = 0.7,
) -> dict:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_dir = MODELS_DIR / f"{task}_{stamp}"
    output_dir.mkdir(parents=True, exist_ok=True)

    _progress(task, "start", 0, f"Iniciando fine-tuning  base={base_model}  epochs={epochs}")

    # 1. Preparar dataset
    _progress(task, "prepare", 5, "Preparando dataset desde PostgreSQL…")
    stats = prepare(task=task, min_quality=min_quality)

    if stats["train"] == 0:
        msg = f"Sin ejemplos suficientes (total={stats['total']}). Necesitas al menos 1 ejemplo de entrenamiento."
        _pg_notify("training_failed", {"task": task, "error": msg})
        raise RuntimeError(msg)

    train_path = Path(stats["train_path"])
    eval_path  = Path(stats["eval_path"])
    _progress(task, "prepare_done", 15, f"Dataset listo: {stats['train']} train, {stats['eval']} eval")

    # 2. Fine-tuning
    used_unsloth = _try_unsloth(task, base_model, epochs, train_path, eval_path, output_dir)
    if not used_unsloth:
        _progress(task, "fallback", 18, "unsloth no disponible — usando transformers CPU")
        _train_transformers(task, base_model, epochs, train_path, eval_path, output_dir)

    # 3. Evaluación
    _progress(task, "evaluate", 82, "Evaluando sobre eval set…")
    metrics = evaluate(task=task, eval_file=str(eval_path))
    metrics["output_dir"] = str(output_dir)
    metrics["base_model"] = base_model
    metrics["epochs"]     = epochs
    metrics["stamp"]      = stamp
    metrics["train_examples"] = stats["train"]

    # Guardar métricas JSON en el output dir
    (output_dir / "metrics.json").write_text(json.dumps(metrics, indent=2), encoding="utf-8")

    _progress(task, "done", 95,
              f"Completado. rouge_l={metrics.get('rouge_l')}  evidence_rate={metrics.get('evidence_rate')}")

    # 4. Notificar finalización
    _pg_notify("training_completed", {
        "task":        task,
        "output_dir":  str(output_dir),
        "metrics":     metrics,
        "stamp":       stamp,
    })

    print(f"\n[train] Resultado final:")
    print(json.dumps(metrics, indent=2))
    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Fine-tuning con unsloth+QLoRA o transformers+trl")
    parser.add_argument("--task",        required=True, choices=["narrative", "draft", "extraction"])
    parser.add_argument("--base-model",  default="llama3.1:8b")
    parser.add_argument("--epochs",      type=int, default=3)
    parser.add_argument("--min-quality", type=float, default=0.7)
    args = parser.parse_args()

    train(
        task=args.task,
        base_model=args.base_model,
        epochs=args.epochs,
        min_quality=args.min_quality,
    )


if __name__ == "__main__":
    main()
