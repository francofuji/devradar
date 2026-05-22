import { useEffect } from "react";
import Badge from "../ui/Badge";
import useSystemStore from "../../store/useSystemStore";

function healthTone(status) {
  if (status === "ok") {
    return "ok";
  }
  if (status === "degraded") {
    return "amber";
  }
  return "gray";
}

export default function TopBar({ sse }) {
  const { health, stats, isLoading, fetchHealth, fetchStats } = useSystemStore();

  useEffect(() => {
    fetchHealth().catch(() => undefined);
    fetchStats().catch(() => undefined);
  }, [fetchHealth, fetchStats]);

  return (
    <header className="topbar">
      <div>
        <p className="topbar__eyebrow">Dev Intelligence Platform</p>
        <h1>Agent Infrastructure Lead Radar</h1>
      </div>

      <div className="topbar__status-grid">
        <article className="status-card">
          <span>System health</span>
          <strong>{health?.status || (isLoading ? "loading" : "unknown")}</strong>
          <Badge tone={healthTone(health?.status)}>{health?.status || "pending"}</Badge>
        </article>

        <article className="status-card">
          <span>SSE stream</span>
          <strong>{sse.status}</strong>
          <Badge tone={sse.status}>{sse.status}</Badge>
        </article>

        <article className="status-card">
          <span>Worker</span>
          <strong>{stats?.worker?.pending_in_queue ?? "—"} pending</strong>
          <p>{stats?.worker?.last_job_type || "No job metadata yet"}</p>
        </article>

        <article className="status-card">
          <span>LLM cache</span>
          <strong>{stats?.cache?.total_keys ?? "—"} keys</strong>
          <p>{stats?.cache?.memory_used_mb ?? "—"} MB used</p>
        </article>
      </div>

    </header>
  );
}
