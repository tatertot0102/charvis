import { NavLink, Route, Routes } from "react-router-dom";
import { JarvisPanel } from "./components/JarvisPanel";
import { useDashboard } from "./hooks/useDashboard";
import { Dashboard } from "./pages/Dashboard";
import { EntityPage } from "./pages/Entity";
import { MemoryPage } from "./pages/Memory";
import { SourcesPage } from "./pages/Sources";
import { TopStatus } from "./components/TopStatus";
import { Loading } from "./components/ui";

const NAV = [
  { to: "/", label: "Command Center", end: true },
  { to: "/memory", label: "Memory" },
  { to: "/people", label: "People" },
  { to: "/projects", label: "Projects" },
  { to: "/commitments", label: "Commitments" },
  { to: "/sources", label: "Sources" },
  { to: "/approvals", label: "Approvals" },
];

export function App() {
  const dash = useDashboard();

  return (
    <div className="shell">
      {dash.state ? (
        <TopStatus status={dash.state.top_status} mode={dash.state.mode} focus={dash.state.focus} />
      ) : (
        <header className="topbar"><span className="brand">Jarvis</span></header>
      )}
      <div className="workspace">
        <nav className="nav" aria-label="Primary">
          {NAV.map((n) => (
            <NavLink key={n.to} to={n.to} end={n.end}
              className={({ isActive }) => (isActive ? "active" : "")}>{n.label}</NavLink>
          ))}
        </nav>
        <main>
          <Routes>
            <Route path="/" element={<Dashboard dash={dash} />} />
            <Route path="/sources" element={<SourcesPage state={dash.state} />} />
            <Route path="/memory" element={<MemoryPage />} />
            <Route path="/people" element={<MemoryPage focusKind="people" />} />
            <Route path="/projects" element={<MemoryPage focusKind="projects" />} />
            <Route path="/commitments" element={<MemoryPage focusKind="commitments" />} />
            <Route path="/approvals" element={<Dashboard dash={dash} approvalsOnly />} />
            <Route path="/events/:id" element={<EntityPage type="event" />} />
            <Route path="/people/:id" element={<EntityPage type="person" />} />
            <Route path="/projects/:id" element={<EntityPage type="project" />} />
            <Route path="*" element={<Loading label="Not found — routing…" />} />
          </Routes>
        </main>
      </div>
      <JarvisPanel onLayoutChange={dash.refresh} />
    </div>
  );
}
