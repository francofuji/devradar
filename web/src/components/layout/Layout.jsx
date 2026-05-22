import { Outlet } from "react-router-dom";
import Sidebar from "./Sidebar";
import TopBar from "./TopBar";
import useSSE from "../../hooks/useSSE";

export default function Layout() {
  const sse = useSSE();

  return (
    <div className="app-shell">
      <Sidebar />
      <div className="app-shell__main">
        <TopBar sse={sse} />
        <main className="content">
          <Outlet context={{ sse }} />
        </main>
      </div>
    </div>
  );
}
