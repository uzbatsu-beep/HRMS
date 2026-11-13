import { useEffect, useMemo, useState } from "react";

type Session = { user: { id: string; username: string; role: string } };
type Enterprise = { id: string; name: string; code: string };
type Unit = { id: string; name: string; code: string; parent_id: string | null };
type Person = {
  id: string; employee_code: string; first_name: string; last_name: string;
  middle_name: string | null; current_unit_id: string | null;
  position_title: string | null;
};

export type PersonFocus = {
  enterpriseId: string;
  personId: string;
  unitId: string | null;
};

async function get<T>(path: string, signal: AbortSignal): Promise<T> {
  const result = await fetch(path, { credentials: "same-origin", signal });
  if (!result.ok) throw new Error(`HTTP ${result.status}`);
  return await result.json() as T;
}

function treeRows(units: Unit[]): { unit: Unit; depth: number }[] {
  const identifiers = new Set(units.map((item) => item.id));
  const children = new Map<string, Unit[]>();
  for (const unit of units) {
    const parent = unit.parent_id && identifiers.has(unit.parent_id) ? unit.parent_id : "";
    const siblings = children.get(parent) ?? [];
    siblings.push(unit);
    children.set(parent, siblings);
  }
  const result: { unit: Unit; depth: number }[] = [];
  const visited = new Set<string>();
  const traverse = (parent: string, depth: number) => {
    const siblings = [...(children.get(parent) ?? [])].sort((a, b) =>
      a.name.localeCompare(b.name, "ru"),
    );
    for (const unit of siblings) {
      if (visited.has(unit.id)) continue;
      visited.add(unit.id);
      result.push({ unit, depth });
      traverse(unit.id, depth + 1);
    }
  };
  traverse("", 0);
  for (const unit of units) if (!visited.has(unit.id)) result.push({ unit, depth: 0 });
  return result;
}

