"""
E18.T5 — Deploy del modelo fine-tuneado a Ollama y registro en model_registry.

Uso:
    python fine_tuning/deploy.py --task narrative --model-dir fine_tuning/models/narrative_20260521_123456

Flujo:
    1. Busca el archivo GGUF (o ft_model/) en model-dir
    2. Genera un Modelfile para Ollama
    3. Corre `ollama create dev-intelligence-{task}-{stamp}`
    4. Verifica que el modelo aparece en `ollama list`
    5. Actualiza config.toml con el nuevo nombre de modelo
    6. Registra en model_registry en PostgreSQL
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

CONFIG_PATH = _project_root / "config.toml"


# ── TOML helpers (evita dependencia de tomli en este script standalone) ──────

def _load_config() -> dict:
    try:
        import tomllib
    except ModuleNotFoundError:
        import tomli as tomllib  # type: ignore[no-redef]
    with CONFIG_PATH.open("rb") as fh:
        return tomllib.load(fh)


def _toml_scalar(value) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if value is None:
        return '""'
    if isinstance(value, str):
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    if isinstance(value, list):
        return "[" + ", ".join(_toml_scalar(i) for i in value) + "]"
    raise TypeError(f"TOML type not supported: {type(value)!r}")


def _dump_toml(data: dict, prefix: list | None = None) -> str:
    prefix = prefix or []
    scalars, tables = [], []
    for k, v in data.items():
        if isinstance(v, dict):
            header = ".".join(prefix + [k])
            tables.append(f"[{header}]")
            tables.append(_dump_toml(v, prefix + [k]).strip())
            tables.append("")
        else:
            scalars.append(f"{k} = {_toml_scalar(v)}")
    return "\n".join([*scalars, *tables]).strip() + "\n"


# ── Modelfile template ───────────────────────────────────────────────────────

MODELFILE_TEMPLATE = """\
FROM {gguf_path}

PARAMETER temperature 0.2
PARAMETER top_p 0.9
PARAMETER num_predict 512
PARAMETER stop "<|eot_id|>"
PARAMETER stop "<|end_of_text|>"

