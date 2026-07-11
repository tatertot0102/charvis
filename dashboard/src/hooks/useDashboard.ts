import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../api";
import type { DashboardState } from "../types";

export interface DashboardHook {
  state: DashboardState | null;
  loading: boolean;
  error: string | null;
  refresh: () => void;
  decide: (id: number, action: "confirm" | "cancel") => Promise<void>;
}

const POLL_MS = 30000;

export function useDashboard(): DashboardHook {
  const [state, setState] = useState<DashboardState | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const mounted = useRef(true);

  const load = useCallback(async () => {
    try {
      const s = await api.getState();
      if (mounted.current) { setState(s); setError(null); }
    } catch (e) {
      if (mounted.current) setError((e as Error).message);
    } finally {
      if (mounted.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    load();
    const t = setInterval(load, POLL_MS);
    return () => { mounted.current = false; clearInterval(t); };
  }, [load]);

  const decide = useCallback(async (id: number, action: "confirm" | "cancel") => {
    if (action === "confirm") await api.confirmApproval(id);
    else await api.cancelApproval(id);
    await load();
  }, [load]);

  return { state, loading, error, refresh: load, decide };
}
