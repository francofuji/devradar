import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchAlerts } from "../api/intelligence";
import Badge from "../components/ui/Badge";
import EmptyState from "../components/ui/EmptyState";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import PageFrame from "./PageFrame";

function urgencyFromId(id) {
  // id format: alert_YYYYMMDD_HHMMSS_handle or similar
  const match = id.match(/(\d{8})/);
  if (!match) return "gray";
  const dateStr = match[1];
  const alertDate = new Date(
    `${dateStr.slice(0, 4)}-${dateStr.slice(4, 6)}-${dateStr.slice(6, 8)}`
  );
  const days = Math.floor((Date.now() - alertDate.getTime()) / 86400000);
  if (days < 2) return "red";
  if (days <= 5) return "copper";
  return "gray";
}

function handleFromId(id) {
  // Try to extract a github handle from the alert filename
  const parts = id.split("_");
  return parts.length > 1 ? parts[parts.length - 1] : null;
}

function AlertCard({ alert }) {
  const tone = urgencyFromId(alert.id);
  const handle = handleFromId(alert.id);
  const preview = alert.preview || "";
  const firstLine = preview.split("\n").find((l) => l.trim()) || "";

  return (
    <article className="panel alert-card">
      <div className="alert-card__header">
        <div className="alert-card__id">
          <Badge tone={tone}>{tone === "red" ? "urgente" : tone === "copper" ? "reciente" : "archivada"}</Badge>
          <span className="alert-card__name">{alert.id}</span>
        </div>
      </div>

      {firstLine && (
        <p className="alert-card__preview">{firstLine.replace(/^#{1,3}\s*/, "")}</p>
      )}

      {alert.sections?.slice(0, 2).map((s) => (
        <div key={s.title} className="alert-card__section">
          <p className="digest-section__subheader">{s.title}</p>
          <p className="panel__copy">{s.content.slice(0, 200)}{s.content.length > 200 ? "…" : ""}</p>
        </div>
      ))}

      <div className="alert-card__actions">
        {handle && (
          <>
            <Link to={`/entities/${handle}`} className="btn-secondary alert-card__btn">
              Ver perfil
            </Link>
            <Link to={`/outreach/${handle}`} className="btn-primary alert-card__btn">
              Ver draft
            </Link>
          </>
        )}
      </div>
    </article>
  );
}

export default function Alerts() {
  const [items, setItems] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchAlerts()
      .then((data) => setItems(data.items || []))
      .catch((err) => setError(err.message || "Error cargando alertas"))
      .finally(() => setIsLoading(false));
  }, []);

  return (
    <PageFrame
      eyebrow="Outputs"
      title="Alertas"
      description={`${items.length} alerta${items.length !== 1 ? "s" : ""} de intención detectada.`}
    >
      {isLoading ? (
        <LoadingSpinner label="Cargando alertas…" />
      ) : error ? (
        <p className="topbar__error">{error}</p>
      ) : items.length === 0 ? (
        <EmptyState
          title="Sin alertas"
          description="No hay alertas generadas aún. El sistema emite alertas cuando detecta señales de intención fuerte en nuevos developers."
        />
      ) : (
        <div className="page">
          {items.map((alert) => (
            <AlertCard key={alert.id} alert={alert} />
          ))}
        </div>
      )}
    </PageFrame>
  );
}
