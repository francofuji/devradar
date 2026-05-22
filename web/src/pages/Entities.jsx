import { useCallback, useEffect, useRef, useState } from "react";
import { fetchEntities } from "../api/entities";
import EntityCard from "../components/ui/EntityCard";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import EmptyState from "../components/ui/EmptyState";
import PageFrame from "./PageFrame";

const STATUSES = ["DISCOVERED", "PROFILED", "MONITORED", "WARM", "QUALIFIED", "OUTREACHED", "ENGAGED", "CLOSED"];
const ARCHETYPES = [
  "solo_agent_builder",
  "automation_builder",
  "mcp_platform_builder",
  "technical_founder",
  "ai_agency_builder",
  "growth_engineer",
];

const PAGE_SIZE = 50;

export default function Entities() {
  const [items, setItems] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState(null);
  const [offset, setOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [search, setSearch] = useState("");

  const [filters, setFilters] = useState({
    status: "",
    archetype: "",
    trajectory: "",
    min_score: 0,
  });

  const debounceRef = useRef(null);

  const load = useCallback(async (newOffset = 0, currentFilters = filters) => {
    setIsLoading(true);
    setError(null);
    try {
      const params = {
        limit: PAGE_SIZE,
        offset: newOffset,
        min_score: currentFilters.min_score || 0,
      };
      if (currentFilters.status) params.status = currentFilters.status;
      if (currentFilters.archetype) params.archetype = currentFilters.archetype;
      if (currentFilters.trajectory) params.trajectory = currentFilters.trajectory;

      const data = await fetchEntities(params);
      const incoming = data.items || [];
      setItems(newOffset === 0 ? incoming : (prev) => [...prev, ...incoming]);
      setHasMore(incoming.length === PAGE_SIZE);
      setOffset(newOffset);
    } catch (err) {
      setError(err.message || "Failed to load entities");
    } finally {
      setIsLoading(false);
    }
  }, [filters]);

  useEffect(() => {
    load(0, filters);
  }, [filters]);

  function handleFilterChange(key, value) {
    setFilters((prev) => ({ ...prev, [key]: value }));
  }

  function handleScoreChange(e) {
    clearTimeout(debounceRef.current);
    const val = Number(e.target.value);
    debounceRef.current = setTimeout(() => {
      setFilters((prev) => ({ ...prev, min_score: val }));
    }, 400);
  }

  const filtered = search.trim()
    ? items.filter(
        (e) =>
          e.id?.toLowerCase().includes(search.toLowerCase()) ||
          e.name?.toLowerCase().includes(search.toLowerCase())
      )
    : items;

  return (
    <PageFrame
      eyebrow="Inteligencia"
      title="Entidades"
      description="Developers monitoreados — filtra por estado, arquetipo, trayectoria y score mínimo."
    >
      <div className="entities-toolbar">
        <input
          className="entities-search"
          type="search"
          placeholder="Buscar por handle o nombre…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />

        <select
          className="entities-select"
          value={filters.status}
          onChange={(e) => handleFilterChange("status", e.target.value)}
        >
          <option value="">Todos los estados</option>
          {STATUSES.map((s) => (
            <option key={s} value={s}>{s}</option>
          ))}
        </select>

        <select
          className="entities-select"
          value={filters.archetype}
          onChange={(e) => handleFilterChange("archetype", e.target.value)}
        >
          <option value="">Todos los arquetipos</option>
          {ARCHETYPES.map((a) => (
            <option key={a} value={a}>{a.replace(/_/g, " ")}</option>
          ))}
        </select>

        <select
          className="entities-select"
          value={filters.trajectory}
          onChange={(e) => handleFilterChange("trajectory", e.target.value)}
        >
          <option value="">Trayectoria</option>
          <option value="up">↑ Subiendo</option>
          <option value="flat">→ Plana</option>
          <option value="down">↓ Bajando</option>
        </select>

        <label className="entities-score-filter">
          <span>Score ≥ {filters.min_score}</span>
          <input
            type="range"
            min={0}
            max={100}
            step={5}
            defaultValue={0}
            onChange={handleScoreChange}
          />
        </label>
      </div>

      {error && (
        <p className="topbar__error">{error}</p>
      )}

      {isLoading && items.length === 0 ? (
        <LoadingSpinner label="Cargando entidades…" />
      ) : filtered.length === 0 ? (
        <EmptyState
          title="Sin resultados"
          description="No hay entidades que coincidan con los filtros actuales."
        />
      ) : (
        <>
          <div className="panel-grid entities-grid">
            {filtered.map((entity) => (
              <EntityCard key={entity.id} entity={entity} />
            ))}
          </div>

          {hasMore && !search && (
            <div style={{ textAlign: "center", marginTop: "1.5rem" }}>
              <button
                className="btn-load-more"
                onClick={() => load(offset + PAGE_SIZE)}
                disabled={isLoading}
              >
                {isLoading ? "Cargando…" : `Cargar más (${items.length} cargados)`}
              </button>
            </div>
          )}
        </>
      )}
    </PageFrame>
  );
}
