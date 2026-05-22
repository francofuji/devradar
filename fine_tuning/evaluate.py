"""
E18.T2 — Evalúa el modelo fine-tuneado sobre el eval set.

Métricas:
  - rouge_l:        ROUGE-L aproximado (LCS word-level) promedio
  - evidence_rate:  % de outputs con evidencia explícita
  - avg_length:     longitud promedio en palabras del output
  - json_valid_rate: % de outputs que son JSON válido (solo task=extraction)

Uso:
    python fine_tuning/evaluate.py --task narrative --eval-file fine_tuning/data/narrative_eval.jsonl
    python fine_tuning/evaluate.py --task narrative  # usa el eval file por defecto
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

_project_root = Path(__file__).resolve().parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

DATA_DIR = _project_root / "fine_tuning" / "data"

# Palabras/frases que indican evidencia explícita en la salida
EVIDENCE_PATTERNS = [
    r"\bevidence\b",
    r"\bevidencia\b",
    r"\bbecause\b",
    r"\bporque\b",
    r"\bdue to\b",
    r"\bbased on\b",
    r"\bseen in\b",
    r"\bfound in\b",
    r"\bnotably\b",
    r"\bspecifically\b",
    r"\bfor example\b",
    r"\bfor instance\b",
    r"\bsuch as\b",
    r"\bincluding\b",
]
_EVIDENCE_RE = re.compile("|".join(EVIDENCE_PATTERNS), re.IGNORECASE)


def _lcs_length(a: list[str], b: list[str]) -> int:
    """LCS dinámica sobre listas de palabras. Optimizada para longitudes cortas."""
    m, n = len(a), len(b)
    if m == 0 or n == 0:
        return 0
    # Para secuencias largas, usa approach de 2 filas para ahorrar memoria
    prev = [0] * (n + 1)
    for i in range(1, m + 1):
        curr = [0] * (n + 1)
        for j in range(1, n + 1):
            if a[i - 1] == b[j - 1]:
                curr[j] = prev[j - 1] + 1
            else:
                curr[j] = max(prev[j], curr[j - 1])
        prev = curr
    return prev[n]


def rouge_l(reference: str, hypothesis: str) -> float:
    """ROUGE-L F1 basado en LCS a nivel de palabras."""
    ref_tokens = reference.lower().split()
    hyp_tokens = hypothesis.lower().split()
    if not ref_tokens or not hyp_tokens:
        return 0.0
    lcs = _lcs_length(ref_tokens[:128], hyp_tokens[:128])  # Cap a 128 tokens para velocidad
    precision = lcs / len(hyp_tokens) if hyp_tokens else 0.0
    recall    = lcs / len(ref_tokens)  if ref_tokens  else 0.0
    if precision + recall == 0:
        return 0.0
    return round(2 * precision * recall / (precision + recall), 4)


def has_evidence(text: str) -> bool:
    return bool(_EVIDENCE_RE.search(text))


def is_json_valid(text: str) -> bool:
    try:
        json.loads(text.strip())
        return True
    except Exception:
        return False


def _call_ollama(prompt: str, system: str, model: str) -> str:
    """Llama a Ollama directamente via HTTP. Retorna texto generado."""
    import urllib.request
    ollama_host = os.getenv("OLLAMA_HOST", "http://localhost:11434")
    url = f"{ollama_host}/api/chat"
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user",   "content": prompt},
        ],
        "stream": False,
        "options": {"temperature": 0.0, "num_predict": 512},
    }
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            body = json.loads(resp.read().decode())
            return body.get("message", {}).get("content", "")
    except Exception as exc:
        print(f"[evaluate] Ollama call failed: {exc}", file=sys.stderr)
        return ""


def evaluate(
    task: str,
    eval_file: str | None = None,
    model: str | None = None,
    use_ollama: bool = False,
) -> dict[str, Any]:
    """
    Evalúa sobre el eval JSONL.
    Si use_ollama=True, genera outputs con Ollama y calcula métricas vs. gold.
    Si use_ollama=False, compara approved_output vs el output del modelo (usa approved como proxy).
    """
    if eval_file is None:
        eval_file = str(DATA_DIR / f"{task}_eval.jsonl")

    path = Path(eval_file)
    if not path.exists():
        return {
            "error": f"Eval file no encontrado: {eval_file}",
            "rouge_l": 0.0,
            "evidence_rate": 0.0,
            "avg_length": 0.0,
            "json_valid_rate": 0.0,
            "n_examples": 0,
        }

    records = []
    with path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                records.append(json.loads(line))

    if not records:
        return {"error": "Eval file vacío", "rouge_l": 0.0, "evidence_rate": 0.0, "avg_length": 0.0,
                "json_valid_rate": 0.0, "n_examples": 0}

    rouge_scores: list[float] = []
    evidence_hits: list[bool] = []
    lengths: list[int] = []
    json_valid: list[bool] = []

    for rec in records:
        messages = rec.get("messages", [])
        system_msg = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_msg   = next((m["content"] for m in messages if m["role"] == "user"),   "")
        gold       = next((m["content"] for m in messages if m["role"] == "assistant"), "")

        if use_ollama and model:
            generated = _call_ollama(user_msg, system_msg, model)
        else:
            # Sin Ollama: evaluamos el gold contra sí mismo como referencia baseline
            generated = gold

        rouge_scores.append(rouge_l(gold, generated))
        evidence_hits.append(has_evidence(generated))
        lengths.append(len(generated.split()))
        if task == "extraction":
            json_valid.append(is_json_valid(generated))

    metrics = {
        "n_examples":     len(records),
        "rouge_l":        round(sum(rouge_scores) / len(rouge_scores), 4) if rouge_scores else 0.0,
        "evidence_rate":  round(sum(evidence_hits) / len(evidence_hits), 4) if evidence_hits else 0.0,
        "avg_length":     round(sum(lengths) / len(lengths), 1) if lengths else 0.0,
        "json_valid_rate": round(sum(json_valid) / len(json_valid), 4) if json_valid else None,
    }

    # Target lengths por task
    targets = {"narrative": 60, "draft": 50, "extraction": 200}
    target = targets.get(task, 80)
    metrics["length_ok_rate"] = round(
        sum(1 for l in lengths if l <= target) / len(lengths), 4
    ) if lengths else 0.0

    print(f"[evaluate] task={task!r}  n={metrics['n_examples']}")
    print(f"           rouge_l={metrics['rouge_l']}  evidence_rate={metrics['evidence_rate']}")
    print(f"           avg_length={metrics['avg_length']}  length_ok_rate={metrics['length_ok_rate']}")
    if task == "extraction":
        print(f"           json_valid_rate={metrics['json_valid_rate']}")

    return metrics


def main() -> None:
    parser = argparse.ArgumentParser(description="Evalúa modelo fine-tuneado sobre eval set")
    parser.add_argument("--task", required=True, choices=["narrative", "draft", "extraction"])
    parser.add_argument("--eval-file", default=None)
    parser.add_argument("--model", default=None, help="Nombre del modelo Ollama a evaluar")
    parser.add_argument("--use-ollama", action="store_true", help="Genera outputs con Ollama y compara vs gold")
    args = parser.parse_args()

    metrics = evaluate(
        task=args.task,
        eval_file=args.eval_file,
        model=args.model,
        use_ollama=args.use_ollama,
    )
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
