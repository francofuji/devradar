import { useEffect, useRef, useState } from "react";
import { useOutletContext } from "react-router-dom";
import Badge from "../components/ui/Badge";
import EmptyState from "../components/ui/EmptyState";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import ScoreBar from "../components/ui/ScoreBar";
import PageFrame from "./PageFrame";
import {
  activateModel,
  exportTraining,
  fetchLlmModels,
  fetchRegisteredModels,
  fetchTrainingExamples,
  fetchTrainingStats,
  launchTraining,
  testLlm,
} from "../api/training";

const TASK_LABELS = {
  narrative:  "Narrativa",
  draft:      "Draft outreach",
  extraction: "Extracción",
};
const TASK_OPTIONS = ["narrative", "draft", "extraction"];
const MODEL_OPTIONS = ["llama3.1:8b", "qwen2.5:7b", "mistral:7b", "llama3.2:3b"];
const GOAL = 150;
const MIN_LAUNCH = 10; // umbral real del backend; muestra advertencia si < 100

// ── Sub-componentes ──────────────────────────────────────────────────────────

function TaskCard({ row, onExport, onLaunch, isLaunching }) {
  const pct = Math.min(100, Math.round((row.high_quality_examples / GOAL) * 100));
  const ready = row.high_quality_examples >= 100;
  const canLaunch = row.high_quality_examples >= MIN_LAUNCH;

  return (
    <article className="panel training-card">
      <div className="training-card__header">
        <p className="panel__eyebrow">{TASK_LABELS[row.task_type] || row.task_type}</p>
        <div style={{ display: "flex", gap: "0.4rem" }}>
          {ready && <Badge tone="green">listo para FT</Badge>}
          {!ready && canLaunch && <Badge tone="amber">dev mode</Badge>}
        </div>
      </div>
      <h3>
        {row.high_quality_examples}{" "}
        <span style={{ fontSize: "0.8rem", color: "var(--muted)" }}>/ {GOAL}</span>
      </h3>
      <ScoreBar value={row.high_quality_examples} max={GOAL} label="ejemplos calidad ≥0.7" />
      <div className="stack-list" style={{ marginTop: "0.75rem" }}>
        <div className="stack-list__row">
          <span>Total ejemplos</span>
          <strong>{row.total_examples}</strong>
        </div>
        <div className="stack-list__row">
          <span>Editados por humano</span>
          <strong>{Math.round((row.avg_edit_rate || 0) * 100)}%</strong>
        </div>
      </div>
      <div style={{ display: "flex", gap: "0.4rem", marginTop: "0.75rem" }}>
        <button
          className="btn-secondary"
          style={{ flex: 1, fontSize: "0.82rem" }}
          onClick={() => onExport(row.task_type)}
        >
          Exportar JSONL
        </button>
        <button
          className="btn-primary"
          style={{ flex: 1, fontSize: "0.82rem" }}
          disabled={!canLaunch || isLaunching}
          onClick={() => onLaunch(row.task_type)}
          title={!canLaunch ? `Necesitas al menos ${MIN_LAUNCH} ejemplos` : ""}
        >
          {isLaunching ? "Lanzando…" : "Lanzar FT"}
        </button>
      </div>
      {!canLaunch && (
        <p className="panel__copy" style={{ marginTop: "0.4rem", fontSize: "0.78rem" }}>
          {MIN_LAUNCH - row.high_quality_examples} ejemplos más para poder lanzar.
        </p>
      )}
    </article>
  );
}

function LaunchModal({ task, stats, onClose, onConfirm }) {
  const [baseModel, setBaseModel] = useState("llama3.1:8b");
  const [epochs, setEpochs] = useState(3);
  const row = stats?.by_task?.find((r) => r.task_type === task);
  const hq = row?.high_quality_examples ?? 0;
  const isProduction = hq >= 100;

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <p className="panel__eyebrow">Lanzar Fine-tuning — {TASK_LABELS[task] || task}</p>

        <div className="training-launch__stats">
          <div className="training-launch__stat">
            <span>Ejemplos HQ disponibles</span>
            <strong>{hq}</strong>
          </div>
          <div className="training-launch__stat">
            <span>Meta de producción</span>
            <strong>100 / {GOAL}</strong>
          </div>
          <div className="training-launch__stat">
            <span>Modo</span>
            <Badge tone={isProduction ? "green" : "amber"}>
              {isProduction ? "producción" : "desarrollo"}
            </Badge>
          </div>
        </div>

        {!isProduction && (
          <p className="panel__copy" style={{ color: "#fbbf24", marginBottom: "0.75rem" }}>
            ⚠ Menos de 100 ejemplos de calidad — el modelo resultante puede ser inconsistente.
            Se recomienda 100+ para uso en producción.
          </p>
        )}

        <div className="config-field">
          <label className="config-field__label">Modelo base</label>
          <select
            className="entities-search config-field__input"
            value={baseModel}
            onChange={(e) => setBaseModel(e.target.value)}
          >
            {MODEL_OPTIONS.map((m) => <option key={m} value={m}>{m}</option>)}
          </select>
        </div>

        <div className="config-field">
          <label className="config-field__label">Épocas de entrenamiento</label>
          <input
            className="entities-search config-field__input"
            type="number"
            min={1}
            max={20}
            value={epochs}
            onChange={(e) => setEpochs(Number(e.target.value))}
          />
        </div>

        <p className="panel__copy" style={{ marginTop: "0.5rem" }}>
          El proceso corre en background. El progreso aparece en tiempo real via SSE.
        </p>

        <div className="modal-actions">
          <button className="btn-secondary" onClick={onClose}>Cancelar</button>
          <button
            className="btn-primary"
            onClick={() => onConfirm({ task, baseModel, epochs })}
          >
            Confirmar y lanzar
          </button>
        </div>
      </div>
    </div>
  );
}

