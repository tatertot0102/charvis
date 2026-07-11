import type { ReactNode } from "react";
import type { TruthBadge } from "../types";

export function Badge({ kind }: { kind: TruthBadge }) {
  return <span className={`badge ${kind}`} title={`Reality: ${kind}`}>{kind}</span>;
}

export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div className="state" role="status" aria-live="polite">
      <div className="spinner" aria-hidden />
      <div style={{ marginTop: 8 }}>{label}</div>
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <div className="state">{children}</div>;
}

export function ErrorState({ message }: { message: string }) {
  return <div className="state err" role="alert">⚠ {message}</div>;
}

export function countdown(seconds?: number | null): string {
  if (seconds == null) return "";
  const past = seconds < 0;
  let s = Math.abs(seconds);
  const d = Math.floor(s / 86400); s -= d * 86400;
  const h = Math.floor(s / 3600); s -= h * 3600;
  const m = Math.floor(s / 60);
  const parts = d ? [`${d}d`, `${h}h`] : h ? [`${h}h`, `${m}m`] : [`${m}m`];
  return (past ? "-" : "") + parts.join(" ");
}

export function fmtWhen(iso?: string | null): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return d.toLocaleString(undefined, {
    weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit",
  });
}
