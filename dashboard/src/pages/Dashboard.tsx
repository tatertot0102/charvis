import type { DashboardHook } from "../hooks/useDashboard";
import type { DashboardSection, SectionId } from "../types";
import {
  Approvals, Hero, Notifications, Priority, Today, WorkingMemory,
} from "../components/sections";
import { ErrorState, Loading } from "../components/ui";

export function Dashboard({ dash, approvalsOnly }: { dash: DashboardHook; approvalsOnly?: boolean }) {
  const { state, loading, error, decide } = dash;

  if (loading && !state) return <Loading label="Assembling your world…" />;
  if (error && !state) return <ErrorState message={`Couldn't reach the brain: ${error}`} />;
  if (!state) return <ErrorState message="No dashboard state." />;

  const section = (id: SectionId): DashboardSection =>
    state.layout.sections.find((s) => s.id === id) ??
    { id, visible: true, collapsed: false, size: "md", order: 0 };

  if (approvalsOnly) {
    return (
      <div className="grid">
        <Approvals meta={{ ...section("approvals"), size: "lg" }} items={state.approvals} onDecision={decide} />
      </div>
    );
  }

  const render = (id: SectionId) => {
    const meta = section(id);
    if (!meta.visible) return null;
    switch (id) {
      case "hero": return <Hero key={id} meta={meta} hero={state.hero} />;
      case "priority": return <Priority key={id} meta={meta} priority={state.priority} />;
      case "today": return <Today key={id} meta={meta} today={state.today} />;
      case "working_memory": return <WorkingMemory key={id} meta={meta} items={state.working_memory} />;
      case "notifications": return <Notifications key={id} meta={meta} items={state.notifications} />;
      case "approvals": return <Approvals key={id} meta={meta} items={state.approvals} onDecision={decide} />;
      default: return null;
    }
  };

  const ordered = [...state.layout.sections].sort((a, b) => a.order - b.order);
  return <div className="grid">{ordered.map((s) => render(s.id))}</div>;
}
