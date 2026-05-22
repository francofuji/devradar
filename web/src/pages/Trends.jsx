import { useEffect, useState } from "react";
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { fetchEcosystemStats, fetchLatestTrends } from "../api/intelligence";
import EmptyState from "../components/ui/EmptyState";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import PageFrame from "./PageFrame";

const TECH_COLORS = [
  "#534AB7", "#185FA5", "#3B6D11", "#854F0B", "#7C3A10",
  "#A32D2D", "#2D6A9F", "#4B6E2A", "#6B4C9B", "#1E6F6F",
];

const CustomTooltip = ({ active, payload, label }) => {
  if (!active || !payload?.length) return null;
  return (
    <div className="score-tooltip">
      <p className="score-tooltip__label">{label}</p>
      {payload.map((entry) => (
        <p key={entry.name} style={{ color: entry.fill || entry.color }}>
          {entry.name}: {entry.value}
        </p>
      ))}
    </div>
  );
};

function TechChart({ data }) {
  if (!data?.length) return <p className="panel__copy">Sin datos de tecnologías.</p>;
  const top = data.slice(0, 12);
  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={top} margin={{ top: 4, right: 8, bottom: 40, left: -10 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.07)" vertical={false} />
        <XAxis
          dataKey="category"
          tick={{ fill: "#6b7280", fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          angle={-35}
          textAnchor="end"
          interval={0}
        />
        <YAxis
          tick={{ fill: "#6b7280", fontSize: 11 }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
        <Bar dataKey="mentions" name="repos" radius={[4, 4, 0, 0]}>
          {top.map((_, i) => (
            <Cell key={i} fill={TECH_COLORS[i % TECH_COLORS.length]} />
          ))}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

function ArchetypeChart({ data }) {
  if (!data?.length) return <p className="panel__copy">Sin datos de arquetipos.</p>;
  const filtered = data.filter((d) => d.archetype !== "unknown" && d.total > 0);
  return (
    <ResponsiveContainer width="100%" height={200}>
      <BarChart data={filtered} layout="vertical" margin={{ top: 4, right: 16, bottom: 4, left: 8 }}>
        <CartesianGrid strokeDasharray="3 3" stroke="rgba(0,0,0,0.07)" horizontal={false} />
        <XAxis type="number" tick={{ fill: "#6b7280", fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis
          type="category"
          dataKey="archetype"
          width={140}
          tick={{ fill: "#6b7280", fontSize: 10 }}
          axisLine={false}
          tickLine={false}
          tickFormatter={(v) => v.replace(/_/g, " ")}
        />
        <Tooltip content={<CustomTooltip />} cursor={{ fill: "rgba(0,0,0,0.04)" }} />
        <Bar dataKey="total" name="developers" fill="#534AB7" radius={[0, 4, 4, 0]} />
      </BarChart>
    </ResponsiveContainer>
  );
}

function LanguageTable({ data }) {
  if (!data?.length) return <p className="panel__copy">Sin datos de lenguajes.</p>;
  const top = data.filter((d) => d.primary_language).slice(0, 10);
  const max = top[0]?.total || 1;
  return (
    <div className="stack-list">
      {top.map((row) => (
        <div key={row.primary_language} className="stack-list__row">
          <span>{row.primary_language}</span>
          <div className="lang-bar-wrap">
            <div
              className="lang-bar-fill"
              style={{ width: `${Math.round((row.total / max) * 100)}%` }}
            />
          </div>
          <strong>{row.total}</strong>
        </div>
      ))}
    </div>
  );
}

export default function Trends() {
  const [stats, setStats] = useState(null);
  const [trends, setTrends] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  useEffect(() => {
    Promise.allSettled([fetchEcosystemStats(), fetchLatestTrends()]).then(
      ([statsRes, trendsRes]) => {
        if (statsRes.status === "fulfilled") setStats(statsRes.value);
        if (trendsRes.status === "fulfilled") setTrends(trendsRes.value);
        setIsLoading(false);
      }
    );
  }, []);

  if (isLoading) {
    return (
      <PageFrame eyebrow="Outputs" title="Tendencias">
        <LoadingSpinner label="Cargando tendencias…" />
      </PageFrame>
    );
  }

  return (
    <PageFrame
      eyebrow="Outputs"
      title="Tendencias"
      description={trends ? `Reporte semanal: ${trends.week}` : "Distribución del ecosistema monitoreado."}
    >
      <div className="page">
        {stats?.technologies?.length > 0 && (
          <article className="panel">
            <p className="panel__eyebrow">Stack tecnológico — menciones por categoría</p>
            <TechChart data={stats.technologies} />
          </article>
        )}

        <div className="panel-grid">
          {stats?.archetypes?.length > 0 && (
            <article className="panel">
              <p className="panel__eyebrow">Distribución por arquetipo</p>
              <ArchetypeChart data={stats.archetypes} />
            </article>
          )}

          {stats?.languages?.length > 0 && (
            <article className="panel">
              <p className="panel__eyebrow">Lenguajes primarios</p>
              <LanguageTable data={stats.languages} />
            </article>
          )}
        </div>

        {trends?.sections?.length > 0 && (
          <article className="panel">
            <p className="panel__eyebrow">Reporte semanal — {trends.week}</p>
            {trends.sections.slice(0, 4).map((s) => (
              <div key={s.title} className="trends-section">
                <p className="digest-section__subheader">{s.title}</p>
                <p className="panel__copy">{s.content.slice(0, 400)}{s.content.length > 400 ? "…" : ""}</p>
              </div>
            ))}
          </article>
        )}

        {!stats && !trends && (
          <EmptyState
            title="Sin datos"
            description="Aún no hay suficientes datos de ecosistema. Ejecuta make collect && make enrich."
          />
        )}
      </div>
    </PageFrame>
  );
}