export default function ContextRail({
  session, onPersonSelect, onNavigate,
}: {
  session: Session | null;
  onPersonSelect: (person: PersonFocus) => void;
  onNavigate: (page: string) => void;
}) {
  const [enterprises, setEnterprises] = useState<Enterprise[]>([]);
  const [enterpriseId, setEnterpriseId] = useState("");
  const [units, setUnits] = useState<Unit[]>([]);
  const [unitId, setUnitId] = useState("");
  const [persons, setPersons] = useState<Person[]>([]);
  const [search, setSearch] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  const [offset, setOffset] = useState(0);
  const [moreAvailable, setMoreAvailable] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [error, setError] = useState("");
  const [peopleLoading, setPeopleLoading] = useState(false);

  useEffect(() => {
    const onChange = () => setRefresh((current) => current + 1);
    window.addEventListener("twm-org-changed", onChange);
    window.addEventListener("twm-personnel-changed", onChange);
    return () => {
      window.removeEventListener("twm-org-changed", onChange);
      window.removeEventListener("twm-personnel-changed", onChange);
    };
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => setSearchTerm(search.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    if (!session) {
      setEnterprises([]); setEnterpriseId(""); setUnits([]);
      setPersons([]); setError(""); return;
    }
    const controller = new AbortController();
    get<Enterprise[]>("/api/v1/org/enterprises", controller.signal)
      .then((data) => {
        setEnterprises(data);
        setEnterpriseId((previous) => data.some((row) => row.id === previous)
          ? previous : data[0]?.id ?? "");
        setError("");
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(
          reason instanceof Error ? reason.message : "Ошибка списка предприятий",
        );
      });
    return () => controller.abort();
  }, [session?.user.id, refresh]);

  useEffect(() => {
    setUnitId(""); setUnits([]);
    if (!session || !enterpriseId) return;
    const controller = new AbortController();
    get<Unit[]>(`/api/v1/org/enterprises/${enterpriseId}/units`, controller.signal)
      .then((data) => setUnits(data))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(
          reason instanceof Error ? reason.message : "Ошибка подразделений",
        );
      });
    return () => controller.abort();
  }, [enterpriseId, session?.user.id, refresh]);

  useEffect(() => { setOffset(0); setPersons([]); }, [
    enterpriseId, unitId, searchTerm, session?.user.id,
  ]);

  useEffect(() => {
    if (!session || !enterpriseId) {
      setPeopleLoading(false); setPersons([]); return;
    }
    const controller = new AbortController();
    const params = new URLSearchParams({ limit: "100", offset: String(offset) });
    if (unitId) params.set("unit_id", unitId);
    if (searchTerm) params.set("q", searchTerm);
    setPeopleLoading(true);
    get<Person[]>(`/api/v1/personnel/enterprises/${enterpriseId}/persons?${params}`,
      controller.signal)
      .then((data) => {
        setPersons((previous) => offset === 0 ? data : [
          ...previous, ...data.filter((x) => !previous.some((row) => row.id === x.id)),
        ]);
        setMoreAvailable(data.length === 100);
        setError("");
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(
          reason instanceof Error ? reason.message : "Ошибка списка персонала",
        );
      })
      .finally(() => { if (!controller.signal.aborted) setPeopleLoading(false); });
    return () => controller.abort();
  }, [enterpriseId, unitId, searchTerm, offset, session?.user.id, refresh]);

  const hierarchy = useMemo(() => treeRows(units), [units]);
  const activeCompany = enterprises.find((row) => row.id === enterpriseId);

  return (
    <aside className="workspace-rail" aria-label="Контекст предприятия">
      <div className="rail-title">
        <div>
          <small>РАБОЧИЙ КОНТЕКСТ</small>
          <h2>Структура и персонал</h2>
        </div>
        <button type="button" title="Обновить данные" className="rail-refresh"
          onClick={() => setRefresh((old) => old + 1)}>↻</button>
      </div>
      {!session ? (
        <div className="rail-empty">
          <p>Для просмотра структуры предприятия и сотрудников требуется вход.</p>
          <button className="rail-action" onClick={() => onNavigate("access")}>
            Войти в систему
          </button>
        </div>
      ) : (
        <>
          <label className="rail-label">Предприятие
            <select value={enterpriseId} onChange={(event) => setEnterpriseId(event.target.value)}>
              {enterprises.length === 0 && <option value="">Нет доступных предприятий</option>}
              {enterprises.map((row) => (
                <option value={row.id} key={row.id}>{row.name}</option>
              ))}
            </select>
          </label>
          <section className="rail-group" aria-labelledby="rail-units-heading">
            <div className="rail-group-heading">
              <h3 id="rail-units-heading">Подразделения</h3>
              <span>{units.length}</span>
            </div>
            <div className="rail-tree" role="group" aria-label="Дерево подразделений">
              <button type="button" className={`rail-unit ${!unitId ? "active" : ""}`}
                onClick={() => setUnitId("")}>
                <span className="rail-tree-symbol">▣</span>
                <span>{activeCompany?.name ?? "Все подразделения"}</span>
              </button>
              {hierarchy.map(({ unit, depth }) => (
                <button key={unit.id} type="button"
                  className={`rail-unit ${unitId === unit.id ? "active" : ""}`}
                  style={{ paddingLeft: `${14 + Math.min(depth, 7) * 14}px` }}
                  onClick={() => setUnitId(unit.id)}
                  title={unit.name}>
                  <span className="rail-tree-symbol">{depth ? "└" : "▸"}</span>
                  <span>{unit.name}</span>
                </button>
              ))}
              {units.length === 0 && <p className="rail-empty-text">Нет видимых подразделений.</p>}
            </div>
            <button className="rail-text-link" type="button"
              onClick={() => onNavigate("organization")}>
              Управление структурой
            </button>
          </section>
          <section className="rail-group rail-personnel" aria-labelledby="rail-people-heading">
            <div className="rail-group-heading">
              <h3 id="rail-people-heading">Персонал</h3>
              <span>{persons.length}{moreAvailable ? "+" : ""}</span>
            </div>
            <label className="rail-label">
              <span className="sr-only">Поиск сотрудника</span>
              <input value={search} onChange={(e) => setSearch(e.target.value)}
                placeholder="Фамилия, имя или таб. №" />
            </label>
            <div className="rail-people-list">
              {persons.map((person) => (
                <button type="button" className="rail-person" key={person.id}
                  onClick={() => onPersonSelect({
                    enterpriseId, personId: person.id, unitId: person.current_unit_id,
                  })}>
                  <span className="rail-avatar">{person.last_name.slice(0, 1)}</span>
                  <span className="rail-person-details">
                    <strong>{person.last_name} {person.first_name}</strong>
                    <small>{person.employee_code} · {person.position_title ?? "Специалист"}</small>
                  </span>
                </button>
              ))}
              {!peopleLoading && persons.length === 0 &&
                <p className="rail-empty-text">Нет сотрудников по выбранным условиям.</p>}
              {peopleLoading && <p className="rail-empty-text">Загрузка персонала…</p>}
            </div>
            {moreAvailable && !peopleLoading && (
              <button className="rail-text-link" type="button"
                onClick={() => setOffset((value) => value + 100)}>Показать ещё</button>
            )}
            <button className="rail-text-link" type="button"
              onClick={() => onNavigate("personnel")}>
              Все карточки персонала
            </button>
          </section>
          {error && <p className="rail-error" role="alert">{error}</p>}
        </>
      )}
    </aside>
  );
}
