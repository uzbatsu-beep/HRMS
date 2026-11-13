import { useWorkspace } from "./WorkspaceContext";

export default function WorkspaceBreadcrumbs({
  pageLabel, navigate,
}: {
  pageLabel: string;
  navigate: (page: string) => void;
}) {
  const {
    enterpriseId, unitId, personId, person, enterprises, units,
    setUnitId, setPersonId,
  } = useWorkspace();
  const enterprise = enterprises.find((entry) => entry.id === enterpriseId);
  const unit = units.find((entry) => entry.id === unitId);
  return (
    <nav className="workspace-breadcrumbs" aria-label="Контекстная навигация">
      <button type="button" onClick={() => navigate("dashboard")}>TWM</button>
      <span aria-hidden="true">/</span>
      <strong>{pageLabel}</strong>
      {enterprise && (
        <>
          <span aria-hidden="true">/</span>
          <button type="button" onClick={() => {
            setUnitId(""); navigate("organization");
          }}>{enterprise.name}</button>
        </>
      )}
      {unit && (
        <>
          <span aria-hidden="true">/</span>
          <button type="button" onClick={() => {
            setPersonId(""); navigate("personnel");
          }}>{unit.name}</button>
        </>
      )}
      {personId && person && (
        <>
          <span aria-hidden="true">/</span>
          <button type="button" onClick={() => navigate("personnel")}>
            {person.last_name} {person.first_name}
          </button>
        </>
      )}
    </nav>
  );
}
