import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { fetchEntity } from "../api/entities";
import { fetchThread } from "../api/outreach";
import Badge from "../components/ui/Badge";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import PageFrame from "./PageFrame";
import { formatArchetype } from "../utils/formatters";

const OUTCOME_TONE = { positive: "green", neutral: "amber", negative: "red" };
const OUTCOME_LABEL = { positive: "Positivo", neutral: "Neutral", negative: "Negativo" };

function formatTime(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  return d.toLocaleString("es-ES", {
    day: "2-digit", month: "short", year: "numeric",
    hour: "2-digit", minute: "2-digit",
  });
}

function SentBubble({ item }) {
  const src = item.meta?.source;
  const sourceLabel = src === "chatgpt" ? "ChatGPT" : src === "claude" ? "Claude" : src === "operator_edit" ? "Editado" : null;
  const channel = item.meta?.channel;
  const outcome = item.meta?.outcome;

  return (
    <div className="thread-item thread-item--out">
      <div className="thread-bubble thread-bubble--out">
        <p className="thread-bubble__content">{item.content}</p>
        <div className="thread-bubble__meta">
          {item.meta?.variant_label && (
            <span className="thread-bubble__tag">Variante {item.meta.variant_label}</span>
          )}
          {sourceLabel && (
            <span className="thread-bubble__tag">{sourceLabel}</span>
          )}
          {channel && <span className="thread-bubble__tag">{channel}</span>}
          {outcome && (
            <Badge tone={OUTCOME_TONE[outcome] || "gray"}>
              {OUTCOME_LABEL[outcome] || outcome}
            </Badge>
          )}
          <span className="thread-bubble__time">{formatTime(item.occurred_at)}</span>
        </div>
      </div>
      <div className="thread-avatar thread-avatar--out">Tú</div>
    </div>
  );
}

function ReplyBubble({ item, devHandle }) {
  const outcome = item.meta?.outcome;
  const channel = item.meta?.channel;

  return (
    <div className="thread-item thread-item--in">
      <div className="thread-avatar thread-avatar--in">@{devHandle}</div>
      <div className="thread-bubble thread-bubble--in">
        <p className="thread-bubble__content">{item.content || "(sin texto)"}</p>
        <div className="thread-bubble__meta">
          {outcome && (
            <Badge tone={OUTCOME_TONE[outcome] || "gray"}>
              {OUTCOME_LABEL[outcome] || outcome}
            </Badge>
          )}
          {channel && <span className="thread-bubble__tag">{channel}</span>}
          <span className="thread-bubble__time">{formatTime(item.occurred_at)}</span>
        </div>
      </div>
    </div>
  );
}

export default function InboxViewer() {
  const { handle } = useParams();
  const navigate = useNavigate();

  const [profile, setProfile] = useState(null);
  const [thread, setThread] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const [profileData, threadData] = await Promise.all([
        fetchEntity(handle),
        fetchThread(handle),
      ]);
      setProfile(profileData);
      setThread(threadData.thread || []);
    } catch (err) {
      setError(err.message || "Error cargando inbox");
    } finally {
      setIsLoading(false);
    }
  }, [handle]);

  useEffect(() => { load(); }, [load]);

  const dev = profile?.developer;

  // Deduplicate sent messages: keep only unique content (multiple regenerations produce duplicates)
  const deduped = [];
  const seenContent = new Set();
  for (const item of thread) {
    if (item.type === "sent") {
      const key = item.content.slice(0, 80);
      if (seenContent.has(key)) continue;
      seenContent.add(key);
    }
    deduped.push(item);
  }

  return (
    <PageFrame
      eyebrow="Outreach"
      title={`Inbox — ${dev?.name || handle}`}
      description={`@${handle} · ${deduped.length} mensaje${deduped.length !== 1 ? "s" : ""}`}
    >
      <div className="draft-layout">
        {/* Left: profile summary */}
        <aside className="draft-profile">
          <article className="panel">
            {dev?.avatar_url && (
              <img
                src={dev.avatar_url}
                alt={handle}
                style={{ width: 48, height: 48, borderRadius: "50%", marginBottom: "0.5rem" }}
              />
            )}
            {dev ? (
              <>
                <div className="panel__badges">
                  <Badge tone={dev.status}>{dev.status}</Badge>
                  {dev.archetype && <Badge tone="indigo">{formatArchetype(dev.archetype)}</Badge>}
                </div>
                {dev.bio && (
                  <p className="panel__copy" style={{ fontSize: "0.78rem", fontStyle: "italic", marginTop: "0.5rem" }}>
                    {dev.bio}
                  </p>
                )}
                <div style={{ marginTop: "0.6rem", display: "flex", flexDirection: "column", gap: "0.3rem", fontSize: "0.8rem" }}>
                  {dev.location && <span>📍 {dev.location}</span>}
                  {dev.email && <a href={`mailto:${dev.email}`} style={{ color: "var(--accent)" }}>✉ {dev.email}</a>}
                  {dev.twitter && (
                    <a href={`https://twitter.com/${dev.twitter}`} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
                      𝕏 @{dev.twitter}
                    </a>
                  )}
                  {dev.github_url && (
                    <a href={dev.github_url} target="_blank" rel="noopener noreferrer" style={{ color: "var(--accent)" }}>
                      GitHub: @{handle}
                    </a>
                  )}
                </div>
              </>
            ) : (
              <p className="panel__copy">Cargando perfil…</p>
            )}
          </article>

          <div className="draft-profile__actions">
            <button className="btn-secondary" onClick={() => navigate("/outreach")}>
              ← Volver a la cola
            </button>
            <Link to={`/outreach/${handle}`} className="btn-secondary">
              Ver draft
            </Link>
          </div>
        </aside>

        {/* Right: thread */}
        <div className="draft-main">
          {isLoading ? (
            <article className="panel"><LoadingSpinner label="Cargando conversación…" /></article>
          ) : error ? (
            <article className="panel"><p className="topbar__error">{error}</p></article>
          ) : deduped.length === 0 ? (
            <article className="panel">
              <p className="panel__eyebrow">Inbox vacío</p>
              <p className="panel__copy">Aún no hay mensajes enviados ni respuestas registradas para este developer.</p>
              <Link to={`/outreach/${handle}`} className="btn-primary" style={{ marginTop: "1rem", display: "inline-block" }}>
                Ir al draft →
              </Link>
            </article>
          ) : (
            <article className="panel">
              <p className="panel__eyebrow">Conversación</p>
              <div className="thread-list">
                {deduped.map((item, i) =>
                  item.direction === "out"
                    ? <SentBubble key={i} item={item} />
                    : <ReplyBubble key={i} item={item} devHandle={handle} />
                )}
              </div>
            </article>
          )}
        </div>
      </div>
    </PageFrame>
  );
}