function ProgressPanel({ event, onDismiss }) {
  const pct = event?.pct ?? 0;
  const step = event?.step ?? "";
  const msg  = event?.msg  ?? "";
  const isDone   = event?.type === "training_completed";
  const isFailed = event?.type === "training_failed";

  return (
    <article className={`panel training-progress ${isDone ? "training-progress--done" : ""} ${isFailed ? "training-progress--fail" : ""}`}>
      <div className="training-progress__header">
        <p className="panel__eyebrow">
          {isDone ? "✓ Fine-tuning completado" : isFailed ? "✗ Fine-tuning fallido" : "Fine-tuning en progreso…"}
        </p>
        <button className="btn-secondary" style={{ fontSize: "0.78rem", padding: "0.2rem 0.5rem" }} onClick={onDismiss}>
          ✕
        </button>
      </div>

      <div className="training-progress__bar-wrap">
        <div className="training-progress__bar" style={{ width: `${pct}%` }} />
      </div>
      <p className="panel__copy" style={{ marginTop: "0.4rem" }}>
        <strong>{pct}%</strong>{step ? ` — ${step}` : ""}{msg ? `: ${msg}` : ""}
      </p>

      {isDone && event.metrics && (
        <div className="stack-list" style={{ marginTop: "0.75rem" }}>
          {[
            ["ROUGE-L", event.metrics.rouge_l],
            ["Evidence rate", event.metrics.evidence_rate
              ? `${Math.round(event.metrics.evidence_rate * 100)}%`
              : "—"],
            ["Avg length", event.metrics.avg_length ? `${event.metrics.avg_length} words` : "—"],
          ].map(([label, val]) => (
            <div key={label} className="stack-list__row">
              <span>{label}</span>
              <strong>{val ?? "—"}</strong>
            </div>
          ))}
        </div>
      )}

      {isFailed && (
        <p className="panel__copy" style={{ color: "#f87171" }}>{event.error}</p>
      )}
    </article>
  );
}

function ExamplesTable({ examples }) {
  if (!examples.length) return <p className="panel__copy">Sin ejemplos disponibles.</p>;
  return (
    <div className="taxonomy-table" style={{ fontSize: "0.82rem" }}>
      <div className="taxonomy-table__head training-examples-grid">
        <span>Task</span><span>Entidad</span><span>Outcome</span>
        <span>Calidad</span><span>Editado</span><span>Fecha</span>
      </div>
      {examples.map((ex) => (
        <div key={ex.id} className="taxonomy-table__row training-examples-grid">
          <Badge tone="blue">{ex.task_type}</Badge>
          <span style={{ fontFamily: "monospace", fontSize: "0.78rem" }}>{ex.entity_id || "—"}</span>
          <Badge tone={ex.outcome === "positive" ? "green" : ex.outcome === "negative" ? "red" : "gray"}>
            {ex.outcome || "—"}
          </Badge>
          <span>{ex.quality_score != null ? ex.quality_score.toFixed(2) : "—"}</span>
          <span>{ex.was_edited ? "✓" : "—"}</span>
          <span style={{ color: "var(--muted)" }}>
            {ex.created_at ? new Date(ex.created_at).toLocaleDateString("es") : "—"}
          </span>
        </div>
      ))}
    </div>
  );
}

