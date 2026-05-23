import { useCallback, useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { fetchEntity } from "../api/entities";
import { fetchThread, registerMessage } from "../api/outreach";
import Badge from "../components/ui/Badge";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import PageFrame from "./PageFrame";
import { formatArchetype } from "../utils/formatters";

const OUTCOME_TONE = { positive: "green", neutral: "amber", negative: "red" };
const OUTCOME_LABEL = { positive: "Positivo", neutral: "Neutral", negative: "Negativo" };
const CHANNELS = ["LinkedIn", "Twitter", "Email", "GitHub"];

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

function MessageForm({ handle, onSaved }) {
  const [direction, setDirection] = useState("out");
  const [channel, setChannel] = useState("LinkedIn");
  const [content, setContent] = useState("");
  const [outcome, setOutcome] = useState("positive");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!content.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await registerMessage(handle, {
        direction,
        content: content.trim(),
        channel,
        outcome: direction === "in" ? outcome : undefined,
      });
      setContent("");
      setDirection("out");
      onSaved();
    } catch (err) {
      setError(err.message || "Error registrando mensaje");
      setSaving(false);
    }
  }

  return (
    <form className="reply-form" onSubmit={handleSubmit} style={{ marginTop: "1.5rem", borderTop: "1px dashed var(--border)", paddingTop: "1rem" }}>
      <p className="panel__eyebrow" style={{ marginBottom: "0.5rem" }}>Registrar mensaje</p>

      {/* Direction toggle */}
      <div className="reply-form__outcomes" style={{ marginBottom: "0.5rem" }}>
        {[
          { value: "out", label: "Yo envié" },
          { value: "in", label: "Dev respondió" },
        ].map(({ value, label }) => (
          <label key={value} className={`reply-outcome ${direction === value ? "reply-outcome--active" : ""}`}>
            <input type="radio" name="direction" value={value} checked={direction === value} onChange={() => setDirection(value)} />
            {label}
          </label>
        ))}
      </div>

      {/* Channel */}
      <select
        className="entities-select"
        value={channel}
        onChange={(e) => setChannel(e.target.value)}
        style={{ marginBottom: "0.5rem" }}
      >
        {CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>

      {/* Message content */}
      <textarea
        className="modal-textarea"
        placeholder={direction === "out" ? "Texto del mensaje enviado…" : "Texto de la respuesta del developer…"}
        rows={3}
        value={content}
        onChange={(e) => setContent(e.target.value)}
        required
      />

      {/* Outcome — only for dev replies */}
      {direction === "in" && (
        <div className="reply-form__outcomes" style={{ marginTop: "0.4rem" }}>
          {["positive", "neutral", "negative"].map((o) => (
            <label key={o} className={`reply-outcome ${outcome === o ? "reply-outcome--active" : ""}`}>
              <input type="radio" name="outcome" value={o} checked={outcome === o} onChange={() => setOutcome(o)} />
              {OUTCOME_LABEL[o]}
            </label>
          ))}
        </div>
      )}

      {error && <p className="topbar__error" style={{ marginTop: "0.4rem" }}>{error}</p>}

      <button type="submit" className="btn-primary" disabled={saving || !content.trim()} style={{ marginTop: "0.6rem" }}>
        {saving ? "Guardando…" : "Registrar"}
      </button>
    </form>
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

        {/* Right: thread + form */}
        <div className="draft-main">
          {isLoading ? (
            <article className="panel"><LoadingSpinner label="Cargando conversación…" /></article>
          ) : error ? (
            <article className="panel"><p className="topbar__error">{error}</p></article>
          ) : (
            <article className="panel">
              <p className="panel__eyebrow">Conversación</p>
              {deduped.length === 0 ? (
                <p className="panel__copy" style={{ color: "var(--muted)", fontSize: "0.82rem" }}>
                  Aún no hay mensajes. Usa el formulario de abajo para registrar el primer contacto.
                </p>
              ) : (
                <div className="thread-list">
                  {deduped.map((item, i) =>
                    item.direction === "out"
                      ? <SentBubble key={i} item={item} />
                      : <ReplyBubble key={i} item={item} devHandle={handle} />
                  )}
                </div>
              )}
              <MessageForm handle={handle} onSaved={load} />
            </article>
          )}
        </div>
      </div>
    </PageFrame>
  );
}
