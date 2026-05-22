const CATEGORY_TONE = {
  // runtime
  ai_llm:        "badge--indigo",
  ai_framework:  "badge--indigo",
  mcp:           "badge--copper",
  automation:    "badge--blue",
  browser:       "badge--blue",
  infra:         "badge--amber",
  database:      "badge--green",
  monitoring:    "badge--amber",
  validation:    "badge--gray",
  auth:          "badge--slate",
  payment:       "badge--green",
  queue:         "badge--amber",
  // dev
  testing:       "badge--slate",
  linting:       "badge--gray",
  build:         "badge--gray",
  types:         "badge--slate",
};

function Section({ title, groups }) {
  const entries = Object.entries(groups).filter(([, pkgs]) => pkgs.length > 0);
  if (entries.length === 0) return null;

  return (
    <div className="stack-display__group">
      <p className="stack-display__category">{title}</p>
      <div style={{ display: "grid", gap: "0.5rem" }}>
        {entries.map(([cat, pkgs]) => {
          const unique = [...new Set(pkgs)];
          return (
            <div key={cat} style={{ display: "flex", flexWrap: "wrap", gap: "0.3rem", alignItems: "center" }}>
              <span style={{ fontSize: "0.7rem", color: "var(--muted)", minWidth: "5rem", textTransform: "uppercase", letterSpacing: "0.08em" }}>
                {cat.replace(/_/g, " ")}
              </span>
              <div className="stack-display__chips">
                {unique.map((pkg) => (
                  <span key={pkg} className={`badge ${CATEGORY_TONE[cat] || "badge--gray"}`}>
                    {pkg}
                  </span>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

export default function StackDisplay({ stackSnapshot }) {
  if (!stackSnapshot) return null;

  const runtime = stackSnapshot.runtime_deps || {};
  const dev = stackSnapshot.dev_deps || {};

  const hasRuntime = Object.values(runtime).some((pkgs) => Array.isArray(pkgs) && pkgs.length > 0);
  const hasDev = Object.values(dev).some((pkgs) => Array.isArray(pkgs) && pkgs.length > 0);

  if (!hasRuntime && !hasDev) {
    return <p className="panel__copy">No stack data available.</p>;
  }

  return (
    <div className="stack-display">
      {hasRuntime && <Section title="Runtime deps" groups={runtime} />}
      {hasDev && <Section title="Dev deps" groups={dev} />}
      {stackSnapshot.file_found && (
        <p style={{ margin: 0, fontSize: "0.72rem", color: "var(--muted)" }}>
          Source: <code>{stackSnapshot.file_found}</code>
          {stackSnapshot.raw_count != null && ` · ${stackSnapshot.raw_count} packages detected`}
        </p>
      )}
    </div>
  );
}