function ModelsTable({ models, onActivate }) {
  if (!models.length)
    return <p className="panel__copy">Sin modelos registrados. Aparecen aquí al completar E18.T5 (deploy).</p>;
  return (
    <div className="taxonomy-table">
      <div className="taxonomy-table__head training-models-grid">
        <span>Modelo</span><span>Task</span><span>Ejemplos</span>
        <span>ROUGE-L</span><span>Activo</span><span></span>
      </div>
      {models.map((m) => (
        <div key={m.id} className="taxonomy-table__row training-models-grid">
          <span style={{ fontSize: "0.78rem", fontFamily: "monospace" }}>{m.model_name}</span>
          <Badge tone="blue">{m.task_type}</Badge>
          <span>{m.training_examples ?? "—"}</span>
          <span>{m.eval_rouge_l != null ? m.eval_rouge_l.toFixed(3) : "—"}</span>
          <span>{m.is_active ? <Badge tone="green">activo</Badge> : <Badge tone="gray">inactivo</Badge>}</span>
          {!m.is_active && (
            <button className="btn-secondary taxonomy-table__edit" onClick={() => onActivate(m.id)}>
              Activar
            </button>
          )}
        </div>
      ))}
    </div>
  );
}

function LlmTestPanel({ llmModels }) {
  const [prompt, setPrompt] = useState("");
  const [taskType, setTaskType] = useState("narrative");
  const [result, setResult] = useState(null);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState(null);

  const handleTest = async () => {
    if (!prompt.trim()) return;
    setIsRunning(true);
    setResult(null);
    setError(null);
    try {
      const data = await testLlm({ prompt, task_type: taskType });
      setResult(data);
    } catch (err) {
      setError(err.message || "Error en llamada LLM");
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <article className="panel">
      <p className="panel__eyebrow">Test LLM</p>
      <div className="llm-test">
        <div className="llm-test__controls">
          <select className="entities-search" style={{ width: "auto" }} value={taskType}
            onChange={(e) => setTaskType(e.target.value)}>
            {TASK_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
          <button className="btn-primary" onClick={handleTest} disabled={isRunning || !prompt.trim()}>
            {isRunning ? "Llamando…" : "Probar"}
          </button>
        </div>
        <textarea
          className="llm-test__input" rows={5}
          placeholder="Escribe tu prompt aquí…"
          value={prompt} onChange={(e) => setPrompt(e.target.value)}
        />
        {error && <p className="topbar__error">{error}</p>}
        {result && (
          <div className="llm-test__result">
            <div className="llm-test__result-header">
              {result.cache_hit
                ? <Badge tone="cyan">⚡ Cache HIT</Badge>
                : result.cached_now
                ? <Badge tone="green">🔄 Llamada nueva · cacheada</Badge>
                : <Badge tone="gray">🔄 Llamada nueva</Badge>}
            </div>
            <pre className="llm-test__output">
              {typeof result.output === "string"
                ? result.output
                : JSON.stringify(result.output, null, 2)}
            </pre>
          </div>
        )}
      </div>
      {llmModels && (
        <div style={{ marginTop: "1rem" }}>
          <p className="panel__eyebrow">Modelos en Ollama</p>
          <div className="stack-list">
            {(llmModels.available_models || []).map((m) => {
              const configured = llmModels.configured_models?.[llmModels.provider] || {};
              const usedFor = Object.entries(configured)
                .filter(([, name]) => name === m)
                .map(([t]) => t);
              return (
                <div key={m} className="stack-list__row">
                  <span style={{ fontFamily: "monospace", fontSize: "0.82rem" }}>{m}</span>
                  {usedFor.length > 0 && (
                    <div style={{ display: "flex", gap: "0.25rem" }}>
                      {usedFor.map((t) => <Badge key={t} tone="green">{t}</Badge>)}
                    </div>
                  )}
                </div>
              );
            })}
            {!(llmModels.available_models || []).length && (
              <p className="panel__copy">Sin modelos detectados en Ollama.</p>
            )}
          </div>
        </div>
      )}
    </article>
  );
}

// ── Página principal ─────────────────────────────────────────────────────────

export default function Training() {
  const { sse } = useOutletContext() || {};

  const [stats, setStats]         = useState(null);
  const [examples, setExamples]   = useState([]);
  const [models, setModels]       = useState([]);
  const [llmModels, setLlmModels] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [exporting, setExporting] = useState(null);
  const [exportMsg, setExportMsg] = useState(null);
  const [examplesFilter, setExamplesFilter] = useState("");
  const [launchTask, setLaunchTask]       = useState(null);  // task para modal
  const [isLaunching, setIsLaunching]     = useState(false);
  const [launchError, setLaunchError]     = useState(null);
  const [progressEvent, setProgressEvent] = useState(null); // último SSE de training

  const load = async () => {
    setIsLoading(true);
    const [s, ex, m, lm] = await Promise.allSettled([
      fetchTrainingStats(),
      fetchTrainingExamples({ limit: 20 }),
      fetchRegisteredModels(),
      fetchLlmModels(),
    ]);
    const r = (res) => (res.status === "fulfilled" ? res.value : null);
    setStats(r(s));
    setExamples(r(ex)?.items || []);
    setModels(r(m)?.items || []);
    setLlmModels(r(lm));
    setIsLoading(false);
  };

  useEffect(() => { load(); }, []);

  // Escuchar SSE para progreso de training
  useEffect(() => {
    if (!sse?.lastEvent) return;
    const { type } = sse.lastEvent;
    if (
      type === "training_progress" ||
      type === "training_completed" ||
      type === "training_failed"
    ) {
      setProgressEvent(sse.lastEvent);
      // Al completar, recargar modelos registrados
      if (type === "training_completed") {
        fetchRegisteredModels().then((data) => setModels(data?.items || [])).catch(() => {});
      }
    }
  }, [sse?.lastEvent]);

  const handleExport = async (taskType) => {
    setExporting(taskType);
    setExportMsg(null);
    try {
      const res = await exportTraining({ task: taskType });
      setExportMsg(`✓ Exportado: ${res.path} (${res.count} ejemplos)`);
    } catch (err) {
      setExportMsg(`Error: ${err.message}`);
    } finally {
      setExporting(null);
    }
  };

  const handleLaunchConfirm = async ({ task, baseModel, epochs }) => {
    setLaunchTask(null);
    setIsLaunching(true);
    setLaunchError(null);
    setProgressEvent({ type: "training_progress", task, step: "queued", pct: 0, msg: "Iniciando…" });
    try {
      await launchTraining({ task, base_model: baseModel, epochs });
    } catch (err) {
      setLaunchError(err.message || "Error lanzando fine-tuning");
      setProgressEvent(null);
    } finally {
      setIsLaunching(false);
    }
  };

  const handleActivate = async (modelId) => {
    try {
      await activateModel(modelId);
      load();
    } catch (err) {
      alert(err.message);
    }
  };

  const filteredExamples = examplesFilter
    ? examples.filter((e) => e.task_type === examplesFilter)
    : examples;

  if (isLoading) {
    return (
      <PageFrame eyebrow="Sistema" title="Fine-tuning">
        <LoadingSpinner label="Cargando datos de training…" />
      </PageFrame>
    );
  }

  return (
    <PageFrame
      eyebrow="Sistema"
      title="Fine-tuning"
      description={`${stats?.high_quality_total ?? 0} ejemplos de calidad · ${stats?.eta_to_150 ?? 150} hasta meta de 150`}
    >
      {/* Barra de progreso SSE */}
      {progressEvent && (
        <ProgressPanel
          event={progressEvent}
          onDismiss={() => setProgressEvent(null)}
        />
      )}

      {launchError && (
        <p className="topbar__error" style={{ marginBottom: "0.75rem" }}>{launchError}</p>
      )}

      {/* Task cards con botón de lanzar */}
      {stats?.by_task?.length > 0 ? (
        <div className="panel-grid">
          {stats.by_task.map((row) => (
            <TaskCard
              key={row.task_type}
              row={row}
              onExport={handleExport}
              onLaunch={(t) => setLaunchTask(t)}
              isLaunching={isLaunching}
            />
          ))}
        </div>
      ) : (
        <EmptyState
          title="Sin ejemplos"
          description="Los ejemplos de fine-tuning se acumulan automáticamente al aprobar drafts de outreach."
        />
      )}

      {exportMsg && (
        <p className="panel__copy" style={{ marginTop: "0.5rem", color: exportMsg.startsWith("✓") ? "#4ade80" : "#f87171" }}>
          {exportMsg}
        </p>
      )}

      {/* Tabla de ejemplos */}
      <article className="panel" style={{ marginTop: "1.5rem" }}>
        <div className="training-examples-header">
          <p className="panel__eyebrow">Últimos ejemplos</p>
          <select
            className="entities-search"
            style={{ width: "auto", fontSize: "0.82rem" }}
            value={examplesFilter}
            onChange={(e) => setExamplesFilter(e.target.value)}
          >
            <option value="">Todos los tasks</option>
            {TASK_OPTIONS.map((t) => <option key={t} value={t}>{t}</option>)}
          </select>
        </div>
        <ExamplesTable examples={filteredExamples} />
      </article>

      {/* Modelos registrados */}
      <article className="panel" style={{ marginTop: "1.5rem" }}>
        <p className="panel__eyebrow">Modelos registrados</p>
        <ModelsTable models={models} onActivate={handleActivate} />
      </article>

      {/* LLM test */}
      <div style={{ marginTop: "1.5rem" }}>
        <LlmTestPanel llmModels={llmModels} />
      </div>

      {/* Modal de confirmación */}
      {launchTask && (
        <LaunchModal
          task={launchTask}
          stats={stats}
          onClose={() => setLaunchTask(null)}
          onConfirm={handleLaunchConfirm}
        />
      )}
    </PageFrame>
  );
}
