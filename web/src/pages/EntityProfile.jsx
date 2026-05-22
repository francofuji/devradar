import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  fetchEntity,
  addEntityNote,
  updateLinkedIn,
  disqualifyEntity,
  enqueueEnrichment,
} from "../api/entities";
import Badge from "../components/ui/Badge";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import ScoreBar from "../components/ui/ScoreBar";
import ScoreHistory from "../components/ui/ScoreHistory";
import PainSignal from "../components/ui/PainSignal";
import StackDisplay from "../components/ui/StackDisplay";
import PageFrame from "./PageFrame";
import {
  formatArchetype,
  formatDaysAgo,
  formatScore,
  formatTrajectory,
} from "../utils/formatters";

function Section({ title, children }) {
  return (
    <section className="profile-section">
      <h4 className="profile-section__title">{title}</h4>
      {children}
    </section>
  );
}

function NoteModal({ handle, onClose, onSaved }) {
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  async function handleSubmit(e) {
    e.preventDefault();
    if (!text.trim()) return;
    setSaving(true);
    setError(null);
    try {
      await addEntityNote(handle, { text: text.trim() });
      onSaved();
      onClose();
    } catch (err) {
      setError(err.message || "Error saving note");
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h4>Agregar nota</h4>
        <form onSubmit={handleSubmit}>
          <textarea
            className="modal-textarea"
            placeholder="Nota sobre este developer…"
            rows={4}
            value={text}
            onChange={(e) => setText(e.target.value)}
            autoFocus
          />
          {error && <p className="topbar__error">{error}</p>}
          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>
              Cancelar
            </button>
            <button type="submit" className="btn-primary" disabled={saving || !text.trim()}>
              {saving ? "Guardando…" : "Guardar"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

function LinkedInModal({ handle, onClose, onSaved }) {
  const [form, setForm] = useState({ title: "", company: "", team_size: "", notes: "" });
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);

  function set(key, val) {
    setForm((prev) => ({ ...prev, [key]: val }));
  }

  async function handleSubmit(e) {
    e.preventDefault();
    if (!form.title || !form.company) return;
    setSaving(true);
    setError(null);
    try {
      await updateLinkedIn(handle, form);
      onSaved();
      onClose();
    } catch (err) {
      setError(err.message || "Error saving LinkedIn");
      setSaving(false);
    }
  }

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <h4>LinkedIn</h4>
        <form onSubmit={handleSubmit}>
          <label className="modal-label">
            Título
            <input
              className="modal-input"
              value={form.title}
              onChange={(e) => set("title", e.target.value)}
              placeholder="Senior Engineer"
              required
            />
          </label>
          <label className="modal-label">
            Empresa
            <input
              className="modal-input"
              value={form.company}
              onChange={(e) => set("company", e.target.value)}
              placeholder="Acme Corp"
              required
            />
          </label>
          <label className="modal-label">
            Tamaño del equipo
            <select
              className="modal-input"
              value={form.team_size}
              onChange={(e) => set("team_size", e.target.value)}
            >
              <option value="">— no especificado —</option>
              <option value="solo">Solo</option>
              <option value="2-5">2–5</option>
              <option value="6-20">6–20</option>
              <option value="21-100">21–100</option>
              <option value="100+">100+</option>
            </select>
          </label>
          <label className="modal-label">
            Notas
            <textarea
              className="modal-textarea"
              rows={2}
              value={form.notes}
              onChange={(e) => set("notes", e.target.value)}
            />
          </label>
          {error && <p className="topbar__error">{error}</p>}
          <div className="modal-actions">
            <button type="button" className="btn-secondary" onClick={onClose}>Cancelar</button>
            <button type="submit" className="btn-primary" disabled={saving}>
              {saving ? "Guardando…" : "Guardar"}
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

export default function EntityProfile() {
  const { handle } = useParams();
  const navigate = useNavigate();

  const [profile, setProfile] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [modal, setModal] = useState(null);
  const [actionMsg, setActionMsg] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    setError(null);
    try {
      const data = await fetchEntity(handle);
      setProfile(data);
    } catch (err) {
      setError(err.response?.status === 404 ? "Developer no encontrado." : (err.message || "Error loading profile"));
    } finally {
      setIsLoading(false);
    }
  }, [handle]);

  useEffect(() => {
    load();
  }, [load]);

  async function handleEnrich() {
    try {
      await enqueueEnrichment(handle, { enrichment_type: "full" });
      setActionMsg("Enrichment encolado.");
      setTimeout(() => setActionMsg(null), 3000);
    } catch (err) {
      setActionMsg("Error al encolar: " + (err.message || ""));
    }
  }

  async function handleDisqualify() {
    const reason = window.prompt("Razón de disqualificación:");
    if (!reason) return;
    try {
      await disqualifyEntity(handle, { reason });
      await load();
      setActionMsg("Developer disqualificado.");
      setTimeout(() => setActionMsg(null), 3000);
    } catch (err) {
      setActionMsg("Error: " + (err.message || ""));
    }
  }

  if (isLoading) {
    return (
      <PageFrame eyebrow="Entidades" title={handle}>
        <LoadingSpinner label="Cargando perfil…" />
      </PageFrame>
    );
  }

  if (error) {
    return (
      <PageFrame eyebrow="Entidades" title="Perfil">
        <p className="topbar__error">{error}</p>
      </PageFrame>
    );
  }

  const { developer: dev, memory, signals, score_history, recent_events, primary_repository } = profile;
  const hooks = memory?.specific_hooks || [];
  const painSignals = signals?.filter((s) => s.signal_type === "pain") || [];
  const linkedIn = dev.linkedin_manual;

  return (
    <PageFrame
      eyebrow="Entidades"
      title={dev.name || dev.id}
      description={dev.id !== dev.name ? `@${dev.id}` : ""}
    >
      {modal === "note" && (
        <NoteModal handle={handle} onClose={() => setModal(null)} onSaved={load} />
      )}
      {modal === "linkedin" && (
        <LinkedInModal handle={handle} onClose={() => setModal(null)} onSaved={load} />
      )}

      <div className="profile-layout">
        {/* Left column */}
        <div className="profile-main">
          <article className="panel">
            <div className="panel__badges">
              <Badge tone={dev.status}>{dev.status || "unknown"}</Badge>
              {dev.archetype && <Badge tone="indigo">{formatArchetype(dev.archetype)}</Badge>}
              {dev.outreach_status && dev.outreach_status !== "none" && (
                <Badge tone="amber">{dev.outreach_status}</Badge>
              )}
            </div>

            <div className="profile-scores">
              <div className="entity-card__score-row">
                <span>Intent {formatScore(dev.intent_score)}</span>
                <ScoreBar value={dev.intent_score} max={100} />
              </div>
              <div className="entity-card__score-row">
                <span>Maturity {formatScore(dev.maturity_score)}</span>
                <ScoreBar value={dev.maturity_score} max={100} />
              </div>
            </div>

            <div className="profile-meta">
              <span>Trayectoria 7d: {formatTrajectory(dev.trajectory_7d)}</span>
              <span>Visto: {formatDaysAgo(dev.first_seen)}</span>
              <span>Activo: {formatDaysAgo(dev.last_active)}</span>
              {dev.last_enriched && <span>Enriquecido: {formatDaysAgo(dev.last_enriched)}</span>}
            </div>

            <div className="profile-links">
              {dev.github_url && (
                <a href={dev.github_url} target="_blank" rel="noopener noreferrer" className="inline-link">
                  GitHub
                </a>
              )}
              {dev.twitter && (
                <a href={`https://twitter.com/${dev.twitter}`} target="_blank" rel="noopener noreferrer" className="inline-link">
                  Twitter
                </a>
              )}
              {dev.personal_site && (
                <a href={dev.personal_site} target="_blank" rel="noopener noreferrer" className="inline-link">
                  Web
                </a>
              )}
            </div>
          </article>

          {memory?.summary && (
            <Section title="Narrative">
              <article className="panel">
                <p className="panel__copy">{memory.summary}</p>
              </article>
            </Section>
          )}

          {hooks.length > 0 && (
            <Section title="Specific hooks">
              <article className="panel">
                <ul className="profile-hooks">
                  {hooks.map((hook, i) => (
                    <li key={i}>{hook}</li>
                  ))}
                </ul>
              </article>
            </Section>
          )}

          {painSignals.length > 0 && (
            <Section title="Pain signals">
              <div className="profile-signals">
                {painSignals.map((s, i) => (
                  <article className="panel" key={i}>
                    <PainSignal signal={s} />
                  </article>
                ))}
              </div>
            </Section>
          )}

          {primary_repository?.stack_snapshot && (
            <Section title="Stack">
              <article className="panel">
                <StackDisplay stackSnapshot={primary_repository.stack_snapshot} />
              </article>
            </Section>
          )}

          {score_history?.length > 0 && (
            <Section title="Score history">
              <article className="panel">
                <ScoreHistory history={score_history} />
              </article>
            </Section>
          )}

          {recent_events?.length > 0 && (
            <Section title="Eventos recientes">
              <article className="panel">
                <div className="stack-list">
                  {recent_events.slice(0, 15).map((ev) => (
                    <div className="stack-list__row" key={ev.id}>
                      <span>{ev.event_type}</span>
                      <span>{formatDaysAgo(ev.occurred_at)}</span>
                    </div>
                  ))}
                </div>
              </article>
            </Section>
          )}
        </div>

        {/* Right sidebar */}
        <aside className="profile-aside">
          <article className="panel">
            <p className="panel__eyebrow">Acciones</p>
            {actionMsg && <p className="panel__copy" style={{ color: "#4ade80" }}>{actionMsg}</p>}
            <div className="profile-actions">
              <button className="btn-primary" onClick={() => setModal("note")}>
                Agregar nota
              </button>
              <button className="btn-secondary" onClick={() => setModal("linkedin")}>
                LinkedIn
              </button>
              <button className="btn-secondary" onClick={handleEnrich}>
                Enriquecer
              </button>
              <button
                className="btn-danger"
                onClick={handleDisqualify}
                disabled={dev.status === "CLOSED"}
              >
                Disqualificar
              </button>
              <button className="btn-secondary" onClick={() => navigate(-1)}>
                ← Volver
              </button>
            </div>
          </article>

          {linkedIn && (
            <article className="panel">
              <p className="panel__eyebrow">LinkedIn</p>
              <strong>{linkedIn.title}</strong>
              <p className="panel__copy">{linkedIn.company}</p>
              {linkedIn.team_size && <p className="panel__copy">Equipo: {linkedIn.team_size}</p>}
              {linkedIn.notes && <p className="panel__copy">{linkedIn.notes}</p>}
            </article>
          )}
        </aside>
      </div>
    </PageFrame>
  );
}
