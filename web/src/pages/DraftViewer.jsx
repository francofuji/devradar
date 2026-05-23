import { useCallback, useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { fetchEntity } from "../api/entities";
import { approveDraft, fetchDraft, fetchDraftPrompt, regenerateDraft, registerReply } from "../api/outreach";
import Badge from "../components/ui/Badge";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import PainSignal from "../components/ui/PainSignal";
import ScoreBar from "../components/ui/ScoreBar";
import PageFrame from "./PageFrame";
import { formatArchetype, formatDaysAgo, formatScore } from "../utils/formatters";

const CHANNELS = ["LinkedIn", "Twitter", "Email"];
const SOURCES = [
  { value: "chatgpt", label: "ChatGPT" },
  { value: "claude", label: "Claude" },
  { value: "other", label: "Otro" },
];

function wordCount(text) {
  return (text || "").trim().split(/\s+/).filter(Boolean).length;
}

// Extract variant label ("A", "B"…) from section title like "Variante 1 — A"
function extractVariantLabel(title) {
  const m = title.match(/—\s*([A-Z])$/);
  return m ? m[1] : null;
}

function DraftEditor({ section, value, onChange, disabled, onApprove, approveState }) {
  const original = section.content;
  const edited = !disabled && value !== original;
  const wc = wordCount(value);
  const wcOver = !disabled && wc > 50;
  const variantLabel = extractVariantLabel(section.title);
  const isVariant = !!variantLabel;

  const [showExternal, setShowExternal] = useState(false);
  const [externalText, setExternalText] = useState("");
  const [externalSource, setExternalSource] = useState("chatgpt");

  function handleApprove() {
    if (externalText.trim()) {
      onApprove(externalText.trim(), externalSource, variantLabel);
    } else {
      onApprove(value, "operator_edit", variantLabel);
    }
  }

  const isApproved = approveState === "approved";
  const isApproving = approveState === "approving";

  return (
    <div className={`draft-editor${disabled ? " draft-editor--loading" : ""}`}>
      <div className="draft-editor__header">
        <span className="draft-editor__title">{section.title}</span>
        {edited && <Badge tone="amber">Editado</Badge>}
        {isApproved && <Badge tone="green">Aprobado ✓</Badge>}
        {!disabled && (
          <span className={`draft-editor__wc ${wcOver ? "draft-editor__wc--over" : ""}`}>
            {wc} palabras{wcOver ? " ⚠ >50" : ""}
          </span>
        )}
      </div>

      <textarea
        className="draft-editor__textarea"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        rows={Math.max(4, value.split("\n").length + 1)}
        disabled={disabled || isApproved}
        style={disabled ? { opacity: 0.45, fontStyle: "italic", cursor: "wait" } : {}}
      />

      {isVariant && !isApproved && !disabled && (
        <div className="draft-variant-actions">
          <button
            className="btn-ghost"
            onClick={() => setShowExternal((v) => !v)}
          >
            {showExternal ? "▲ Ocultar versión externa" : "▼ Pegar versión externa (ChatGPT / Claude)"}
          </button>

          <button
            className="btn-primary"
            onClick={handleApprove}
            disabled={isApproving}
          >
            {isApproving ? "Aprobando…" : `Aprobar variante ${variantLabel}`}
          </button>

          {showExternal && (
            <div className="draft-external">
              <div className="draft-external__header">
                <span style={{ fontSize: "0.75rem", color: "var(--text-muted)" }}>Fuente:</span>
                {SOURCES.map((s) => (
                  <label key={s.value} className={`reply-outcome ${externalSource === s.value ? "reply-outcome--active" : ""}`}>
                    <input
                      type="radio"
                      name={`source-${section.title}`}
                      value={s.value}
                      checked={externalSource === s.value}
                      onChange={() => setExternalSource(s.value)}
                    />
                    {s.label}
                  </label>
                ))}
              </div>
              <textarea
                className="draft-editor__textarea"
                placeholder="Pegar aquí la respuesta de ChatGPT o Claude…"
                value={externalText}
                onChange={(e) => setExternalText(e.target.value)}
                rows={5}
              />
              {externalText.trim() && (
                <span style={{ fontSize: "0.7rem", color: "var(--text-muted)" }}>
                  ✓ Se usará esta versión como approved_output al aprobar.
                </span>
              )}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function ReplyForm({ handle, onSaved }) {
  const [outcome, setOutcome] = useState("positive");
  const [channel, setChannel] = useState("LinkedIn");
  const [notes, setNotes] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!notes.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await registerReply(handle, { outcome, channel, notes: notes.trim() });
      onSaved();
    } catch (err) {
      setError(err.message || "Error registering reply");
      setSaving(false);
    }
  }

  return (
    <form className="reply-form" onSubmit={handleSubmit}>
      <p className="panel__eyebrow">Registrar respuesta</p>
      <div className="reply-form__outcomes">
        {["positive", "neutral", "negative"].map((o) => (
          <label key={o} className={`reply-outcome ${outcome === o ? "reply-outcome--active" : ""}`}>
            <input type="radio" name="outcome" value={o} checked={outcome === o} onChange={() => setOutcome(o)} />
            {o}
          </label>
        ))}
      </div>
      <select className="entities-select" value={channel} onChange={(e) => setChannel(e.target.value)} style={{ marginTop: "0.5rem" }}>
        {CHANNELS.map((c) => <option key={c} value={c}>{c}</option>)}
      </select>
      <textarea
        className="modal-textarea"
        placeholder="Notas sobre la respuesta…"
        rows={3}
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
        required
      />
      {error && <p className="topbar__error">{error}</p>}
      <button type="submit" className="btn-primary" disabled={saving || !notes.trim()}>
        {saving ? "Guardando…" : "Registrar"}
      </button>
    </form>
  );
}

export default function DraftViewer() {
  const { handle } = useParams();
  const navigate = useNavigate();

  const [profile, setProfile] = useState(null);
  const [draft, setDraft] = useState(null);
  const [isLoadingProfile, setIsLoadingProfile] = useState(true);
  const [isLoadingDraft, setIsLoadingDraft] = useState(true);
  const [draftError, setDraftError] = useState(null);

  const [edits, setEdits] = useState({});
  const [regenerating, setRegenerating] = useState(false);
  const [regenerated, setRegenerated] = useState(false);
  const [copied, setCopied] = useState(false);
  const [showReply, setShowReply] = useState(false);

  // Per-variant approve state: { "A": "idle"|"approving"|"approved"|"error" }
  const [variantState, setVariantState] = useState({});
  const [approveError, setApproveError] = useState(null);

  const draftPanelRef = useRef(null);

  const loadProfile = useCallback(async () => {
    try {
      const data = await fetchEntity(handle);
      setProfile(data);
    } catch {
      // non-blocking
    } finally {
      setIsLoadingProfile(false);
    }
  }, [handle]);

  const loadDraft = useCallback(async () => {
    setIsLoadingDraft(true);
    setDraftError(null);
    try {
      const data = await fetchDraft(handle);
      setDraft(data);
      const initial = {};
      for (const s of data.sections || []) {
        initial[s.title] = s.content;
      }
      setEdits(initial);
      setVariantState({});
    } catch (err) {
      setDraftError(err.message || "Error loading draft");
    } finally {
      setIsLoadingDraft(false);
    }
  }, [handle]);

  useEffect(() => {
    loadProfile();
    loadDraft();
  }, [loadProfile, loadDraft]);

  async function handleApproveVariant(approvedText, source, variantLabel) {
    setVariantState((prev) => ({ ...prev, [variantLabel]: "approving" }));
    setApproveError(null);
    try {
      await approveDraft(handle, {
        approved_output: approvedText,
        variant_label: variantLabel,
        source,
      });
      setVariantState((prev) => ({ ...prev, [variantLabel]: "approved" }));
      setShowReply(true);
    } catch (err) {
      setVariantState((prev) => ({ ...prev, [variantLabel]: "error" }));
      setApproveError(err.message || "Error aprobando variante");
    }
  }

  const dev = profile?.developer;
  const signals = profile?.signals?.filter((s) => s.signal_type === "pain") || [];
  const memory = profile?.memory;
  const hooks = memory?.specific_hooks || [];

  const variantSections = (draft?.sections || []).filter((s) => extractVariantLabel(s.title));
  const approvedCount = Object.values(variantState).filter((v) => v === "approved").length;
  const outreachStatus = dev?.outreach_status;
  const showReplyPanel = outreachStatus === "drafted" || outreachStatus === "sent" || showReply;

  return (
    <PageFrame
      eyebrow="Outreach"
      title={dev?.name || handle}
      description={dev ? `@${handle} · intent ${formatScore(dev.intent_score)}` : handle}
    >
      <div className="draft-layout">
        {/* Left: profile summary */}
        <aside className="draft-profile">
          <article className="panel">
            {isLoadingProfile ? (
              <LoadingSpinner label="Cargando perfil…" />
            ) : dev ? (
              <>
                <div className="panel__badges">
                  <Badge tone={dev.status}>{dev.status}</Badge>
                  {dev.archetype && <Badge tone="indigo">{formatArchetype(dev.archetype)}</Badge>}
                </div>
                <div className="profile-scores" style={{ marginTop: "0.6rem" }}>
                  <div className="entity-card__score-row">
                    <span>Intent {formatScore(dev.intent_score)}</span>
                    <ScoreBar value={dev.intent_score} max={100} />
                  </div>
                  <div className="entity-card__score-row">
                    <span>Maturity {formatScore(dev.maturity_score)}</span>
                    <ScoreBar value={dev.maturity_score} max={100} />
                  </div>
                </div>
                <p className="panel__copy" style={{ marginTop: "0.5rem" }}>
                  Activo {formatDaysAgo(dev.last_active)}
                </p>
              </>
            ) : (
              <p className="panel__copy">Perfil no disponible.</p>
            )}
          </article>

          {memory?.summary && (
            <article className="panel">
              <p className="panel__eyebrow">Narrative</p>
              <p className="panel__copy">{memory.summary}</p>
            </article>
          )}

          {hooks.length > 0 && (
            <article className="panel">
              <p className="panel__eyebrow">Hooks de evidencia</p>
              <ul className="profile-hooks">
                {hooks.map((h, i) => <li key={i}>{h}</li>)}
              </ul>
            </article>
          )}

          {signals.length > 0 && (
            <article className="panel">
              <p className="panel__eyebrow">Pain signals</p>
              <div className="profile-signals">
                {signals.slice(0, 3).map((s, i) => <PainSignal key={i} signal={s} />)}
              </div>
            </article>
          )}

          <div className="draft-profile__actions">
            <button className="btn-secondary" onClick={() => navigate("/outreach")}>
              ← Volver a la cola
            </button>
          </div>
        </aside>

        {/* Right: draft editor */}
        <div className="draft-main">
          {isLoadingDraft ? (
            <article className="panel">
              <LoadingSpinner label="Generando draft…" />
            </article>
          ) : draftError ? (
            <article className="panel">
              <p className="topbar__error">{draftError}</p>
              <button className="btn-secondary" onClick={loadDraft} style={{ marginTop: "0.8rem" }}>
                Reintentar
              </button>
            </article>
          ) : (
            <>
              <article className="panel">
                <div className="draft-header">
                  <p className="panel__eyebrow">
                    Draft{draft?.generated ? " — generado ahora" : " — existente"}
                  </p>
                  {approvedCount > 0 && (
                    <Badge tone="green">{approvedCount} de {variantSections.length} aprobadas</Badge>
                  )}
                </div>

                <div className="draft-sections">
                  {(draft?.sections || []).map((section) => (
                    <DraftEditor
                      key={section.title}
                      section={section}
                      value={regenerating ? "GENERANDO..." : (edits[section.title] ?? section.content)}
                      onChange={(val) =>
                        !regenerating && setEdits((prev) => ({ ...prev, [section.title]: val }))
                      }
                      disabled={regenerating}
                      onApprove={handleApproveVariant}
                      approveState={variantState[extractVariantLabel(section.title)] || "idle"}
                    />
                  ))}
                </div>

                <div className="draft-actions">
                  <button
                    className="btn-secondary"
                    onClick={() => {
                      const initial = {};
                      for (const s of draft.sections || []) initial[s.title] = s.content;
                      setEdits(initial);
                      setVariantState({});
                    }}
                  >
                    Resetear
                  </button>
                  <button
                    className="btn-secondary"
                    disabled={regenerating}
                    onClick={async () => {
                      setRegenerating(true);
                      setRegenerated(false);
                      setEdits({});
                      setVariantState({});
                      setDraftError(null);
                      try {
                        const data = await regenerateDraft(handle);
                        setDraft(data);
                        const initial = {};
                        for (const s of data.sections || []) initial[s.title] = s.content;
                        setEdits(initial);
                        setRegenerated(true);
                        setTimeout(() => setRegenerated(false), 3000);
                      } catch (err) {
                        setDraftError(err.message || "Error regenerando draft");
                      } finally {
                        setRegenerating(false);
                      }
                    }}
                  >
                    {regenerating ? "Generando…" : "Regenerar"}
                  </button>
                  {regenerated && <Badge tone="green">¡Regenerado! ✓</Badge>}
                  <button
                    className="btn-secondary"
                    onClick={async () => {
                      try {
                        const data = await fetchDraftPrompt(handle);
                        await navigator.clipboard.writeText(data.combined);
                        setCopied(true);
                        setTimeout(() => setCopied(false), 3000);
                      } catch {
                        // fallback silencioso
                      }
                    }}
                  >
                    {copied ? "¡Copiado! ✓" : "Copiar prompt"}
                  </button>
                </div>

                {approveError && <p className="topbar__error" style={{ marginTop: "0.5rem" }}>{approveError}</p>}
              </article>

              {(showReplyPanel) && (
                <article className="panel">
                  <ReplyForm
                    handle={handle}
                    onSaved={() => {
                      setShowReply(false);
                      navigate("/outreach");
                    }}
                  />
                </article>
              )}
            </>
          )}
        </div>
      </div>
    </PageFrame>
  );
}
