import {
  createContext, useCallback, useContext, useEffect, useMemo, useState,
  type Dispatch, type ReactNode, type SetStateAction,
} from "react";

export type WorkspaceEnterprise = { id: string; name: string; code: string };
export type WorkspaceUnit = {
  id: string; enterprise_id: string; name: string; code: string; parent_id: string | null;
};
export type WorkspacePerson = {
  id: string; enterprise_id: string; first_name: string; last_name: string;
  current_unit_id: string | null; employee_code: string;
};
export type WorkspaceSession = {
  user: { id: string; username: string; role: "admin" | "manager" | "viewer" };
  csrf_token: string;
};

interface WorkspaceSelection {
  session: WorkspaceSession | null;
  loading: boolean;
  enterprises: WorkspaceEnterprise[];
  units: WorkspaceUnit[];
  enterpriseId: string;
  unitId: string;
  personId: string;
  person: WorkspacePerson | null;
  error: string;
  setEnterpriseId: Dispatch<SetStateAction<string>>;
  setUnitId: Dispatch<SetStateAction<string>>;
  setPersonId: Dispatch<SetStateAction<string>>;
  focusPerson: (enterpriseId: string, personId: string, unitId?: string | null) => void;
  refresh: () => void;
}

const Workspace = createContext<WorkspaceSelection | null>(null);

async function read<T>(url: string, signal: AbortSignal): Promise<T> {
  const response = await fetch(url, { credentials: "same-origin", signal });
  if (!response.ok) throw new Error(`HTTP ${response.status}: ${url}`);
  return await response.json() as T;
}