SYSTEM \"\"\"
You are a specialized AI assistant fine-tuned for developer intelligence analysis.
Task: {task}
Be concise, factual, and cite explicit evidence from the developer's repositories.
\"\"\"
"""


# ── Ollama helpers ───────────────────────────────────────────────────────────

def _ollama_list() -> list[str]:
    """Retorna lista de nombres de modelos instalados en Ollama."""
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    import urllib.request
    try:
        with urllib.request.urlopen(f"{ollama_host}/api/tags", timeout=10) as resp:
            data = json.loads(resp.read().decode())
            return [m["name"] for m in data.get("models", [])]
    except Exception as exc:
        print(f"[deploy] ollama list failed: {exc}", file=sys.stderr)
        return []


def _ollama_create(model_name: str, modelfile_path: Path) -> bool:
    """Ejecuta `ollama create`. Retorna True si tuvo éxito."""
    result = subprocess.run(
        ["ollama", "create", model_name, "--file", str(modelfile_path)],
        capture_output=True, text=True, timeout=300,
    )
    if result.returncode != 0:
        print(f"[deploy] ollama create failed:\n{result.stderr}", file=sys.stderr)
        return False
    print(f"[deploy] ollama create OK: {model_name}")
    return True


# ── Registro en PostgreSQL ───────────────────────────────────────────────────

def _register_model(
    task: str, model_name: str, base_model: str,
    training_examples: int, eval_rouge_l: float | None,
    notes: str,
) -> str:
    from db import db_cursor
    with db_cursor() as cur:
        cur.execute(
            """
            INSERT INTO model_registry (task_type, model_name, base_model, training_examples, eval_rouge_l, notes)
            VALUES (%s, %s, %s, %s, %s, %s)
            RETURNING id
            """,
            (task, model_name, base_model, training_examples, eval_rouge_l, notes),
        )
        row = cur.fetchone()
    model_id = str(row["id"])
    print(f"[deploy] model_registry  id={model_id}")
    return model_id


# ── Actualizar config.toml ───────────────────────────────────────────────────

def _update_config(task: str, model_name: str) -> None:
    config = _load_config()
    llm = dict(config.get("llm", {}))
    llm[f"ollama_model_{task}"] = model_name
    config["llm"] = llm
    CONFIG_PATH.write_text(_dump_toml(config), encoding="utf-8")
    print(f"[deploy] config.toml actualizado: ollama_model_{task} = {model_name!r}")


# ── Main ─────────────────────────────────────────────────────────────────────

def deploy(task: str, model_dir: str) -> dict:
    model_path = Path(model_dir)
    if not model_path.exists():
        raise FileNotFoundError(f"model_dir no existe: {model_dir}")

    # Cargar métricas de training si existen
    metrics_file = model_path / "metrics.json"
    metrics = {}
    if metrics_file.exists():
        metrics = json.loads(metrics_file.read_text(encoding="utf-8"))

    stamp = metrics.get("stamp") or datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_model = metrics.get("base_model", "unknown")
    training_examples = metrics.get("train_examples", 0)
    rouge_l = metrics.get("rouge_l")

    # Buscar GGUF
    gguf_files = list(model_path.glob("*.gguf"))
    if not gguf_files:
        # Buscar en ft_model/
        ft_model_dir = model_path / "ft_model"
        if not ft_model_dir.exists():
            raise FileNotFoundError(f"No se encontró GGUF ni ft_model/ en {model_dir}")
        # Sin GGUF no podemos crear modelo Ollama directamente — señalamos que es solo HF
        print("[deploy] ADVERTENCIA: No hay GGUF. El modelo está en ft_model/ (formato HF).")
        print("[deploy] Para importar a Ollama necesitas exportar manualmente a GGUF con llama.cpp.")
        gguf_path = ft_model_dir / "config.json"  # placeholder
        has_gguf = False
    else:
        gguf_path = gguf_files[0]
        has_gguf = True
        print(f"[deploy] GGUF encontrado: {gguf_path.name}")

    model_name = f"dev-intelligence-{task}-{stamp}"

    if has_gguf:
        # Generar Modelfile
        modelfile_content = MODELFILE_TEMPLATE.format(
            gguf_path=str(gguf_path),
            task=task,
        )
        modelfile_path = model_path / "Modelfile"
        modelfile_path.write_text(modelfile_content, encoding="utf-8")
        print(f"[deploy] Modelfile escrito: {modelfile_path}")

        # Crear modelo en Ollama
        ok = _ollama_create(model_name, modelfile_path)
        if not ok:
            raise RuntimeError(f"Fallo al crear modelo Ollama: {model_name}")

        # Verificar que aparece en ollama list
        available = _ollama_list()
        verified = any(model_name in m for m in available)
        if verified:
            print(f"[deploy] ✓ Modelo verificado en Ollama: {model_name}")
        else:
            print(f"[deploy] ADVERTENCIA: {model_name} no aparece en ollama list aún.")
    else:
        print(f"[deploy] Saltando ollama create (sin GGUF). Registro solo en model_registry.")
        verified = False

    # Registrar en PostgreSQL
    notes = f"trained={stamp}  base={base_model}  rouge_l={rouge_l}"
    model_id = _register_model(
        task=task,
        model_name=model_name,
        base_model=base_model,
        training_examples=training_examples,
        eval_rouge_l=rouge_l,
        notes=notes,
    )

    # Actualizar config.toml si GGUF verificado
    if verified:
        _update_config(task, model_name)

    result = {
        "ok": True,
        "model_name": model_name,
        "model_id": model_id,
        "has_gguf": has_gguf,
        "verified_in_ollama": verified,
        "task": task,
        "stamp": stamp,
        "metrics": metrics,
    }
    print(f"[deploy] ✓ Deploy completo: {model_name}  id={model_id}")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Deploy modelo fine-tuneado a Ollama")
    parser.add_argument("--task", required=True, choices=["narrative", "draft", "extraction"])
    parser.add_argument("--model-dir", required=True,
                        help="Directorio de salida de train.py (ej. fine_tuning/models/narrative_20260521_123456)")
    args = parser.parse_args()

    result = deploy(task=args.task, model_dir=args.model_dir)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
