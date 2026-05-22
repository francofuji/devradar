import { useCallback, useEffect, useState } from "react";
import LoadingSpinner from "../components/ui/LoadingSpinner";
import PageFrame from "./PageFrame";
import { fetchConfig, updateConfig } from "../api/system";

function inferType(value) {
  if (typeof value === "boolean") return "boolean";
  if (typeof value === "number") return "number";
  if (Array.isArray(value)) return "array";
  return "string";
}

function ScalarField({ fieldKey, value, onChange }) {
  const type = inferType(value);

  if (type === "boolean") {
    return (
      <div className="config-field">
        <label className="config-field__label">{fieldKey}</label>
        <select
          className="entities-search config-field__input"
          value={String(value)}
          onChange={(e) => onChange(e.target.value === "true")}
        >
          <option value="true">true</option>
          <option value="false">false</option>
        </select>
      </div>
    );
  }

  if (type === "array") {
    return (
      <div className="config-field">
        <label className="config-field__label">{fieldKey}</label>
        <input
          className="entities-search config-field__input"
          value={value.join(", ")}
          onChange={(e) =>
            onChange(
              e.target.value
                .split(",")
                .map((s) => s.trim())
                .filter(Boolean)
            )
          }
        />
        <span className="config-field__hint">Separado por comas</span>
      </div>
    );
  }

  return (
    <div className="config-field">
      <label className="config-field__label">{fieldKey}</label>
      <input
        className="entities-search config-field__input"
        type={type === "number" ? "number" : "text"}
        value={value ?? ""}
        onChange={(e) =>
          onChange(type === "number" ? Number(e.target.value) : e.target.value)
        }
      />
    </div>
  );
}

function SectionPanel({ sectionKey, data, onSectionChange }) {
  const [open, setOpen] = useState(false);

  const handleFieldChange = (key, val) => {
    onSectionChange(sectionKey, { ...data, [key]: val });
  };

  const scalars = Object.entries(data).filter(([, v]) => typeof v !== "object" || Array.isArray(v));

  return (
    <article className="panel config-section">
      <button
        className="digest-section__toggle"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
      >
        <span className="digest-section__icon">⚙</span>
        <span className="digest-section__title">[{sectionKey}]</span>
        <span className="digest-section__chevron">{open ? "▲" : "▼"}</span>
      </button>
      {open && (
        <div className="config-section__body">
          {scalars.map(([key, val]) => (
            <ScalarField
              key={key}
              fieldKey={key}
              value={val}
              onChange={(newVal) => handleFieldChange(key, newVal)}
            />
          ))}
          {scalars.length === 0 && (
            <p className="panel__copy">No hay valores editables en esta sección.</p>
          )}
        </div>
      )}
    </article>
  );
}

export default function SystemConfig() {
  const [config, setConfig] = useState(null);
  const [original, setOriginal] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState(null);

  const load = useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await fetchConfig();
      setConfig(data);
      setOriginal(JSON.stringify(data));
    } catch (err) {
      setError(err.message || "Error cargando configuración");
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  const handleSectionChange = (section, newData) => {
    setConfig((prev) => ({ ...prev, [section]: newData }));
    setSaved(false);
  };

  const handleSave = async () => {
    setIsSaving(true);
    setError(null);
    try {
      await updateConfig(config);
      setOriginal(JSON.stringify(config));
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (err) {
      setError(err.message || "Error guardando configuración");
    } finally {
      setIsSaving(false);
    }
  };

  const handleReset = () => {
    if (original) {
      setConfig(JSON.parse(original));
      setSaved(false);
    }
  };

  const isDirty = config && JSON.stringify(config) !== original;

  if (isLoading) {
    return (
      <PageFrame eyebrow="Sistema" title="Configuración">
        <LoadingSpinner label="Cargando config.toml…" />
      </PageFrame>
    );
  }

  const sections = config
    ? Object.entries(config).filter(([, v]) => typeof v === "object" && !Array.isArray(v))
    : [];

  return (
    <PageFrame
      eyebrow="Sistema"
      title="Configuración"
      description="Edita config.toml desde la interfaz. Los cambios se persisten en el volumen montado."
    >
      {error && <p className="topbar__error">{error}</p>}

      <div className="config-sections">
        {sections.map(([key, data]) => (
          <SectionPanel
            key={key}
            sectionKey={key}
            data={data}
            onSectionChange={handleSectionChange}
          />
        ))}
      </div>

      <div className="config-actions">
        <button
          className="btn-secondary"
          onClick={handleReset}
          disabled={!isDirty || isSaving}
        >
          Descartar cambios
        </button>
        <button
          className="btn-primary"
          onClick={handleSave}
          disabled={!isDirty || isSaving}
        >
          {isSaving ? "Guardando…" : saved ? "✓ Guardado" : "Guardar config.toml"}
        </button>
      </div>
    </PageFrame>
  );
}
