import { NavLink } from "react-router-dom";

const groups = [
  {
    title: "Inteligencia",
    links: [
      { to: "/dashboard", label: "Dashboard" },
      { to: "/entities", label: "Entidades" },
      { to: "/outreach", label: "Cola de Outreach" },
    ],
  },
  {
    title: "Outputs",
    links: [
      { to: "/digest", label: "Digest Diario" },
      { to: "/alerts", label: "Alertas" },
      { to: "/trends", label: "Tendencias" },
    ],
  },
  {
    title: "Sistema",
    links: [
      { to: "/system/health", label: "Health" },
      { to: "/system/logs", label: "Logs" },
      { to: "/system/config", label: "Configuración" },
      { to: "/system/taxonomy", label: "Taxonomía" },
      { to: "/training", label: "Fine-tuning" },
    ],
  },
];

export default function Sidebar() {
  return (
    <aside className="sidebar">
      <div className="sidebar__brand">
        <p>Dev Intelligence</p>
      </div>

      {groups.map((group) => (
        <section className="sidebar__group" key={group.title}>
          <p className="sidebar__title">{group.title}</p>
          <nav className="sidebar__nav">
            {group.links.map((link) => (
              <NavLink
                key={link.to}
                to={link.to}
                className={({ isActive }) =>
                  isActive ? "sidebar__link sidebar__link--active" : "sidebar__link"
                }
              >
                {link.label}
              </NavLink>
            ))}
          </nav>
        </section>
      ))}
    </aside>
  );
}
