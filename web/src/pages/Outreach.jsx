import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchContacted, fetchOutreachQueue } from "../api/outreach";
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

const OUTREACH_STATUS_LABEL = {
  drafted: "Draft aprobado",
  sent: "Enviado",
  replied: "Respondió",
  none: "Pendiente",
};

const OUTREACH_STATUS_TONE = {
  drafted: "amber",
  sent: "indigo",
  replied: "green",
  none: "gray",
};

function ContactedCard({ item }) {
  return (
    <article className="panel outreach-card outreach-card--contacted">
      <div className="outreach-card__header">
        <div className="outreach-card__identity" style={{ display: "flex", alignItems: "center", gap: "0.6rem" }}>
          {item.avatar_url && (
            <img
              src={item.avatar_url}
              alt={item.id}
              style={{ width: 32, height: 32, borderRadius: "50%", flexShrink: 0 }}
            />
          )}
          <div>
            <span className="outreach-card__handle">{item.name || item.id}</span>
            {item.name && <span className="entity-card__sub" style={{ display: "block" }}>@{item.id}</span>}
          </div>
        </div>
        <div className="outreach-card__badges">
          <Badge tone={OUTREACH_STATUS_TONE[item.outreach_status] || "gray"}>
            {OUTREACH_STATUS_LABEL[item.outreach_status] || item.outreach_status}
          </Badge>
          {item.archetype && item.archetype !== "unknown" && (
            <Badge tone="indigo">{formatArchetype(item.archetype)}</Badge>
          )}
        </div>
      </div>

      <div style={{ display: "flex", gap: "1rem", fontSize: "0.78rem", color: "var(--text-muted)", marginTop: "0.4rem", flexWrap: "wrap" }}>
        {item.location && <span>📍 {item.location}</span>}
        {item.email && <a href={`mailto:${item.email}`} style={{ color: "var(--accent)" }}>✉ {item.email}</a>}
        {item.twitter && (
          <a href={`https://twitter.com/${item.twitter}`} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
            𝕏 @{item.twitter}
          </a>
        )}
        {item.github_url && (
          <a href={item.github_url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
            GitHub
          </a>
        )}
      </div>

      {item.narrative && (
        <p className="outreach-card__narrative" style={{ marginTop: "0.4rem" }}>{item.narrative}</p>
      )}

      <div className="outreach-card__footer">
        <span className="entity-card__age">{formatDaysAgo(item.last_active)}</span>
        <Link to={`/outreach/${item.id}`} className="btn-secondary outreach-card__cta">
          Ver perfil →
        </Link>
      </div>
    </article>
  );
}

export default function Outreach() {
  const [items, setItems] = useState([]);
  const [contacted, setContacted] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  useEffect(() => {
    Promise.all([fetchOutreachQueue(), fetchContacted()])
      .then(([queueData, contactedData]) => {
        setItems(queueData.items || []);
        setContacted(contactedData.items || []);
      })
      .catch((err) => setError(err.message || "Error loading queue"))
      .finally(() => setIsLoading(false));
  }, []);

  return (
    <PageFrame
      eyebrow="Pipeline"
      title="Cola de Outreach"
      description={`${items.length} pendiente${items.length !== 1 ? "s" : ""} · ${contacted.length} contactado${contacted.length !== 1 ? "s" : ""}`}
    >
      {isLoading ? (
        <LoadingSpinner label="Cargando cola…" />
      ) : error ? (
        <p className="topbar__error">{error}</p>
      ) : (
        <>
          {/* Pending queue */}
          {items.length === 0 ? (
            <EmptyState
              title="Cola vacía"
              description="No hay developers QUALIFIED pendientes de outreach."
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

          {/* Contacted section */}
          {contacted.length > 0 && (
            <section style={{ marginTop: "2rem" }}>
              <p className="panel__eyebrow" style={{ marginBottom: "0.8rem" }}>
                Contactados ({contacted.length})
              </p>
              <div className="outreach-queue">
                {contacted.map((item) => (
                  <ContactedCard key={item.id} item={item} />
                ))}
              </div>
            </section>
          )}
        </>
      )}
    </PageFrame>
  );
}
