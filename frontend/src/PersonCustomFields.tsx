import { useEffect, useState, type FormEvent } from "react";
import { useWorkspace } from "./WorkspaceContext";
import type { CustomField } from "./ConfiguratorPanel";

type Value = string | number | boolean | null;
type FieldResult = {
  person_id: string; config_version: number | null;
  fields: CustomField[]; values: Record<string, Value>;
};

export default function PersonCustomFields({
  personId, archived,
}: { personId: string; archived: boolean }) {
  const { session } = useWorkspace();
  const [result, setResult] = useState<FieldResult | null>(null);
  const [draft, setDraft] = useState<Record<string, Value>>({});
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setResult(null); setDraft({}); setError(""); setNotice("");
    if (!session || !personId) { setLoading(false); return; }
    fetch("/api/v1/configuration/persons/" + encodeURIComponent(personId) + "/fields", {
      credentials: "same-origin", signal: controller.signal,
    }).then(async (response) => {
      if (!response.ok) throw new Error("HTTP " + response.status);
      return await response.json() as FieldResult;
    }).then((data) => {
      if (!controller.signal.aborted) { setResult(data); setDraft(data.values); }
    }).catch((cause: unknown) => {
      if (!controller.signal.aborted) {
        setError(cause instanceof Error ? cause.message : "Ошибка конфигурации");
      }
    }).finally(() => {
      if (!controller.signal.aborted) setLoading(false);
    });
    return () => controller.abort();
  }, [session?.user.id, personId]);

  async function save(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!session || session.user.role !== "admin" || !result) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const response = await fetch(
        "/api/v1/configuration/persons/" + encodeURIComponent(personId) + "/fields", {
          method: "PUT", credentials: "same-origin",
          headers: { "Content-Type": "application/json", "X-CSRF-Token": session.csrf_token },
          body: JSON.stringify({ values: draft }),
        },
      );
      if (!response.ok) {
        const body = await response.json() as { detail?: string };
        throw new Error("HTTP " + response.status + ": " + (body.detail ?? "Запрос отклонён"));
      }
      const data = await response.json() as FieldResult;
      setResult(data); setDraft(data.values);
      setNotice("Дополнительные данные сохранены с историей изменений.");
    } catch (cause: unknown) {
      setError(cause instanceof Error ? cause.message : "Ошибка сохранения");
    } finally { setBusy(false); }
  }

  if (loading) return <div className="config-person-fields">Загрузка дополнительных полей…</div>;
  if (error && !result) return (
    <div className="config-person-fields" role="alert">Дополнительные поля: {error}</div>
  );
  if (!result || result.fields.length === 0) return null;
  const editable = session?.user.role === "admin" && !archived;
  return (
    <section className="config-person-fields" aria-label="Дополнительные поля сотрудника">
      <h4>Дополнительные поля · схема v{result.config_version}</h4>
      <form onSubmit={save}>
        {result.fields.map((field) => (
          <label key={field.code}>
            {field.label}{field.required ? " *" : ""}
            {field.kind === "boolean" ? (
              <input type="checkbox" disabled={!editable || busy}
                checked={draft[field.code] === true}
                onChange={(event) => setDraft((old) => ({
                  ...old, [field.code]: event.target.checked,
                }))} />
            ) : field.kind === "choice" ? (
              <select disabled={!editable || busy}
                value={draft[field.code] == null ? "" : String(draft[field.code])}
                onChange={(event) => setDraft((old) => ({
                  ...old, [field.code]: event.target.value || null,
                }))}>
                <option value="">Не указано</option>
                {field.options.map((option) =>
                  <option key={option} value={option}>{option}</option>)}
              </select>
            ) : (
              <input type={field.kind === "integer" ? "number" : "text"}
                disabled={!editable || busy}
                maxLength={field.kind === "text" ? field.max_length ?? 120 : undefined}
                min={field.kind === "integer" ? field.min_value ?? undefined : undefined}
                max={field.kind === "integer" ? field.max_value ?? undefined : undefined}
                value={draft[field.code] == null ? "" : String(draft[field.code])}
                onChange={(event) => {
                  const value = event.target.value;
                  setDraft((old) => ({
                    ...old, [field.code]: value === "" ? null
                      : field.kind === "integer" ? Number(value) : value,
                  }));
                }} />
            )}
          </label>
        ))}
        {editable && (
          <button type="submit" disabled={busy}>Сохранить дополнительные поля</button>
        )}
      </form>
      {error && <p className="config-error" role="alert">{error}</p>}
      {notice && <p className="config-notice" role="status">{notice}</p>}
      <p>Информационные данные. Не используются для подтверждения допусков.</p>
    </section>
  );
}
