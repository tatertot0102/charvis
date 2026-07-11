import { useState } from "react";
import { Link } from "react-router-dom";
import type {
  ApprovalSummary,
  DashboardSection,
  HeroState,
  NotificationItem,
  PriorityState,
  TodayState,
  WorkingMemoryItem,
} from "../types";
import { Badge, countdown, EmptyState, fmtWhen } from "./ui";

export function Section({
  meta, title, count, children,
}: {
  meta: DashboardSection;
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  const [collapsed, setCollapsed] = useState(meta.collapsed);
  return (
    <section className={`card sec-${meta.size}`} aria-label={title}>
      <header>
        <h2>{title}</h2>
        {count != null && <span className="count">{count}</span>}
        <button className="collapse-btn" onClick={() => setCollapsed((c) => !c)} aria-expanded={!collapsed}>
          {collapsed ? "▸" : "▾"}
        </button>
      </header>
      {!collapsed && children}
    </section>
  );
}

export function Hero({ meta, hero }: { meta: DashboardSection; hero: HeroState }) {
  if (!hero.present) {
    return (
      <section className={`card hero sec-${meta.size}`} aria-label="Hero">
        <header><h2>Now</h2></header>
        <EmptyState>Nothing urgent right now. You're clear.</EmptyState>
      </section>
    );
  }
  return (
    <section className={`card hero sec-${meta.size}`} aria-label="Hero">
      <header><h2>{hero.kind === "event" ? "Happening next" : "Most important"}</h2>
        <span style={{ marginLeft: "auto", display: "flex", gap: 4 }}>
          {hero.badges.map((b) => <Badge key={b} kind={b} />)}
        </span>
      </header>
      <h1>{hero.title}</h1>
      {hero.countdown_seconds != null && <div className="count-big">{countdown(hero.countdown_seconds)}</div>}
      <div className="meta">
        {hero.when && <span>{fmtWhen(hero.when)}</span>}
        {hero.location && <span>📍 {hero.location}</span>}
        {hero.context && <span className="muted">{hero.context}</span>}
      </div>
      {hero.people.length > 0 && <div className="faint">With: {hero.people.join(", ")}</div>}
      {hero.related_emails.length > 0 && (
        <div>
          <div className="subhead">Related email</div>
          {hero.related_emails.map((e, i) => <div key={i} className="faint">• {e.text}</div>)}
        </div>
      )}
      {hero.prep_checklist.length > 0 && (
        <ul className="checklist">{hero.prep_checklist.map((c, i) => <li key={i}>{c}</li>)}</ul>
      )}
    </section>
  );
}

export function Priority({ meta, priority }: { meta: DashboardSection; priority: PriorityState }) {
  const { top, secondary } = priority;
  return (
    <Section meta={meta} title="Priority">
      {!top ? (
        <EmptyState>No standout priority — a balanced day.</EmptyState>
      ) : (
        <>
          <div className="top-rec">
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              {top.urgent && <span className="pill-urgent">URGENT</span>}
              <strong>{top.title}</strong>
              <Badge kind={top.badge} />
            </div>
            <div className="why">{top.reason}{top.confidence ? ` · ${Math.round(top.confidence * 100)}% confident` : ""}</div>
          </div>
          {secondary.length > 0 && <div className="subhead">Then</div>}
          {secondary.map((p, i) => (
            <div key={i} className="row">
              <span className="title">{p.urgent && <span className="pill-urgent">! </span>}{p.title}</span>
              <Badge kind={p.badge} />
            </div>
          ))}
        </>
      )}
    </Section>
  );
}

export function Today({ meta, today }: { meta: DashboardSection; today: TodayState }) {
  const empty =
    today.events.length + today.commitments.length + today.email_events.length === 0;
  return (
    <Section meta={meta} title="Today / Upcoming"
      count={today.events.length + today.commitments.length + today.email_events.length}>
      {empty && today.conflicts.length === 0 ? (
        <EmptyState>Nothing scheduled. 🎉</EmptyState>
      ) : (
        <>
          {today.events.length > 0 && <div className="subhead">Google Calendar (verified)</div>}
          {today.events.map((e, i) => (
            <div key={`e${i}`} className="row">
              <span className="title">{e.title}</span>
              <Badge kind="verified" />
              <span className="when">{fmtWhen(e.when)}</span>
            </div>
          ))}
          {today.commitments.length > 0 && <div className="subhead">Remembered commitments</div>}
          {today.commitments.map((c, i) => (
            <div key={`c${i}`} className="row"><span className="title">{c.title}</span><Badge kind="remembered" /></div>
          ))}
          {today.email_events.length > 0 && <div className="subhead">Possible events from email</div>}
          {today.email_events.map((m, i) => (
            <div key={`m${i}`} className="row"><span className="title">{m.title}</span><Badge kind="likely" /></div>
          ))}
          {today.conflicts.map((c, i) => (
            <div key={`x${i}`} className="row"><span className="title pill-warn">⚠ {c}</span><Badge kind="conflicted" /></div>
          ))}
        </>
      )}
    </Section>
  );
}

export function WorkingMemory({ meta, items }: { meta: DashboardSection; items: WorkingMemoryItem[] }) {
  return (
    <Section meta={meta} title="Working Memory">
      {items.length === 0 ? (
        <EmptyState>Nothing active being tracked.</EmptyState>
      ) : (
        items.map((it, i) => (
          <div key={i} className="row">
            <span className="faint" style={{ minWidth: 110 }}>{it.label}</span>
            <span className="title">{it.value}</span>
            {it.badge && <Badge kind={it.badge} />}
          </div>
        ))
      )}
      <Link className="faint" to="/memory" style={{ marginTop: 4 }}>Long-term memory →</Link>
    </Section>
  );
}

export function Notifications({ meta, items }: { meta: DashboardSection; items: NotificationItem[] }) {
  return (
    <Section meta={meta} title="Needs attention" count={items.length}>
      {items.length === 0 ? (
        <EmptyState>All clear — nothing needs you.</EmptyState>
      ) : (
        items.map((n, i) => {
          const body = <><span className="dot" /><span>{n.text}</span></>;
          return n.href ? (
            <Link key={i} to={n.href} className={`note ${n.severity}`}>{body}</Link>
          ) : (
            <div key={i} className={`note ${n.severity}`}>{body}</div>
          );
        })
      )}
    </Section>
  );
}

export function Approvals({
  meta, items, onDecision,
}: {
  meta: DashboardSection;
  items: ApprovalSummary[];
  onDecision: (id: number, action: "confirm" | "cancel") => Promise<void>;
}) {
  const [busy, setBusy] = useState<number | null>(null);
  const decide = async (id: number, action: "confirm" | "cancel") => {
    setBusy(id);
    try { await onDecision(id, action); } finally { setBusy(null); }
  };
  return (
    <Section meta={meta} title="Pending approvals" count={items.length}>
      {items.length === 0 ? (
        <EmptyState>No actions waiting on you.</EmptyState>
      ) : (
        items.map((a) => (
          <div key={a.id} className="approval">
            <div><strong>{a.summary}</strong></div>
            <div className="faint">
              {a.action_type} · {a.item_count} item(s) · {Math.round(a.confidence * 100)}% ·
              needs <span className="phrase">{a.required_phrase}</span>
              {a.expires_at && <> · expires {fmtWhen(a.expires_at)}</>}
            </div>
            {a.evidence.length > 0 && (
              <div className="faint">{a.evidence.map((e, i) => <div key={i}>• {e.text}</div>)}</div>
            )}
            <div className="actions">
              <button className="btn approve" disabled={busy === a.id} onClick={() => decide(a.id, "confirm")}>Approve</button>
              <button className="btn reject" disabled={busy === a.id} onClick={() => decide(a.id, "cancel")}>Reject</button>
            </div>
          </div>
        ))
      )}
    </Section>
  );
}
