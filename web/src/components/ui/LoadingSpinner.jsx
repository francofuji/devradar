export default function LoadingSpinner({ label = "Cargando…" }) {
  return (
    <div className="loading">
      <span className="loading__spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  );
}
