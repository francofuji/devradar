import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { fetchDigestByDate, fetchLatestDigest } from "../api/intelligence";
import EmptyState from "../components/ui/EmptyState";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import PageFrame from "./PageFrame";

const SECTION_ICONS = {
  "Nuevas entidades": "◈",
  "Transiciones": "⟳",
  "Alertas": "⚑",
  "Stack changes": "⬡",
  "Actividad notable": "★",
};

// Extract @handle patterns from markdown text → link to /entities/:handle
function linkifyHandles(text) {
  const parts = text.split(/(@[\w-]+)/g);
  return parts.map((part, i) => {
    if (/^@[\w-]+$/.test(part)) {
      const handle = part.slice(1);
      return (
        <Link key={i} to={`/entities/${handle}`} className="inline-link">
          {part}
        </Link>
      );
    }
    return part;
  });
}

function Section({ title, content, defaultOpen = false }) {
  const [open, setOpen] = useState(defaultOpen);
  const icon = SECTION_ICONS[title] || "·";
  const lines = content.split("\n").filter((l) => l.trim());

  return (
    <article className="digest-section panel">
      <button
        className="digest-section__toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="digest-section__icon">{icon}</span>
        <span className="digest-section__title">{title}</span>
        <span className="digest-section__chevron">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="digest-section__body">
          {lines.map((line, i) => {
            const isHeader = line.startsWith("###");
            const isBullet = line.startsWith("- ") || line.startsWith("* ");
            const text = line.replace(/^#{1,3}\s*/, "").replace(/^[-*]\s*/, "");
            if (isHeader) {
              return (
                <p key={i} className="digest-section__subheader">
                  {linkifyHandles(text)}
                </p>
              );
            }
            if (isBullet) {
              return (
                <p key={i} className="digest-section__bullet">
                  <span className="digest-bullet-dot">·</span>
                  {linkifyHandles(text)}
                </p>
              );
            }
            if (!text) return null;
            return (
              <p key={i} className="digest-section__para">
                {linkifyHandles(text)}
              </p>
            );
          })}
        </div>
      )}
    </article>
  );
}

export default function Digest() {
  const [digest, setDigest] = useState(null);
  const [date, setDate] = useState("");
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);

  const load = useCallback(async (targetDate) => {
    setIsLoading(true);
    setError(null);
    try {
      const data = targetDate
        ? await fetchDigestByDate(targetDate)
        : await fetchLatestDigest();
      setDigest(data);
      setDate(data.date || "");
    } catch (err) {
      setError(err.message || "Error cargando digest");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    load(null);
  }, [load]);

  const today = new Date().toISOString().slice(0, 10);

  return (
    <PageFrame
      eyebrow="Outputs"
      title="Digest Diario"
      description={digest ? `Reporte del ${digest.date}` : "Generado a las 07:00 UTC cada día."}
    >
      <div className="digest-toolbar">
        <input
          type="date"
          className="entities-search digest-date-input"
          value={date}
          max={today}
          onChange={(e) => {
            setDate(e.target.value);
            if (e.target.value) load(e.target.value);
          }}
        />
        <button
          className="btn-secondary"
          onClick={() => load(null)}
          disabled={isLoading}
        >
          Último digest
        </button>
      </div>

      {isLoading ? (
        <LoadingSpinner label="Cargando digest…" />
      ) : error ? (
        <EmptyState
          title="Sin digest disponible"
          description={error}
        />
      ) : !digest?.sections?.length ? (
        <EmptyState
          title="Digest vacío"
          description="El digest de hoy aún no tiene contenido. Vuelve después de las 07:00 UTC."
        />
      ) : (
        <div className="digest-sections">
          {digest.sections.map((section, i) => (
            <Section
              key={section.title}
              title={section.title}
              content={section.content}
              defaultOpen={i === 0}
            />
          ))}
        </div>
      )}
    </PageFrame>
  );
}