export function WorkspaceProvider({ children }: { children: ReactNode }) {
  const [session, setSession] = useState<WorkspaceSession | null>(null);
  const [loading, setLoading] = useState(true);
  const [authRevision, setAuthRevision] = useState(0);
  const [revision, setRevision] = useState(0);
  const [enterprises, setEnterprises] = useState<WorkspaceEnterprise[]>([]);
  const [units, setUnits] = useState<WorkspaceUnit[]>([]);
  const [enterpriseId, writeEnterprise] = useState("");
  const [unitId, writeUnit] = useState("");
  const [personId, writePerson] = useState("");
  const [person, setPerson] = useState<WorkspacePerson | null>(null);
  const [error, setError] = useState("");

  const refresh = useCallback(() => setRevision((value) => value + 1), []);

  useEffect(() => {
    const onAuth = () => {
      // Clear all context immediately: no old user/company IDs survive logout
      // or impersonation while the new session is being established.
      setSession(null);
      setEnterprises([]); setUnits([]); setPerson(null);
      writeEnterprise(""); writeUnit(""); writePerson("");
      setAuthRevision((value) => value + 1);
    };
    window.addEventListener("twm-auth-changed", onAuth);
    window.addEventListener("twm-org-changed", refresh);
    window.addEventListener("twm-personnel-changed", refresh);
    return () => {
      window.removeEventListener("twm-auth-changed", onAuth);
      window.removeEventListener("twm-org-changed", refresh);
      window.removeEventListener("twm-personnel-changed", refresh);
    };
  }, [refresh]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    read<WorkspaceSession>("/api/v1/auth/me", controller.signal)
      .then((value) => { if (!controller.signal.aborted) setSession(value); })
      .catch(() => { if (!controller.signal.aborted) setSession(null); })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [authRevision]);

  useEffect(() => {
    if (!session) {
      setEnterprises([]); setUnits([]); setPerson(null);
      writeEnterprise(""); writeUnit(""); writePerson("");
      return;
    }
    const controller = new AbortController();
    // A person-linked viewer can access their own competence / credentials
    // even if they have no broader organization scope.
    Promise.all([
      read<WorkspaceEnterprise[]>("/api/v1/org/enterprises", controller.signal),
      read<{ enterprise_id: string; enterprise_name: string } | null>(
        "/api/v1/competence/me/link", controller.signal,
      ).catch(() => null),
    ]).then(([rows, own]) => {
      if (controller.signal.aborted) return;
      const available = [...rows];
      if (own && !available.some((entry) => entry.id === own.enterprise_id)) {
        available.push({
          id: own.enterprise_id, name: own.enterprise_name, code: "own",
        });
      }
      setEnterprises(available);
      writeEnterprise((old) =>
        available.some((entry) => entry.id === old) ? old : available[0]?.id ?? "");
      setError("");
    }).catch((cause: unknown) => {
      if (controller.signal.aborted) return;
      setEnterprises([]); writeEnterprise("");
      setError(cause instanceof Error ? cause.message : "Ошибка списка предприятий");
    });
    return () => controller.abort();
  }, [session?.user.id, revision]);

  useEffect(() => {
    setUnits([]);
    if (!session || !enterpriseId) { writeUnit(""); writePerson(""); return; }
    const controller = new AbortController();
    read<WorkspaceUnit[]>(
      `/api/v1/org/enterprises/${enterpriseId}/units`, controller.signal,
    ).then((rows) => {
      if (controller.signal.aborted) return;
      setUnits(rows);
      writeUnit((old) => old && rows.some((unit) => unit.id === old) ? old : "");
    }).catch(() => {
      if (!controller.signal.aborted) {
        setUnits([]);
        writeUnit("");
      }
    });
    return () => controller.abort();
  }, [session?.user.id, enterpriseId, revision]);

  useEffect(() => {
    setPerson(null);
    if (!session || !enterpriseId || !personId) return;
    const controller = new AbortController();
    read<WorkspacePerson>(
      `/api/v1/personnel/persons/${personId}`, controller.signal,
    ).then((value) => {
      if (controller.signal.aborted) return;
      if (value.enterprise_id === enterpriseId) setPerson(value);
      else writePerson("");
    }).catch(() => {
      // Stale, archived or no-longer-visible workers must not stay in shared
      // navigation context after an organizational change.
      if (!controller.signal.aborted) writePerson("");
    });
    return () => controller.abort();
  }, [session?.user.id, enterpriseId, personId, revision]);

  const setEnterpriseId = useCallback<Dispatch<SetStateAction<string>>>((action) => {
    const candidate = typeof action === "function" ? action(enterpriseId) : action;
    if (candidate && !enterprises.some((entry) => entry.id === candidate)) return;
    if (candidate !== enterpriseId) {
      writeUnit("");
      writePerson("");
      setPerson(null);
      writeEnterprise(candidate);
    }
  }, [enterprises, enterpriseId]);

  const setUnitId = useCallback<Dispatch<SetStateAction<string>>>((action) => {
    const candidate = typeof action === "function" ? action(unitId) : action;
    if (candidate && !units.some((unit) => unit.id === candidate)) return;
    if (candidate !== unitId) {
      writePerson("");
      setPerson(null);
      writeUnit(candidate);
    }
  }, [units, unitId]);

  const setPersonId = useCallback<Dispatch<SetStateAction<string>>>((action) => {
    writePerson((old) => typeof action === "function" ? action(old) : action);
  }, []);

  const focusPerson = useCallback((
    companyId: string, selectedId: string, selectedUnit?: string | null,
  ) => {
    if (!enterprises.some((entry) => entry.id === companyId)) return;
    if (companyId !== enterpriseId) {
      writeEnterprise(companyId);
      writeUnit(""); // Unit list will refresh for the new enterprise.
    } else if (selectedUnit && units.some((unit) => unit.id === selectedUnit)) {
      writeUnit(selectedUnit);
    }
    writePerson(selectedId);
  }, [enterprises, enterpriseId, units]);

  const value = useMemo<WorkspaceSelection>(() => ({
    session, loading, enterprises, units, enterpriseId, unitId, personId, person,
    error, setEnterpriseId, setUnitId, setPersonId, focusPerson, refresh,
  }), [
    session, loading, enterprises, units, enterpriseId, unitId, personId,
    person, error, setEnterpriseId, setUnitId, setPersonId, focusPerson, refresh,
  ]);
  return <Workspace.Provider value={value}>{children}</Workspace.Provider>;
}

export function useWorkspace(): WorkspaceSelection {
  const context = useContext(Workspace);
  if (!context) throw new Error("useWorkspace must be called inside WorkspaceProvider");
  return context;
}
