import { Link } from "react-router-dom";

export default function NotFound() {
  return (
    <section className="page page--404">
      <p className="page__eyebrow">Missing route</p>
      <h2>404</h2>
      <p>La ruta que buscabas no existe dentro de la consola operativa.</p>
      <Link className="inline-link" to="/dashboard">
        Volver al dashboard
      </Link>
    </section>
  );
}
