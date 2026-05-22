import { useEffect, useRef, useState } from "react";
import { fetchLlmLogs, fetchLlmLogDetail, fetchEnrichmentLogs, fetchEventLogs, openLogStream } from "../api/logs";
import { getApiToken } from "../api/client";
import Badge from "../components/ui/Badge";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import PageFrame from "./PageFrame";

// ── Helpers ────────────────────────────────────────────────────────────────

function timeAgo(isoStr) {
  if (!isoStr) return "—";
  const diff = Date.now() - new Date(isoStr).getTime();
  const s = Math.floor(diff / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 24) return `${h}h`;
  return `${Math.floor(h / 24)}d`;
}

function fmt(n) {
  if (n == null) return "—";
  return Number(n).toLocaleString();
}

function fmtCost(n) {
  if (n == null) return "—";
  const v = Number(n);
  if (v === 0) return "$0.00";
  return `$${v.toFixed(4)}`;
}

function Timestamp({ iso }) {
  return <span title={iso}>{timeAgo(iso)}</span>;
}

function LiveBadge({ live }) {
  if (!live) return null;
  return (
    <span style={{
      display: "inline-flex", alignItems: "center", gap: "0.3rem",
      padding: "0.2rem 0.55rem", borderRadius: 8,
      background: "var(--success-bg)", color: "var(--success-text)",
      fontSize: "0.75rem", fontWeight: 500,
    }}>
      <span style={{
        width: 6, height: 6, borderRadius: "50%",
        background: "var(--success-text)",
        animation: "pulse 1.5s ease-in-out infinite",
      }} />
      Live
    </span>
  );
}

function RefreshBar({ onRefresh, lastUpdated, live, onLiveToggle }) {
  return (
    <div style={{ display: "flex", alignItems: "center", gap: "0.6rem", marginBottom: "1rem" }}>
      <button className="btn-secondary" onClick={onRefresh} style={{ padding: "0.35rem 0.8rem", fontSize: "0.82rem" }}>
        ↺ Refrescar
      </button>
      <button
        className={live ? "btn-primary" : "btn-secondary"}
        onClick={onLiveToggle}
        style={{ padding: "0.35rem 0.8rem", fontSize: "0.82rem" }}
      >
        {live ? "● Live" : "Live"}
      </button>
      <LiveBadge live={live} />
      {lastUpdated && (
        <span style={{ fontSize: "0.75rem", color: "var(--muted)", marginLeft: "auto" }}>
          Actualizado {timeAgo(lastUpdated)}
        </span>
      )}
    </div>
  );
}

// ── Table primitives ───────────────────────────────────────────────────────

function THead({ cols }) {
  return (
    <div style={{
      display: "grid", gridTemplateColumns: cols,
      padding: "0.45rem 0.9rem",
      background: "var(--surface-metric)",
      borderBottom: "0.5px solid var(--border)",
      fontSize: "0.7rem", fontWeight: 500,
      textTransform: "uppercase", letterSpacing: "0.06em",
      color: "var(--muted)",
      gap: "0.5rem",
    }}>
    </div>
  );
}

// ── LLM task_type badges ───────────────────────────────────────────────────

const TASK_TONE = {
  readme_extraction: "gray",
  archetype_classification: "indigo",
  pain_detection: "amber",
  memory_narrative: "blue",
  draft: "green",
  full: "slate",
};

const PROVIDER_TONE = { ollama: "indigo", anthropic: "copper" };

// ── Tab: LLM Calls ─────────────────────────────────────────────────────────

// grid columns: entity · task · provider · tokens · cost · hace
const COLS_LLM = "2fr 1.4fr 1.4fr 1.2fr 0.9fr 4rem";

