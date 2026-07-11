import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import type { DashboardMode, TopStatus as TopStatusT } from "../types";
import { countdown } from "./ui";

export function TopStatus({
  status, mode, focus,
}: {
  status: TopStatusT;
  mode: DashboardMode;
  focus?: string | null;
}) {
  const [now, setNow] = useState(() => new Date());
  const [cd, setCd] = useState(status.next_event_countdown_seconds ?? null);

  useEffect(() => {
    const t = setInterval(() => {
      setNow(new Date());
      setCd((c) => (c == null ? c : c - 1));
    }, 1000);
    return () => clearInterval(t);
  }, []);

  useEffect(() => setCd(status.next_event_countdown_seconds ?? null), [status.next_event_countdown_seconds]);

  return (
    <header className="topbar">
      <Link to="/" className="brand">Jarvis</Link>
      <span className="clock">{now.toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit", second: "2-digit" })}</span>
      {status.next_event_title && (
        <span className="next-ev">Next: {status.next_event_title} {cd != null && <strong>in {countdown(cd)}</strong>}</span>
      )}
      {focus && <span className="next-ev">Focus: <strong>{focus}</strong></span>}
      <span className="src-dots" title="Source health">
        {status.sources.filter((s) => !s.placeholder).map((s) => (
          <span key={s.name} className={`src-dot ${s.connected ? "ok" : s.state === "connected" ? "ok" : "bad"}`}
            title={`${s.label}: ${s.state}`} />
        ))}
      </span>
      <span className="mode-pill" title="Deterministic mode">{mode.replace("_", " ")}</span>
    </header>
  );
}
