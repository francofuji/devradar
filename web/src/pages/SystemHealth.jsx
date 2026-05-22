import { useCallback, useEffect, useState } from "react";
import Badge from "../components/ui/Badge";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import ScoreBar from "../components/ui/ScoreBar";
import PageFrame from "./PageFrame";
import { fetchHealth } from "../api/system";
import { fetchCacheStats, fetchLlmStatus } from "../api/training";
import { fetchSystemMetrics, fetchGithubRateLimit } from "../api/system";

function statusTone(ok) {
  return ok ? "green" : "red";
}

function CheckRow({ label, ok, detail }) {
  return (
    <div className="health-check-row">
      <span className="health-check-row__dot" style={{ background: ok ? "#4ade80" : "#f87171" }} />
      <span className="health-check-row__label">{label}</span>
      <span className="health-check-row__detail">{detail}</span>
      <Badge tone={ok ? "green" : "red"}>{ok ? "ok" : "fail"}</Badge>
    </div>
  );
}

function MetricCard({ eyebrow, value, sub }) {
  return (
    <article className="panel">
      <p className="panel__eyebrow">{eyebrow}</p>
      <h3>{value}</h3>
      {sub && <p className="panel__copy">{sub}</p>}
    </article>
  );
}

export default function SystemHealth() {
  const [health, setHealth] = useState(null);
  const [cache, setCache] = useState(null);
  const [llm, setLlm] = useState(null);
  const [metrics, setMetrics] = useState(null);
  const [githubRate, setGithubRate] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [lastRefresh, setLastRefresh] = useState(null);

  const load = useCallback(async () => {
    const [h, c, l, m, g] = await Promise.allSettled([
      fetchHealth(),
      fetchCacheStats(),
      fetchLlmStatus(),
      fetchSystemMetrics(),
      fetchGithubRateLimit(),
    ]);
    const r = (res) => (res.status === "fulfilled" ? res.value : null);
    setHealth(r(h));
    setCache(r(c));
    setLlm(r(l));
    setMetrics(r(m));
    setGithubRate(r(g));
    setLastRefresh(new Date());
    setIsLoading(false);
  }, []);

  useEffect(() => {
    load();
    const interval = setInterval(load, 30000);
    return () => clearInterval(interval);
  }, [load]);

  if (isLoading && !health) {
    return (
      <PageFrame eyebrow="Sistema" title="Health">
        <LoadingSpinner label="Consultando salud del sistema…" />
      </PageFrame>
    );
  }

  const dbOk = health?.db?.ok ?? false;
  const redisOk = health?.redis?.ok ?? false;
  const ollamaOk = health?.ollama?.available ?? false;
  const workerAlive = health?.worker?.alive ?? false;
  const digestReady = health?.daily_digest_ready ?? false;
  const cacheOk = cache && !cache.error;
  const githubOk = githubRate?.remaining !== null && githubRate?.remaining !== undefined;

  return (
    <PageFrame
      eyebrow="Sistema"
      title="Health"
      description={lastRefresh ? `Actualizado ${lastRefresh.toLocaleTimeString("es")} · Refresh cada 30s` : ""}
    >
      <div className="health-grid">
        {/* Service checks */}
        <article className="panel health-checks">
          <p className="panel__eyebrow">Servicios</p>
          <div className="health-checks__list">
            <CheckRow
              label="PostgreSQL"
              ok={dbOk}
              detail={health?.db?.error || "ping ok"}
            />
            <CheckRow
              label="Redis"
              ok={redisOk}
              detail={health?.redis?.error || `${cache?.memory_used_mb ?? 0} MB · ${cache?.total_keys ?? 0} keys`}
            />
            <CheckRow
              label="Ollama"
              ok={ollamaOk}
              detail={(health?.ollama?.models || []).join(", ") || "no models"}
            />
            <CheckRow
              label="Worker"
              ok={workerAlive}
              detail={
                health?.worker?.last_job_type
                  ? `último: ${health.worker.last_job_type} · ${health.worker.pending_in_queue} pending`
                  : "sin actividad reciente"
              }
            />
            <CheckRow
              label="GitHub rate limit"
              ok={githubOk}
              detail={githubOk ? `${githubRate.remaining} requests restantes` : "sin datos en Redis"}
            />
            <CheckRow
              label="LLM cache"
              ok={cacheOk}
              detail={cacheOk ? `${cache.total_keys} keys · ${cache.memory_used_mb} MB` : "no disponible"}
            />
            <CheckRow
              label="Digest diario"
              ok={digestReady}
              detail={digestReady ? "generado hoy" : "no existe aún"}
            />
          </div>
        </article>

        {/* LLM provider */}
        <article className="panel">
          <p className="panel__eyebrow">LLM provider</p>
          <h3>{llm?.provider || "ollama"}</h3>
          <div className="stack-list" style={{ marginTop: "0.5rem" }}>
            {["extraction", "narrative", "draft"].map((t) => (
              <div key={t} className="stack-list__row">
                <span>{t}</span>
                <strong style={{ fontSize: "0.78rem" }}>
                  {llm?.models?.[t] || "—"}
                </strong>
              </div>
            ))}
          </div>
        </article>

        {/* Redis cache bar */}
        <article className="panel">
          <p className="panel__eyebrow">LLM cache</p>
          <h3>{cache?.total_keys ?? 0} keys</h3>
          <ScoreBar
            value={cache?.memory_used_mb ?? 0}
            max={cache?.memory_limit_mb ?? 256}
            label="MB"
          />
          <p className="panel__copy" style={{ marginTop: "0.5rem" }}>
            Límite: {cache?.memory_limit_mb ?? 256} MB
          </p>
        </article>
      </div>

      {/* Operational metrics */}
      {metrics && (
        <>
          <p className="panel__eyebrow" style={{ margin: "1.5rem 0 0.6rem" }}>Métricas de operación (24h)</p>
          <div className="panel-grid">
            <MetricCard
              eyebrow="Eventos hoy"
              value={metrics.events_today}
              sub="desde tabla events"
            />
            <MetricCard
              eyebrow="Enrichments hoy"
              value={metrics.enrichments_today}
              sub="completados en queue"
            />
            <MetricCard
              eyebrow="Cache hits"
              value={metrics.cache_hits}
              sub="contador Redis stats:cache_hits"
            />
            <MetricCard
              eyebrow="Entidades totales"
              value={metrics.statuses?.reduce((s, r) => s + Number(r.total), 0) ?? 0}
              sub={metrics.statuses?.map((s) => `${s.status}: ${s.total}`).join(" · ") || ""}
            />
          </div>
        </>
      )}

      <div style={{ marginTop: "1rem", textAlign: "right" }}>
        <button className="btn-secondary" onClick={load} style={{ fontSize: "0.82rem" }}>
          Refrescar ahora
        </button>
      </div>
    </PageFrame>
  );
}