function LlmDetailPanel({ rowId }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    fetchLlmLogDetail(rowId)
      .then(setDetail)
      .catch(() => setDetail({ error: "No se pudo cargar el detalle." }))
      .finally(() => setLoading(false));
  }, [rowId]);

  const panelStyle = {
    padding: "0.85rem 1.1rem",
    background: "var(--surface-metric)",
    borderBottom: "0.5px solid var(--border)",
    display: "grid", gap: "0.75rem",
  };

  const blockStyle = {
    display: "grid", gap: "0.3rem",
  };

  const labelStyle = {
    fontSize: "0.68rem", fontWeight: 500, textTransform: "uppercase",
    letterSpacing: "0.1em", color: "var(--muted)",
  };

  const preStyle = {
    margin: 0, padding: "0.6rem 0.8rem",
    background: "var(--surface)", border: "0.5px solid var(--border)",
    borderRadius: 8, fontSize: "0.78rem", lineHeight: 1.55,
    fontFamily: "IBM Plex Mono, monospace", whiteSpace: "pre-wrap",
    wordBreak: "break-word", maxHeight: 280, overflowY: "auto",
    color: "var(--text)",
  };

  if (loading) return (
    <div style={panelStyle}>
      <LoadingSpinner label="Cargando detalle…" />
    </div>
  );

  if (detail?.error) return (
    <div style={panelStyle}>
      <p style={{ margin: 0, color: "var(--danger-text)", fontSize: "0.82rem" }}>{detail.error}</p>
    </div>
  );

  const hasPrompt = detail?.prompt_preview;
  const hasResponse = detail?.response_preview;
  const isCacheHit = detail?.llm_calls === 0;

  return (
    <div style={panelStyle}>
      {isCacheHit && (
        <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--success-text)" }}>
          ✓ Cache hit — esta llamada fue servida desde Redis, no hay prompt/response almacenado.
        </p>
      )}
      {hasPrompt && (
        <div style={blockStyle}>
          <span style={labelStyle}>Prompt enviado</span>
          <pre style={preStyle}>{detail.prompt_preview}</pre>
        </div>
      )}
      {hasResponse && (
        <div style={blockStyle}>
          <span style={labelStyle}>Respuesta recibida</span>
          <pre style={preStyle}>{detail.response_preview}</pre>
        </div>
      )}
      {!isCacheHit && !hasPrompt && !hasResponse && (
        <p style={{ margin: 0, fontSize: "0.78rem", color: "var(--muted)" }}>
          Este registro es anterior a la captura de prompts. Las nuevas llamadas sí incluirán el texto.
        </p>
      )}
    </div>
  );
}

function LlmRow({ row }) {
  const [expanded, setExpanded] = useState(false);
  const isCacheHit = row.llm_calls === 0 && row.input_tokens === 0 && row.output_tokens === 0;

  return (
    <>
      <div
        onClick={() => setExpanded((x) => !x)}
        style={{
          display: "grid", gridTemplateColumns: "2fr 1.4fr 1.4fr 1.2fr 0.9fr 4rem",
          padding: "0.5rem 0.9rem",
          borderBottom: expanded ? "none" : "0.5px solid var(--border)",
          fontSize: "0.83rem", gap: "0.5rem", alignItems: "center",
          background: expanded
            ? "var(--accent-soft)"
            : isCacheHit ? "rgba(59,109,17,0.05)" : "transparent",
          cursor: "pointer",
          transition: "background 0.1s",
        }}
      >
        <span style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: "0.78rem", color: "var(--muted)" }}>
          {row.entity_id}
        </span>
        <div style={{ display: "flex", gap: "0.3rem", flexWrap: "wrap" }}>
          <Badge tone={TASK_TONE[row.enrichment_type] || "gray"}>{row.enrichment_type}</Badge>
        </div>
        <Badge tone={PROVIDER_TONE[row.provider] || "gray"}>{row.provider}</Badge>
        <span style={{ fontVariantNumeric: "tabular-nums", color: "var(--muted)", fontSize: "0.78rem" }}>
          {isCacheHit
            ? <span style={{ color: "var(--success-text)" }}>cache hit</span>
            : `${fmt(row.input_tokens)} / ${fmt(row.output_tokens)}`}
        </span>
        <span style={{ fontVariantNumeric: "tabular-nums" }}>{fmtCost(row.estimated_cost)}</span>
        <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}>
          <Timestamp iso={row.created_at} />
        </span>
      </div>
      {expanded && row.id && <LlmDetailPanel rowId={row.id} />}
    </>
  );
}

function LlmTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [filterType, setFilterType] = useState("");
  const [filterProvider, setFilterProvider] = useState("");
  const [offset, setOffset] = useState(0);
  const esRef = useRef(null);

  async function load(reset = false) {
    setLoading(true);
    try {
      const params = { limit: 50 + (reset ? 0 : offset) };
      if (filterType) params.enrichment_type = filterType;
      if (filterProvider) params.provider = filterProvider;
      const res = await fetchLlmLogs(params);
      setData(res);
      setLastUpdated(new Date().toISOString());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(true); }, [filterType, filterProvider]);

  function toggleLive() {
    if (live) {
      esRef.current?.close();
      esRef.current = null;
      setLive(false);
    } else {
      const es = openLogStream(getApiToken());
      es.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === "llm_cost") {
            setData((prev) => {
              if (!prev) return prev;
              const newRow = {
                entity_id: msg.entity_id, enrichment_type: msg.enrichment_type,
                provider: msg.provider, llm_calls: msg.llm_calls,
                input_tokens: msg.input_tokens, output_tokens: msg.output_tokens,
                estimated_cost: msg.estimated_cost, created_at: msg.ts,
              };
              return { ...prev, rows: [newRow, ...(prev.rows || [])] };
            });
          }
        } catch {}
      };
      esRef.current = es;
      setLive(true);
    }
  }

  useEffect(() => () => esRef.current?.close(), []);

  const rows = data?.rows || [];
  const totals = data?.totals || {};

  return (
    <div>
      <div style={{ display: "flex", gap: "0.6rem", marginBottom: "0.75rem", flexWrap: "wrap" }}>
        <select
          value={filterType} onChange={(e) => setFilterType(e.target.value)}
          style={{ padding: "0.35rem 0.65rem", borderRadius: 8, border: "0.5px solid var(--border-strong)", background: "var(--surface)", fontSize: "0.82rem" }}
        >
          <option value="">Todos los tipos</option>
          {["readme_extraction","archetype_classification","pain_detection","memory_narrative","draft","full"].map(t => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
        <select
          value={filterProvider} onChange={(e) => setFilterProvider(e.target.value)}
          style={{ padding: "0.35rem 0.65rem", borderRadius: 8, border: "0.5px solid var(--border-strong)", background: "var(--surface)", fontSize: "0.82rem" }}
        >
          <option value="">Todos los providers</option>
          <option value="ollama">ollama</option>
          <option value="anthropic">anthropic</option>
        </select>
      </div>

      <RefreshBar onRefresh={() => load(true)} lastUpdated={lastUpdated} live={live} onLiveToggle={toggleLive} />

      {loading && <LoadingSpinner label="Cargando LLM logs…" />}

      {!loading && (
        <article className="panel" style={{ padding: 0, overflow: "hidden" }}>
          {/* Head */}
          <div style={{
            display: "grid", gridTemplateColumns: "2fr 1.4fr 1.4fr 1.2fr 0.9fr 4rem",
            padding: "0.45rem 0.9rem", background: "var(--surface-metric)",
            borderBottom: "0.5px solid var(--border)",
            fontSize: "0.7rem", fontWeight: 500, textTransform: "uppercase",
            letterSpacing: "0.06em", color: "var(--muted)", gap: "0.5rem",
          }}>
            <span>Entidad</span><span>Task type</span><span>Provider</span>
            <span>Tokens in / out</span><span>Costo</span><span>Hace</span>
          </div>

          {rows.length === 0
            ? <p className="panel__copy" style={{ padding: "1rem" }}>Sin registros.</p>
            : rows.map((r, i) => <LlmRow key={i} row={r} />)
          }

          {/* Totals footer */}
          <div style={{
            display: "flex", gap: "1.5rem", padding: "0.55rem 0.9rem",
            background: "var(--surface-metric)", borderTop: "0.5px solid var(--border)",
            fontSize: "0.78rem", color: "var(--muted)",
          }}>
            <span>Total calls: <strong style={{ color: "var(--text)" }}>{fmt(totals.total_calls)}</strong></span>
            <span>Input tokens: <strong style={{ color: "var(--text)" }}>{fmt(totals.total_input_tokens)}</strong></span>
            <span>Output tokens: <strong style={{ color: "var(--text)" }}>{fmt(totals.total_output_tokens)}</strong></span>
            <span>Costo total: <strong style={{ color: "var(--text)" }}>{fmtCost(totals.total_cost)}</strong></span>
          </div>
        </article>
      )}
    </div>
  );
}

// ── Tab: Enrichment Jobs ───────────────────────────────────────────────────

const STATUS_TONE = { pending: "gray", running: "amber", completed: "ok", failed: "danger" };

function StatusBadge({ status }) {
  const isRunning = status === "running";
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: "0.3rem" }}>
      {isRunning && (
        <span style={{
          width: 7, height: 7, borderRadius: "50%",
          border: "2px solid var(--warning-text)",
          borderTopColor: "transparent",
          animation: "spin 700ms linear infinite", display: "inline-block",
        }} />
      )}
      <Badge tone={
        status === "completed" ? "green"
        : status === "failed" ? "amber"
        : status === "running" ? "amber"
        : "gray"
      }>{status}</Badge>
    </span>
  );
}

