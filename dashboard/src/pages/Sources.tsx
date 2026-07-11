import type { DashboardState } from "../types";
import { Loading } from "../components/ui";

export function SourcesPage({ state }: { state: DashboardState | null }) {
  if (!state) return <Loading />;
  const real = state.sources.filter((s) => !s.placeholder);
  const placeholders = state.sources.filter((s) => s.placeholder);

  return (
    <div className="page">
      <h1>Sources</h1>
      <p className="faint">Live connection status. Placeholder sources are not built yet and are shown as such — never faked.</p>

      <div className="src-table">
        {real.map((s) => (
          <div key={s.name} className="src-row">
            <strong>{s.label}</strong>
            <span className="faint">{s.detail}</span>
            <span className={`st ${s.state}`}>{s.state.replace("_", " ")}</span>
          </div>
        ))}
      </div>

      <h2 style={{ marginTop: 8, fontSize: "0.8rem", letterSpacing: "0.08em", textTransform: "uppercase", color: "var(--text-faint)" }}>
        Coming later (placeholders)
      </h2>
      <div className="src-table">
        {placeholders.map((s) => (
          <div key={s.name} className="src-row" style={{ opacity: 0.7 }}>
            <strong>{s.label}</strong>
            <span className="faint">Not connected — planned</span>
            <span className="st coming_later">coming later</span>
          </div>
        ))}
      </div>
    </div>
  );
}
