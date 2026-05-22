export default function EmptyState({ title, description }) {
  return (
    <section className="empty-state">
      <p className="empty-state__eyebrow">Sin resultados todavía</p>
      <h3>{title}</h3>
      <p>{description}</p>
    </section>
  );
}
