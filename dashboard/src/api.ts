// Single API client. All factual content comes from the backend; the frontend never fabricates.
import type {
  ApprovalSummary,
  DashboardState,
  EntityWorkspace,
  LayoutCommand,
  LayoutState,
} from "./types";

declare global {
  interface Window {
    __JARVIS_TOKEN__?: string;
  }
}

// Production: the brain injects window.__JARVIS_TOKEN__. Dev: fall back to a Vite env var.
const TOKEN =
  (typeof window !== "undefined" && window.__JARVIS_TOKEN__) ||
  (import.meta.env?.VITE_JARVIS_TOKEN as string | undefined) ||
  "";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

async function req<T>(path: string, init: RequestInit = {}): Promise<T> {
  const resp = await fetch(path, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${TOKEN}`,
      ...(init.headers || {}),
    },
  });
  if (!resp.ok) {
    let detail = resp.statusText;
    try {
      detail = (await resp.json())?.detail ?? detail;
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, detail);
  }
  return (await resp.json()) as T;
}

export const api = {
  getState: (focus?: string) =>
    req<DashboardState>(`/dashboard/state${focus ? `?focus=${encodeURIComponent(focus)}` : ""}`),
  getLayout: () => req<LayoutState>("/dashboard/layout"),
  postLayout: (cmd: LayoutCommand) =>
    req<LayoutState>("/dashboard/layout", { method: "POST", body: JSON.stringify(cmd) }),
  getEntity: (type: string, id: string) =>
    req<EntityWorkspace>(`/dashboard/entity/${type}/${encodeURIComponent(id)}`),
  getApprovals: () => req<{ count: number; actions: ApprovalSummary[] }>("/approvals"),
  confirmApproval: (id: number) =>
    req<{ id: number; status: string; message: string }>(`/approvals/${id}/confirm`, { method: "POST" }),
  cancelApproval: (id: number) =>
    req<{ id: number; status: string; message: string }>(`/approvals/${id}/cancel`, { method: "POST" }),
  chat: (message: string) =>
    req<{ reply: string; conversation_id: number }>("/chat", {
      method: "POST",
      body: JSON.stringify({ message, session_id: "dashboard" }),
    }),
  memory: (kind: string) => req<Record<string, unknown>>(`/memory/${kind}`),
};
