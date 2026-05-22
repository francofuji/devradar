import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchOutreachQueue } from "../api/outreach";
import Badge from "../components/ui/Badge";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import EmptyState from "../components/ui/EmptyState";
import ScoreBar from "../components/ui/ScoreBar";
import PageFrame from "./PageFrame";
import { formatArchetype, formatDaysAgo, formatScore } from "../utils/formatters";

function urgencyTone(lastEnriched) {
  if (!lastEnriched) return "gray";
  const days = Math.floor((Date.now() - new Date(lastEnriched).getTime()) / 86400000);
  if (days < 2) return "red";
  if (days <= 5) return "copper";
  return "gray";
}

function urgencyLabel(lastEnriched) {
  if (!lastEnriched) return "unknown";
  const days = Math.floor((Date.now() - new Date(lastEnriched).getTime()) / 86400000);
  if (days === 0) return "hoy";
  if (days === 1) return "ayer";
  return `${days}d`;
}

function wordCount(text) {
  return (text || "").trim().split(/\s+/).filter(Boolean).length;
}

export default function Outreach() {
  const [items, setItems] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    fetchOutreachQueue()
      .then((data) => setItems(data.items || []))
      .catch((err) => setError(err.message || "Error loading queue"))
      .finally(() => setIsLoading(false));
  }, []);

  return (
    <PageFrame
      eyebrow="Pipeline"
      title="Cola de Outreach"
      description={`${items.length} developer${items.length !== 1 ? "s" : ""} QUALIFIED sin outreach — ordenados por intent score.`}
    >
      {isLoading ? (
        <LoadingSpinner label="Cargando cola…" />
      ) : error ? (
        <p className="topbar__error">{error}</p>
      ) : items.length === 0 ? (
        <EmptyState
          title="Cola vacía"
          description="No hay developers QUALIFIED con outreach_status='none'. Cuando el sistema califique nuevos developers, aparecerán aquí."
        />
      ) : (
        <div className="outreach-queue">
          {items.map((item) => (
            <article key={item.id} className="panel outreach-card">
              <div className="outreach-card__header">
                <div className="outreach-card__identity">
                  <span className="outreach-card__handle">{item.name || item.id}</span>
                  {item.name && <span className="entity-card__sub">@{item.id}</span>}
                </div>
                <div className="outreach-card__badges">
                  <Badge tone={urgencyTone(item.last_enriched)}>
                    {urgencyLabel(item.last_enriched)}
                  </Badge>
                  {item.archetype && item.archetype !== "unknown" && (
                    <Badge tone="indigo">{formatArchetype(item.archetype)}</Badge>
                  )}
                </div>
              </div>

              <div className="outreach-card__score">
                <div className="entity-card__score-row">
                  <span>Intent {formatScore(item.intent_score)}</span>
                  <ScoreBar value={item.intent_score} max={100} />
                </div>
              </div>

              {item.narrative && (
                <p className="outreach-card__narrative">{item.narrative}</p>
              )}

              {item.specific_hooks?.length > 0 && (
                <ul className="outreach-card__hooks">
                  {item.specific_hooks.slice(0, 2).map((h, i) => (
                    <li key={i}>{h}</li>
                  ))}
                </ul>
              )}

              <div className="outreach-card__footer">
                <span className="entity-card__age">{formatDaysAgo(item.last_active)}</span>
                <Link to={`/outreach/${item.id}`} className="btn-primary outreach-card__cta">
                  Ver draft →
                </Link>
              </div>
            </article>
          ))}
        </div>
      )}
    </PageFrame>
  );
}
