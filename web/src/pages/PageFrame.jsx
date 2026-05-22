import EmptyState from "../components/ui/EmptyState";

export default function PageFrame({ eyebrow, title, description, children }) {
  return (
    <section className="page">
      <header className="page__header">
        <p className="page__eyebrow">{eyebrow}</p>
        <h2>{title}</h2>
        <p>{description}</p>
      </header>

      {children}
    </section>
  );
}
