import { useEffect, useState } from "react";
import { useOutletContext } from "react-router-dom";
import {
  Cell,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
} from "recharts";
import Badge from "../components/ui/Badge";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import ScoreBar from "../components/ui/ScoreBar";
import PageFrame from "./PageFrame";
import useSystemStore from "../store/useSystemStore";

const STATUS_COLORS = {
  DISCOVERED: "#94a3b8",
  PROFILED:   "#185FA5",
  MONITORED:  "#534AB7",
  WARM:       "#854F0B",
  QUALIFIED:  "#3B6D11",
  OUTREACHED: "#7C3A10",
  ENGAGED:    "#2D6A9F",
  CLOSED:     "#64748b",
};

function StatusDonut({ statuses }) {
  if (!statuses?.length) return <p className="panel__copy">Sin datos.</p>;
  const data = statuses.map((s) => ({
    name: s.status,
    value: Number(s.total),
    fill: STATUS_COLORS[s.status] || "#94a3b8",
  }));
  const total = data.reduce((sum, d) => sum + d.value, 0);

  return (
    <div className="donut-wrap">
      <ResponsiveContainer width={140} height={140}>
        <PieChart>
          <Pie
            data={data}
            cx="50%"
            cy="50%"
            innerRadius={42}
            outerRadius={64}
            paddingAngle={2}
            dataKey="value"
          >
            {data.map((entry, i) => (
              <Cell key={i} fill={entry.fill} />
            ))}
          </Pie>
          <Tooltip
            formatter={(value, name) => [value, name]}
            contentStyle={{
              background: "var(--panel-strong)",
              border: "1px solid var(--line-strong)",
              borderRadius: 10,
              fontSize: 12,
            }}
          />
        </PieChart>
      </ResponsiveContainer>
      <div className="donut-legend">
        {data.map((d) => (
          <div key={d.name} className="donut-legend__row">
            <span className="donut-legend__dot" style={{ background: d.fill }} />
            <span>{d.name}</span>
            <strong>{d.value}</strong>
          </div>
        ))}
        <div className="donut-legend__total">
          <span>Total</span>
          <strong>{total}</strong>
        </div>
      </div>
    </div>
  );
}

function SseToast({ event, onDismiss }) {
  useEffect(() => {
    const t = setTimeout(onDismiss, 5000);
    return () => clearTimeout(t);
  }, [onDismiss]);

  return (
    <div className="sse-toast" onClick={onDismiss}>
      <Badge tone="green">live</Badge>
      <span>{event.type?.replace(/_/g, " ")}</span>
      {event.entity_id && <span className="sse-toast__entity">@{event.entity_id}</span>}
    </div>
  );
}

export default function Dashboard() {
  const { health, stats, isLoading, fetchHealth, fetchStats } = useSystemStore();
  const { sse } = useOutletContext();

  const [toasts, setToasts] = useState([]);

  useEffect(() => {
    fetchHealth().catch(() => undefined);
    fetchStats().catch(() => undefined);
  }, [fetchHealth, fetchStats]);

  // SSE toasts for enrichment and transitions
  useEffect(() => {
    if (!sse?.lastEvent) return;
    const { type } = sse.lastEvent;
    if (type === "enrichment_completed" || type === "entity_transition") {
      const id = Date.now();
      setToasts((prev) => [...prev.slice(-2), { id, event: sse.lastEvent }]);
    }
  }, [sse?.lastEvent]);

  const dismissToast = (id) => setToasts((prev) => prev.filter((t) => t.id !== id));

  if (isLoading && !stats) {
    return (
      <PageFrame eyebrow="Inteligencia" title="Dashboard">
        <LoadingSpinner label="Sincronizando health y métricas…" />
      </PageFrame>
    );
  }

  const statuses = stats?.ecosystem?.statuses || [];
  const totalTracked = statuses.reduce((sum, s) => sum + Number(s.total || 0), 0);

  return (
    <PageFrame
      eyebrow="Inteligencia"
      title="Dashboard"
      description="Resumen ejecutivo del sistema y señales de operación."
    >
      {toasts.length > 0 && (
        <div className="sse-toasts">
          {toasts.map(({ id, event }) => (
            <SseToast key={id} event={event} onDismiss={() => dismissToast(id)} />
          ))}
        </div>
      )}

      {/* Top stat cards */}
      <div className="panel-grid">
        <article className="panel">
          <p className="panel__eyebrow">System health</p>
          <h3>{health?.status || "unknown"}</h3>
          <div className="panel__badges">
            <Badge tone={health?.status || "gray"}>{health?.status || "pending"}</Badge>
            <Badge tone={stats?.worker?.alive ? "green" : "gray"}>
              worker {stats?.worker?.alive ? "alive" : "unknown"}
            </Badge>
          </div>
          <p className="panel__copy">
            Ollama: {(health?.ollama?.models || []).join(", ") || "none detected"}
          </p>
        </article>

        <article className="panel">
          <p className="panel__eyebrow">Redis cache</p>
          <h3>{stats?.cache?.total_keys ?? 0} keys</h3>
          <ScoreBar value={stats?.cache?.memory_used_mb ?? 0} max={256} label="MB used" />
        </article>

        <article className="panel">
          <p className="panel__eyebrow">GitHub rate</p>
          <h3>{stats?.githubRate?.remaining ?? "—"}</h3>
          <p className="panel__copy">Requests restantes.</p>
        </article>

        <article className="panel">
          <p className="panel__eyebrow">Enrichment queue</p>
          <h3>{stats?.worker?.pending_in_queue ?? "—"}</h3>
          <p className="panel__copy">
            Último: {stats?.worker?.last_job_type || "n/a"}
          </p>
        </article>
      </div>

      {/* Ecosystem charts */}
      <div className="panel-grid">
        <article className="panel">
          <p className="panel__eyebrow">Entidades por estado — {totalTracked} total</p>
          <StatusDonut statuses={statuses} />
        </article>

        {stats?.ecosystem?.archetypes?.length > 0 && (
          <article className="panel">
            <p className="panel__eyebrow">Por arquetipo</p>
            <div className="stack-list">
              {stats.ecosystem.archetypes
                .filter((a) => a.archetype !== "unknown" && a.total > 0)
                .slice(0, 6)
                .map((a) => (
                  <div key={a.archetype} className="stack-list__row">
                    <span>{a.archetype.replace(/_/g, " ")}</span>
                    <strong>{a.total}</strong>
                  </div>
                ))}
            </div>
          </article>
        )}

        {stats?.ecosystem?.technologies?.length > 0 && (
          <article className="panel">
            <p className="panel__eyebrow">Top tecnologías</p>
            <div className="stack-list">
              {stats.ecosystem.technologies.slice(0, 6).map((t) => (
                <div key={t.category} className="stack-list__row">
                  <span>{t.category.replace(/_/g, " ")}</span>
                  <strong>{t.mentions}</strong>
                </div>
              ))}
            </div>
          </article>
        )}
      </div>
    </PageFrame>
  );
}
