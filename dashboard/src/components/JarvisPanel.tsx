import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api";
import type { LayoutCommand, SectionId } from "../types";

interface Msg { role: "user" | "bot"; text: string; }

const SECTIONS: Record<string, SectionId> = {
  hero: "hero", priority: "priority", today: "today", upcoming: "today",
  "working memory": "working_memory", memory: "working_memory",
  notifications: "notifications", notification: "notifications", approvals: "approvals",
};

// Parse a small, explicit command set into a validated LayoutCommand. Everything else is a chat
// question. The backend re-validates every command; anything off-schema is ignored there too.
function parseCommand(text: string): LayoutCommand | { nav: string } | null {
  const t = text.trim().toLowerCase();
  let m: RegExpMatchArray | null;
  if ((m = t.match(/^(?:clear|reset) focus$/))) return { action: "set_focus", focus: null };
  if ((m = t.match(/^focus(?: on)?\s+(.+)$/))) return { action: "set_focus", focus: m[1] };
  if ((m = t.match(/^(hide|show|collapse|expand)\s+(.+)$/))) {
    const sec = SECTIONS[m[2].trim()];
    if (sec) return { action: m[1], section: sec };
  }
  if ((m = t.match(/^(?:open|go to|show me)\s+(memory|people|projects|commitments|sources|approvals)$/)))
    return { nav: `/${m[1]}` };
  return null;
}

export function JarvisPanel({ onLayoutChange }: { onLayoutChange: () => void }) {
  const [open, setOpen] = useState(false);
  const [log, setLog] = useState<Msg[]>([
    { role: "bot", text: "Ask me anything, or say “focus college”, “hide notifications”, “open sources”." },
  ]);
  const [input, setInput] = useState("");
  const [busy, setBusy] = useState(false);
  const navigate = useNavigate();

  const send = async (raw: string) => {
    const text = raw.trim();
    if (!text || busy) return;
    setLog((l) => [...l, { role: "user", text }]);
    setInput("");
    setBusy(true);
    try {
      const cmd = parseCommand(text);
      if (cmd && "nav" in cmd) {
        navigate(cmd.nav);
        setLog((l) => [...l, { role: "bot", text: `Opening ${cmd.nav}.` }]);
      } else if (cmd) {
        try {
          await api.postLayout(cmd);
          onLayoutChange();
          setLog((l) => [...l, { role: "bot", text: "Done — updated the dashboard." }]);
        } catch {
          setLog((l) => [...l, { role: "bot", text: "I can't apply that change (it's not allowed)." }]);
        }
      } else {
        const { reply } = await api.chat(text);
        setLog((l) => [...l, { role: "bot", text: reply }]);
      }
    } catch (e) {
      setLog((l) => [...l, { role: "bot", text: `Something went wrong: ${(e as Error).message}` }]);
    } finally {
      setBusy(false);
    }
  };

  if (!open) {
    return <button className="jarvis-fab" aria-label="Open Jarvis" onClick={() => setOpen(true)}>J</button>;
  }

  return (
    <div className="jarvis" role="dialog" aria-label="Jarvis assistant">
      <header><strong>Jarvis</strong><button className="x" aria-label="Close" onClick={() => setOpen(false)}>×</button></header>
      <div className="log">
        {log.map((m, i) => <div key={i} className={`msg ${m.role}`}>{m.text}</div>)}
        {busy && <div className="msg bot faint">…</div>}
      </div>
      <div className="chips">
        {["focus college", "hide notifications", "open sources", "what's my week?"].map((c) => (
          <button key={c} className="chip" onClick={() => send(c)}>{c}</button>
        ))}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); send(input); }}>
        <input value={input} onChange={(e) => setInput(e.target.value)} placeholder="Ask or command…" aria-label="Message Jarvis" />
        <button className="btn" disabled={busy}>Send</button>
      </form>
    </div>
  );
}