function EnrichRow({ row }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <>
      <div
        style={{
          display: "grid", gridTemplateColumns: "2fr 1.3fr 0.5fr 1fr 0.7fr 4rem",
          padding: "0.5rem 0.9rem", borderBottom: "0.5px solid var(--border)",
          fontSize: "0.83rem", gap: "0.5rem", alignItems: "center",
          background: row.status === "failed" ? "rgba(163,45,45,0.04)" : "transparent",
          cursor: row.error ? "pointer" : "default",
        }}
        onClick={() => row.error && setExpanded((x) => !x)}
      >
        <span style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: "0.78rem", color: "var(--muted)" }}>
          {row.entity_id}
        </span>
        <Badge tone="indigo">{row.enrichment_type}</Badge>
        <span style={{ color: "var(--muted)" }}>{row.priority}</span>
        <StatusBadge status={row.status} />
        <span style={{ fontVariantNumeric: "tabular-nums", color: "var(--muted)" }}>
          {row.duration_seconds != null ? `${row.duration_seconds}s` : "—"}
        </span>
        <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}><Timestamp iso={row.created_at} /></span>
      </div>
      {expanded && row.error && (
        <div style={{
          padding: "0.5rem 0.9rem 0.6rem 2rem", fontSize: "0.78rem",
          color: "var(--danger-text)", background: "var(--danger-bg)",
          borderBottom: "0.5px solid var(--border)",
          fontFamily: "IBM Plex Mono, monospace", whiteSpace: "pre-wrap",
        }}>
          {row.error}
        </div>
      )}
    </>
  );
}

function EnrichTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [live, setLive] = useState(false);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [filterStatus, setFilterStatus] = useState("");
  const esRef = useRef(null);

  async function load() {
    setLoading(true);
    try {
      const params = { limit: 50 };
      if (filterStatus) params.status = filterStatus;
      const res = await fetchEnrichmentLogs(params);
      setData(res);
      setLastUpdated(new Date().toISOString());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [filterStatus]);

  function toggleLive() {
    if (live) {
      esRef.current?.close();
      esRef.current = null;
      setLive(false);
    } else {
      const es = openLogStream(getApiToken());
      es.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data);
          if (msg.type === "queue_status") {
            // Refresh the whole table so we get updated rows
            load();
          }
        } catch {}
      };
      esRef.current = es;
      setLive(true);
    }
  }

  useEffect(() => () => esRef.current?.close(), []);

  const rows = data?.rows || [];

  return (
    <div>
      <div style={{ display: "flex", gap: "0.6rem", marginBottom: "0.75rem" }}>
        <select
          value={filterStatus} onChange={(e) => setFilterStatus(e.target.value)}
          style={{ padding: "0.35rem 0.65rem", borderRadius: 8, border: "0.5px solid var(--border-strong)", background: "var(--surface)", fontSize: "0.82rem" }}
        >
          <option value="">Todos los estados</option>
          <option value="pending">pending</option>
          <option value="running">running</option>
          <option value="completed">completed</option>
          <option value="failed">failed</option>
        </select>
      </div>

      <RefreshBar onRefresh={load} lastUpdated={lastUpdated} live={live} onLiveToggle={toggleLive} />

      {loading && <LoadingSpinner label="Cargando enrichment jobs…" />}

      {!loading && (
        <article className="panel" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{
            display: "grid", gridTemplateColumns: "2fr 1.3fr 0.5fr 1fr 0.7fr 4rem",
            padding: "0.45rem 0.9rem", background: "var(--surface-metric)",
            borderBottom: "0.5px solid var(--border)",
            fontSize: "0.7rem", fontWeight: 500, textTransform: "uppercase",
            letterSpacing: "0.06em", color: "var(--muted)", gap: "0.5rem",
          }}>
            <span>Entidad</span><span>Tipo</span><span>Prio</span>
            <span>Status</span><span>Duración</span><span>Hace</span>
          </div>
          {rows.length === 0
            ? <p className="panel__copy" style={{ padding: "1rem" }}>Sin registros.</p>
            : rows.map((r, i) => <EnrichRow key={i} row={r} />)
          }
        </article>
      )}
    </div>
  );
}

// ── Tab: Events ────────────────────────────────────────────────────────────

const CAT_TONE = {
  discovery: "blue", activity: "green", enrichment: "indigo",
  intent: "copper", system: "gray",
};

function EventRow({ row }) {
  const isIntent = row.event_type === "developer.intent_threshold_crossed";
  return (
    <div style={{
      display: "grid", gridTemplateColumns: "2.2fr 1.8fr 1fr 1fr 4rem",
      padding: "0.5rem 0.9rem", borderBottom: "0.5px solid var(--border)",
      fontSize: "0.83rem", gap: "0.5rem", alignItems: "center",
      background: isIntent ? "rgba(133,79,11,0.05)" : "transparent",
    }}>
      <span style={{ fontSize: "0.8rem" }}>
        {row.event_type}
        {row.payload_title && (
          <span style={{ color: "var(--muted)", marginLeft: "0.4rem", fontSize: "0.75rem" }}>
            — {row.payload_title}
          </span>
        )}
      </span>
      <span style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: "0.75rem", color: "var(--muted)" }}>
        {row.entity_id || "—"}
      </span>
      <Badge tone={CAT_TONE[row.event_category] || "gray"}>{row.event_category || "—"}</Badge>
      <span style={{ color: "var(--muted)", fontSize: "0.78rem" }}>{row.source || "—"}</span>
      <span style={{ color: "var(--muted)", fontSize: "0.75rem" }}><Timestamp iso={row.occurred_at} /></span>
    </div>
  );
}

