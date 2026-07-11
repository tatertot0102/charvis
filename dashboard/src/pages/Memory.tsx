import { useEffect, useState } from "react";
import { api } from "../api";
import { Badge, ErrorState, Loading } from "../components/ui";

interface Conclusion { kind: string; subject: string; statement: string; confidence: number; }
interface Pattern { pattern_type: string; subject: string; description: string; confidence: number; }
interface Commitment { direction: string; description: string; counterparty?: string | null; confidence: number; }

type Kind = "memory" | "people" | "projects" | "commitments";

const TITLES: Record<Kind, string> = {
  memory: "Long-term Memory", people: "People", projects: "Projects", commitments: "Commitments",
};

export function MemoryPage({ focusKind = "memory" as Kind }: { focusKind?: Kind }) {
  const [data, setData] = useState<{ conclusions: Conclusion[]; patterns: Pattern[]; commitments: Commitment[] } | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        if (focusKind === "commitments") {
          const c = await api.memory("commitments") as { commitments?: Commitment[] };
          if (alive) setData({ conclusions: [], patterns: [], commitments: c.commitments ?? [] });
        } else if (focusKind === "people" || focusKind === "projects") {
          const c = await api.memory(focusKind) as { conclusions?: Conclusion[] };
          if (alive) setData({ conclusions: c.conclusions ?? [], patterns: [], commitments: [] });
        } else {
          const [c, p] = await Promise.all([
            api.memory("conclusions") as Promise<{ conclusions?: Conclusion[] }>,
            api.memory("patterns") as Promise<{ patterns?: Pattern[] }>,
          ]);
          if (alive) setData({ conclusions: c.conclusions ?? [], patterns: p.patterns ?? [], commitments: [] });
        }
      } catch (e) {
        if (alive) setError((e as Error).message);
      }
    })();
    return () => { alive = false; };
  }, [focusKind]);

  if (error) return <ErrorState message={error} />;
  if (!data) return <Loading />;

  const empty = data.conclusions.length + data.patterns.length + data.commitments.length === 0;

  return (
    <div className="page">
      <h1>{TITLES[focusKind]}</h1>
      {empty && <div className="state">Nothing here yet — memory builds up as Jarvis learns.</div>}

      {data.conclusions.length > 0 && (
        <section className="card">
          <header><h2>Conclusions</h2><span className="count">{data.conclusions.length}</span></header>
          {data.conclusions.map((c, i) => (
            <div key={i} className="row">
              <span className="title"><strong>{c.subject}</strong> — {c.statement}</span>
              <Badge kind="remembered" />
              <span className="when">{Math.round(c.confidence * 100)}%</span>
            </div>
          ))}
        </section>
      )}

      {data.patterns.length > 0 && (
        <section className="card">
          <header><h2>Patterns</h2><span className="count">{data.patterns.length}</span></header>
          {data.patterns.map((p, i) => (
            <div key={i} className="row">
              <span className="title"><strong>{p.subject}</strong> — {p.description}</span>
              <Badge kind="inferred" />
              <span className="when">{Math.round(p.confidence * 100)}%</span>
            </div>
          ))}
        </section>
      )}

      {data.commitments.length > 0 && (
        <section className="card">
          <header><h2>Commitments</h2><span className="count">{data.commitments.length}</span></header>
          {data.commitments.map((c, i) => (
            <div key={i} className="row">
              <span className="title">{c.description}{c.counterparty ? ` · ${c.counterparty}` : ""}</span>
              <span className="faint">{c.direction.replace("_", " ")}</span>
              <Badge kind="remembered" />
            </div>
          ))}
        </section>
      )}
    </div>
  );
}
