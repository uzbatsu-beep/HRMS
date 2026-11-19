import { useEffect, useRef, useState } from "react";

export type CandidateRecord = {
  person_id: string;
  resource_id: string | null;
  employee_code: string;
  full_name: string;
  eligible: boolean;
  blockers: { source: string; code: string; message: string }[];
  verified_skills: string[];
  verified_credentials: string[];
};

type CandidatePage = {
  items: CandidateRecord[];
  next_cursor: string | null;
  has_more: boolean;
};

const SIZE = 20;

export function useCandidatePages(orderId: string, enabled: boolean, revision: string | number) {
  const [search, setSearch] = useState("");
  const [items, setItems] = useState<CandidateRecord[]>([]);
  const [cursor, setCursor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  const scope = [orderId, String(enabled), search, revision, reload].join("|");
  const currentScope = useRef(scope);
  currentScope.current = scope;

  async function request(after: string | null, signal?: AbortSignal): Promise<CandidatePage> {
    const params = new URLSearchParams({ limit: String(SIZE) });
    if (after) params.set("after", after);
    if (search.trim()) params.set("search", search.trim());
    const response = await fetch(
      "/api/v1/work/orders/" + orderId + "/candidates-page?" + params.toString(),
      { credentials: "same-origin", signal },
    );
    if (!response.ok) throw new Error("HTTP " + response.status);
    return await response.json() as CandidatePage;
  }

  useEffect(() => {
    setItems([]); setCursor(null); setError("");
    if (!enabled || !orderId) { setBusy(false); return; }
    const controller = new AbortController();
    const snapshot = scope;
    setBusy(true);
    const delay = search.trim() ? 250 : 0;
    const timeout = window.setTimeout(() => {
      request(null, controller.signal).then((page) => {
        if (currentScope.current !== snapshot) return;
        setItems(page.items);
        setCursor(page.next_cursor);
      }).catch((reason: unknown) => {
        if (controller.signal.aborted || currentScope.current !== snapshot) return;
        setError(reason instanceof Error ? reason.message : "Ошибка списка кандидатов");
      }).finally(() => {
        if (currentScope.current === snapshot) setBusy(false);
      });
    }, delay);
    return () => { window.clearTimeout(timeout); controller.abort(); };
  }, [scope]);

  async function loadMore() {
    if (!cursor || busy || !enabled) return;
    const snapshot = scope;
    setBusy(true); setError("");
    try {
      const page = await request(cursor);
      if (currentScope.current !== snapshot) return;
      setItems((old) => [...old, ...page.items]);
      setCursor(page.next_cursor);
    } catch (reason) {
      if (currentScope.current !== snapshot) return;
      setError(reason instanceof Error ? reason.message : "Ошибка загрузки страницы");
    } finally {
      if (currentScope.current === snapshot) setBusy(false);
    }
  }

  return {
    search, setSearch, items, busy, error,
    hasMore: cursor !== null, loadMore,
    retry: () => setReload((old) => old + 1),
  };
}
