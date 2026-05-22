import { useCallback, useEffect, useRef, useState } from "react";
import Badge from "../components/ui/Badge";
import EmptyState from "../components/ui/EmptyState";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import PageFrame from "./PageFrame";
import { createTaxonomyPackage, fetchTaxonomy, updateTaxonomyPackage } from "../api/system";

const EMPTY_DEF = {
  category: "",
  subcategory: "",
  budget_signal: null,
  archetype_signals: [],
  maturity_modifier: 0,
  intent_weight: 0,
  scaling_signal: false,
  pain_category: null,
  runtime_only: false,
  note: "",
};

function PackageModal({ pkg, categories, onClose, onSaved }) {
  const isNew = !pkg;
  const [name, setName] = useState(pkg?.package || "");
  const [def, setDef] = useState(
    pkg ? { ...EMPTY_DEF, ...pkg } : { ...EMPTY_DEF }
  );
  const [isSaving, setIsSaving] = useState(false);
  const [error, setError] = useState(null);

  const set = (key, val) => setDef((prev) => ({ ...prev, [key]: val }));

  const handleSave = async () => {
    if (!name.trim()) return setError("Nombre del package requerido");
    if (!def.category) return setError("Categoría requerida");
    setIsSaving(true);
    setError(null);
    try {
      const payload = {
        ...def,
        archetype_signals:
          typeof def.archetype_signals === "string"
            ? def.archetype_signals.split(",").map((s) => s.trim()).filter(Boolean)
            : def.archetype_signals,
        maturity_modifier: Number(def.maturity_modifier),
        intent_weight: Number(def.intent_weight),
        scaling_signal: Boolean(def.scaling_signal),
        runtime_only: Boolean(def.runtime_only),
        note: def.note || "",
      };
      if (isNew) {
        await createTaxonomyPackage(name.trim(), payload);
      } else {
        await updateTaxonomyPackage(name.trim(), payload);
      }
      onSaved();
      onClose();
    } catch (err) {
      setError(err.message || "Error guardando package");
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <p className="panel__eyebrow">{isNew ? "Nuevo package" : `Editar: ${pkg.package}`}</p>
        {error && <p className="topbar__error" style={{ margin: "0.4rem 0" }}>{error}</p>}

        {isNew && (
          <div className="config-field">
            <label className="config-field__label">Nombre del package</label>
            <input
              className="entities-search config-field__input"
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="ej: openai"
            />
          </div>
        )}

        <div className="config-field">
          <label className="config-field__label">Categoría</label>
          <select
            className="entities-search config-field__input"
            value={def.category}
            onChange={(e) => set("category", e.target.value)}
          >
            <option value="">— seleccionar —</option>
            {categories.map((c) => <option key={c} value={c}>{c}</option>)}
          </select>
        </div>

        <div className="config-field">
          <label className="config-field__label">Subcategoría</label>
          <input
            className="entities-search config-field__input"
            value={def.subcategory || ""}
            onChange={(e) => set("subcategory", e.target.value || null)}
          />
        </div>

        <div className="config-field">
          <label className="config-field__label">Archetype signals (CSV)</label>
          <input
            className="entities-search config-field__input"
            value={Array.isArray(def.archetype_signals) ? def.archetype_signals.join(", ") : def.archetype_signals || ""}
            onChange={(e) => set("archetype_signals", e.target.value)}
            placeholder="solo_agent_builder, mcp_platform_builder"
          />
        </div>

        <div className="taxonomy-modal__row">
          <div className="config-field" style={{ flex: 1 }}>
            <label className="config-field__label">Maturity modifier</label>
            <input
              className="entities-search config-field__input"
              type="number"
              value={def.maturity_modifier}
              onChange={(e) => set("maturity_modifier", Number(e.target.value))}
            />
          </div>
          <div className="config-field" style={{ flex: 1 }}>
            <label className="config-field__label">Intent weight</label>
            <input
              className="entities-search config-field__input"
              type="number"
              value={def.intent_weight}
              onChange={(e) => set("intent_weight", Number(e.target.value))}
            />
          </div>
        </div>

        <div className="taxonomy-modal__row">
          <div className="config-field" style={{ flex: 1 }}>
            <label className="config-field__label">Budget signal</label>
            <input
              className="entities-search config-field__input"
              value={def.budget_signal || ""}
              onChange={(e) => set("budget_signal", e.target.value || null)}
            />
          </div>
          <div className="config-field" style={{ flex: 1 }}>
            <label className="config-field__label">Pain category</label>
            <input
              className="entities-search config-field__input"
              value={def.pain_category || ""}
              onChange={(e) => set("pain_category", e.target.value || null)}
            />
          </div>
        </div>

        <div className="taxonomy-modal__row">
          <label className="config-field__label" style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input
              type="checkbox"
              checked={Boolean(def.scaling_signal)}
              onChange={(e) => set("scaling_signal", e.target.checked)}
            />
            Scaling signal
          </label>
          <label className="config-field__label" style={{ display: "flex", gap: "0.5rem", alignItems: "center" }}>
            <input
              type="checkbox"
              checked={Boolean(def.runtime_only)}
              onChange={(e) => set("runtime_only", e.target.checked)}
            />
            Runtime only
          </label>
        </div>

        <div className="config-field">
          <label className="config-field__label">Nota</label>
          <input
            className="entities-search config-field__input"
            value={def.note || ""}
            onChange={(e) => set("note", e.target.value)}
          />
        </div>

        <div className="modal-actions">
          <button className="btn-secondary" onClick={onClose}>Cancelar</button>
          <button className="btn-primary" onClick={handleSave} disabled={isSaving}>
            {isSaving ? "Guardando…" : "Guardar"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function SystemTaxonomy() {
  const [items, setItems] = useState([]);
  const [categories, setCategories] = useState([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [isLoading, setIsLoading] = useState(true);
  const [editing, setEditing] = useState(null); // null | false (new) | pkg object
  const limit = 50;
  const searchTimeout = useRef(null);

  const load = useCallback(async (q = search, off = offset) => {
    setIsLoading(true);
    try {
      const data = await fetchTaxonomy({ search: q, offset: off, limit });
      setItems(data.items || []);
      setTotal(data.total || 0);
      setCategories(data.categories || []);
    } finally {
      setIsLoading(false);
    }
  }, [search, offset]);

  useEffect(() => {
    load();
  }, []);

  const handleSearch = (val) => {
    setSearch(val);
    setOffset(0);
    clearTimeout(searchTimeout.current);
    searchTimeout.current = setTimeout(() => load(val, 0), 300);
  };

  const handleSaved = () => load(search, offset);

  return (
    <PageFrame
      eyebrow="Sistema"
      title="Taxonomía"
      description={`${total} packages en taxonomy/dependencies.json`}
    >
      <div className="entities-toolbar">
        <input
          type="search"
          className="entities-search"
          placeholder="Buscar package o categoría…"
          value={search}
          onChange={(e) => handleSearch(e.target.value)}
        />
        <button className="btn-primary" onClick={() => setEditing(false)}>
          + Agregar
        </button>
      </div>

      {isLoading ? (
        <LoadingSpinner label="Cargando taxonomía…" />
      ) : items.length === 0 ? (
        <EmptyState title="Sin resultados" description="No hay packages que coincidan con la búsqueda." />
      ) : (
        <>
          <div className="taxonomy-table">
            <div className="taxonomy-table__head">
              <span>Package</span>
              <span>Categoría</span>
              <span>Intent</span>
              <span>Maturity</span>
              <span>Signals</span>
              <span></span>
            </div>
            {items.map((item) => (
              <div key={item.package} className="taxonomy-table__row">
                <span className="taxonomy-table__pkg">{item.package}</span>
                <Badge tone="blue">{item.category}</Badge>
                <span>{item.intent_weight ?? 0}</span>
                <span>{item.maturity_modifier ?? 0}</span>
                <span className="taxonomy-table__signals">
                  {item.scaling_signal && <Badge tone="amber">scaling</Badge>}
                  {item.budget_signal && <Badge tone="green">budget</Badge>}
                  {(item.archetype_signals || []).slice(0, 2).map((s) => (
                    <Badge key={s} tone="indigo">{s.replace(/_/g, " ")}</Badge>
                  ))}
                </span>
                <button className="btn-secondary taxonomy-table__edit" onClick={() => setEditing(item)}>
                  Editar
                </button>
              </div>
            ))}
          </div>

          <div className="entities-pagination">
            <button
              className="btn-secondary"
              disabled={offset === 0}
              onClick={() => {
                const next = Math.max(0, offset - limit);
                setOffset(next);
                load(search, next);
              }}
            >
              ← Anterior
            </button>
            <span className="panel__copy">
              {offset + 1}–{Math.min(offset + limit, total)} de {total}
            </span>
            <button
              className="btn-secondary"
              disabled={offset + limit >= total}
              onClick={() => {
                const next = offset + limit;
                setOffset(next);
                load(search, next);
              }}
            >
              Siguiente →
            </button>
          </div>
        </>
      )}

      {editing !== null && (
        <PackageModal
          pkg={editing || null}
          categories={categories}
          onClose={() => setEditing(null)}
          onSaved={handleSaved}
        />
      )}
    </PageFrame>
  );
}