function EventsTab() {
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [lastUpdated, setLastUpdated] = useState(null);
  const [filterType, setFilterType] = useState("");
  const [filterEntity, setFilterEntity] = useState("");
  const [debouncedType, setDebouncedType] = useState("");
  const [debouncedEntity, setDebouncedEntity] = useState("");

  useEffect(() => {
    const t = setTimeout(() => setDebouncedType(filterType), 350);
    return () => clearTimeout(t);
  }, [filterType]);

  useEffect(() => {
    const t = setTimeout(() => setDebouncedEntity(filterEntity), 350);
    return () => clearTimeout(t);
  }, [filterEntity]);

  async function load() {
    setLoading(true);
    try {
      const params = { limit: 100 };
      if (debouncedType) params.event_type = debouncedType;
      if (debouncedEntity) params.entity_id = debouncedEntity;
      const res = await fetchEventLogs(params);
      setData(res);
      setLastUpdated(new Date().toISOString());
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => { load(); }, [debouncedType, debouncedEntity]);

  const rows = data?.rows || [];

  return (
    <div>
      <div style={{ display: "flex", gap: "0.6rem", marginBottom: "0.75rem", flexWrap: "wrap" }}>
        <input
          type="text" placeholder="Filtrar por event_type…" value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
          style={{ padding: "0.35rem 0.65rem", borderRadius: 8, border: "0.5px solid var(--border-strong)", background: "var(--surface)", fontSize: "0.82rem", minWidth: 200 }}
        />
        <input
          type="text" placeholder="Filtrar por entity_id…" value={filterEntity}
          onChange={(e) => setFilterEntity(e.target.value)}
          style={{ padding: "0.35rem 0.65rem", borderRadius: 8, border: "0.5px solid var(--border-strong)", background: "var(--surface)", fontSize: "0.82rem", minWidth: 180 }}
        />
      </div>

      <RefreshBar
        onRefresh={load} lastUpdated={lastUpdated}
        live={false} onLiveToggle={() => {}}
      />

      {loading && <LoadingSpinner label="Cargando eventos…" />}

      {!loading && (
        <article className="panel" style={{ padding: 0, overflow: "hidden" }}>
          <div style={{
            display: "grid", gridTemplateColumns: "2.2fr 1.8fr 1fr 1fr 4rem",
            padding: "0.45rem 0.9rem", background: "var(--surface-metric)",
            borderBottom: "0.5px solid var(--border)",
            fontSize: "0.7rem", fontWeight: 500, textTransform: "uppercase",
            letterSpacing: "0.06em", color: "var(--muted)", gap: "0.5rem",
          }}>
            <span>Tipo de evento</span><span>Entidad</span>
            <span>Categoría</span><span>Source</span><span>Hace</span>
          </div>
          {rows.length === 0
            ? <p className="panel__copy" style={{ padding: "1rem" }}>Sin eventos.</p>
            : rows.map((r, i) => <EventRow key={i} row={r} />)
          }
        </article>
      )}
    </div>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

const TABS = [
  { id: "llm",    label: "LLM Calls" },
  { id: "jobs",   label: "Enrichment Jobs" },
  { id: "events", label: "Eventos" },
];

export default function Logs() {
  const [activeTab, setActiveTab] = useState("llm");

  return (
    <PageFrame
      eyebrow="Sistema"
      title="Logs"
      description="Observabilidad de LLM calls, enrichment jobs y eventos del sistema."
    >
      {/* Tab bar */}
      <div style={{ display: "flex", gap: "0.25rem", marginBottom: "1rem" }}>
        {TABS.map((tab) => (
          <button
            key={tab.id}
            onClick={() => setActiveTab(tab.id)}
            style={{
              padding: "0.45rem 1rem",
              borderRadius: 8,
              border: "0.5px solid",
              borderColor: activeTab === tab.id ? "var(--accent)" : "var(--border-strong)",
              background: activeTab === tab.id ? "var(--accent-soft)" : "transparent",
              color: activeTab === tab.id ? "var(--accent)" : "var(--muted)",
              fontSize: "0.85rem", fontWeight: activeTab === tab.id ? 500 : 400,
              cursor: "pointer",
              transition: "all 0.12s",
            }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === "llm"    && <LlmTab />}
      {activeTab === "jobs"   && <EnrichTab />}
      {activeTab === "events" && <EventsTab />}

      <style>{`
        @keyframes pulse {
          0%, 100% { opacity: 1; }
          50% { opacity: 0.4; }
        }
      `}</style>
    </PageFrame>
  );
}
