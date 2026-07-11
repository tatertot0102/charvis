import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api } from "../api";
import type { EntityWorkspace } from "../types";
import { Badge, ErrorState, fmtWhen, Loading } from "../components/ui";

export function EntityPage({ type }: { type: "event" | "person" | "project" }) {
  const { id = "" } = useParams();
  const [ws, setWs] = useState<EntityWorkspace | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    setWs(null); setError(null);
    api.getEntity(type, id)
      .then((w) => alive && setWs(w))
      .catch((e) => alive && setError((e as Error).message));
    return () => { alive = false; };
  }, [type, id]);

  if (error) return <ErrorState message={error} />;
  if (!ws) return <Loading label={`Gathering everything about ${id}…`} />;

  const block = (title: string, items: string[]) =>
    items.length > 0 && (
      <section className="card">
        <header><h2>{title}</h2><span className="count">{items.length}</span></header>
        {items.map((t, i) => <div key={i} className="row"><span className="title">{t}</span></div>)}
      </section>
    );

  return (
    <div className="page">
      <Link to="/" className="back">← Command Center</Link>
      <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <h1>{ws.title}</h1>
        {ws.badges.map((b) => <Badge key={b} kind={b} />)}
      </div>
      <p className="faint">{ws.summary}</p>

      {ws.conflicts.length > 0 && (
        <section className="card" style={{ borderColor: "var(--conflicted)" }}>
          <header><h2>⚠ Conflicts</h2></header>
          {ws.conflicts.map((c, i) => <div key={i} className="row"><span className="title">{c}</span></div>)}
        </section>
      )}

      {ws.events.length > 0 && (
        <section className="card">
          <header><h2>Events</h2><span className="count">{ws.events.length}</span></header>
          {ws.events.map((e, i) => (
            <div key={i} className="row">
              <span className="title">{e.title}</span><Badge kind="verified" />
              <span className="when">{fmtWhen(e.when)}</span>
            </div>
          ))}
        </section>
      )}

      {ws.emails.length > 0 && (
        <section className="card">
          <header><h2>Related email</h2><span className="count">{ws.emails.length}</span></header>
          {ws.emails.map((e, i) => (
            <div key={i} className="row"><span className="title">{e.text}</span><Badge kind="likely" /></div>
          ))}
        </section>
      )}

      {block("People", ws.people)}
      {block("Commitments", ws.commitments)}
      {block("Memory", ws.memory)}
      {block("Waiting on", ws.waiting)}
    </div>
  );
}
