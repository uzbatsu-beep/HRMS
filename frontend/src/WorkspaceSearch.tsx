import { useEffect, useRef, useState } from "react";
import { useWorkspace, type WorkspacePerson } from "./WorkspaceContext";

export default function WorkspaceSearch({
  openPerson,
}: {
  openPerson: (person: WorkspacePerson) => void;
}) {
  const { session, enterpriseId } = useWorkspace();
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<WorkspacePerson[]>([]);
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [activeIndex, setActiveIndex] = useState(0);
  const [searchRevision, setSearchRevision] = useState(0);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    setQuery(""); setResults([]); setOpen(false); setActiveIndex(0);
  }, [session?.user.id, enterpriseId]);

  useEffect(() => {
    const onOutside = (event: MouseEvent) => {
      if (event.target instanceof Node && !root.current?.contains(event.target))
        setOpen(false);
    };
    document.addEventListener("mousedown", onOutside);
    return () => document.removeEventListener("mousedown", onOutside);
  }, []);

  useEffect(() => {
    const normalized = query.trim();
    if (!session || !enterpriseId || normalized.length < 2) {
      setResults([]); setBusy(false); setError(""); return;
    }
    const controller = new AbortController();
    const timeout = window.setTimeout(() => {
      const params = new URLSearchParams({ q: normalized, limit: "20" });
      setBusy(true); setError("");
      fetch(`/api/v1/personnel/enterprises/${enterpriseId}/persons?${params}`, {
        credentials: "same-origin", signal: controller.signal,
      }).then(async (response) => {
        if (!response.ok) throw new Error("Поиск недоступен: " + response.status);
        return await response.json() as WorkspacePerson[];
      }).then((entries) => {
        if (!controller.signal.aborted) {
          setResults(entries);
          setActiveIndex(0);
        }
      }).catch((cause: unknown) => {
        if (!controller.signal.aborted) {
          setError(cause instanceof Error ? cause.message : "Ошибка поиска");
          setResults([]);
        }
      }).finally(() => {
        if (!controller.signal.aborted) setBusy(false);
      });
    }, 250);
    return () => { window.clearTimeout(timeout); controller.abort(); };
  }, [query, session?.user.id, enterpriseId, searchRevision]);

  if (!session || !enterpriseId) return null;

  function choose(person: WorkspacePerson) {
    openPerson(person);
    setQuery("");
    setResults([]);
    setActiveIndex(0);
    setOpen(false);
  }

  return (
    <div className="workspace-search" ref={root}>
      <label htmlFor="workspace-search-input" className="sr-only">
        Глобальный поиск сотрудников предприятия
      </label>
      <input
        id="workspace-search-input" type="search"
        aria-label="Глобальный поиск сотрудников"
        aria-expanded={open && query.trim().length >= 2}
        aria-controls="workspace-search-results"
        aria-activedescendant={
          open && results.length > 0 ? "workspace-search-option-" + results[activeIndex]?.id
            : undefined
        }
        aria-autocomplete="list"
        role="combobox"
        placeholder="Поиск сотрудника..."
        autoComplete="off"
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          setQuery(event.target.value); setResults([]); setError("");
          setActiveIndex(0); setOpen(true);
        }}
        onKeyDown={(event) => {
          if (event.key === "Escape") { setOpen(false); return; }
          if (event.key === "ArrowDown" && results.length > 0) {
            event.preventDefault(); setOpen(true);
            setActiveIndex((index) => (index + 1) % results.length);
          }
          if (event.key === "ArrowUp" && results.length > 0) {
            event.preventDefault(); setOpen(true);
            setActiveIndex((index) => (index - 1 + results.length) % results.length);
          }
          if (event.key === "Enter" && results.length > 0 && open) {
            event.preventDefault(); choose(results[activeIndex] ?? results[0]);
          }
        }}
      />
      {open && query.trim().length >= 2 && (
        <div className="workspace-search-results" id="workspace-search-results"
          role="listbox" aria-label="Найденные сотрудники" aria-busy={busy}>
          {busy ? <p role="status">Поиск...</p> : error ? (
            <div className="workspace-search-feedback" role="alert">
              <p>{error}</p>
              <button type="button" onClick={() => setSearchRevision((value) => value + 1)}>
                Повторить поиск
              </button>
            </div>
          ) : results.length === 0 ? <p>Совпадений нет</p>
            : results.map((person, index) => (
              <button type="button" role="option" aria-selected={activeIndex === index}
                id={"workspace-search-option-" + person.id}
                key={person.id} onClick={() => choose(person)}
                onMouseEnter={() => setActiveIndex(index)}>
                <strong>{person.last_name} {person.first_name}</strong>
                <small>{person.employee_code}</small>
              </button>
            ))}
        </div>
      )}
    </div>
  );
}
