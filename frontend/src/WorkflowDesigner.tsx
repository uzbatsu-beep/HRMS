import type { ReactNode } from "react";

export type FormField = {
  code: string; label: string;
  kind: "text" | "integer" | "boolean" | "choice";
  required: boolean;
  max_length?: number | null;
  min_value?: number | null; max_value?: number | null;
  options: string[];
};

export type WorkflowState = {
  code: string; label: string; terminal: boolean;
};
export type WorkflowTransition = {
  code: string; label: string; from_state: string; to_state: string;
  actor: "creator" | "manager" | "admin"; independent_review: boolean;
};

export type WorkflowDocument = {
  fields: FormField[];
  states: WorkflowState[];
  transitions: WorkflowTransition[];
  initial_state: string;
};

export type WorkflowVersion = {
  id: string; code: string; title: string; version: number;
  status: "draft" | "validated" | "approved" | "published";
  created_by: string; approved_by: string | null;
  effective_on: string | null; document: WorkflowDocument;
};

export const initialWorkflow = (): WorkflowDocument => ({
  fields: [
    { code: "request_note", label: "Описание обращения", kind: "text",
      required: true, max_length: 400, options: [] },
  ],
  initial_state: "draft",
  states: [
    { code: "draft", label: "Черновик", terminal: false },
    { code: "submitted", label: "Ожидает рассмотрения", terminal: false },
    { code: "resolved", label: "Рассмотрено", terminal: true },
  ],
  transitions: [
    { code: "submit", label: "Передать на рассмотрение",
      from_state: "draft", to_state: "submitted",
      actor: "creator", independent_review: false },
    { code: "resolve", label: "Завершить рассмотрение",
      from_state: "submitted", to_state: "resolved",
      actor: "manager", independent_review: true },
  ],
});

const actorLabels = {
  creator: "Автор обращения", manager: "Руководитель", admin: "Администратор",
};

function Group({ heading, children }: { heading: string; children: ReactNode }) {
  return <fieldset className="config-v2-field">
    <legend>{heading}</legend>
    {children}
  </fieldset>;
}

export default function WorkflowDesigner({
  value, onChange, disabled,
}: {
  value: WorkflowDocument;
  onChange: (doc: WorkflowDocument) => void;
  disabled: boolean;
}) {
  const patchField = (index: number, patch: Partial<FormField>) => {
    onChange({ ...value, fields: value.fields.map((field, i) =>
      i === index ? { ...field, ...patch } : field) });
  };
  const patchState = (index: number, patch: Partial<WorkflowState>) => {
    onChange({ ...value, states: value.states.map((state, i) =>
      i === index ? { ...state, ...patch } : state) });
  };
  const patchRoute = (index: number, patch: Partial<WorkflowTransition>) => {
    onChange({ ...value, transitions: value.transitions.map((route, i) =>
      i === index ? { ...route, ...patch } : route) });
  };

  return <div className="config-form">
    <h4>Форма обращения · до 12 полей</h4>
    {value.fields.map((field, index) => (
      <Group key={index} heading={"Поле " + (index + 1)}>
        <label>Код поля
          <input disabled={disabled} value={field.code}
            onChange={(e) => patchField(index, { code: e.target.value })}
            maxLength={32} pattern="[a-z][a-z0-9_]*" />
        </label>
        <label>Название поля
          <input disabled={disabled} value={field.label}
            onChange={(e) => patchField(index, { label: e.target.value })} />
        </label>
        <label>Тип данных
          <select disabled={disabled} value={field.kind}
            onChange={(e) => {
              const kind = e.target.value as FormField["kind"];
              patchField(index, {
                kind, max_length: kind === "text" ? 120 : null,
                min_value: null, max_value: null,
                options: kind === "choice" ? ["Вариант А", "Вариант Б"] : [],
              });
            }}>
            <option value="text">Текст</option>
            <option value="integer">Целое число</option>
            <option value="boolean">Да / нет</option>
            <option value="choice">Выбор</option>
          </select>
        </label>
        <label className="config-checkbox">
          <input type="checkbox" disabled={disabled} checked={field.required}
            onChange={(e) => patchField(index, { required: e.target.checked })} />
          Обязательное поле
        </label>
        {field.kind === "text" && <label>Максимум символов
          <input type="number" min={1} max={400} disabled={disabled}
            value={field.max_length ?? 120}
            onChange={(e) => patchField(index, { max_length: +e.target.value })}/>
        </label>}
        {field.kind === "integer" && <>
          <label>Минимум <input type="number" disabled={disabled}
            value={field.min_value ?? ""}
            onChange={(e) => patchField(index, {
              min_value: e.target.value === "" ? null : +e.target.value,
            })} /></label>
          <label>Максимум <input type="number" disabled={disabled}
            value={field.max_value ?? ""}
            onChange={(e) => patchField(index, {
              max_value: e.target.value === "" ? null : +e.target.value,
            })} /></label>
        </>}
        {field.kind === "choice" && <label>Варианты через запятую
          <input disabled={disabled} value={field.options.join(", ")}
            onChange={(e) => patchField(index, {
              options: e.target.value.split(",").map((part) => part.trim()),
            })} />
        </label>}
        {!disabled && <button type="button" onClick={() => onChange({
          ...value, fields: value.fields.filter((_, i) => i !== index),
        })}>Удалить поле</button>}
      </Group>
    ))}
    {!disabled && <button type="button" disabled={value.fields.length >= 12}
      onClick={() => onChange({ ...value, fields: [...value.fields, {
        code: "", label: "", kind: "text", required: false,
        max_length: 120, options: [],
      }] })}>Добавить поле</button>}

    <h4>Состояния · 2–8 · минимум одно конечное</h4>
    <p className="org-hint">Это состояния информационной заявки, а не наряда
      или производственного разрешения.</p>
    <label>Исходное состояние
      <select value={value.initial_state} disabled={disabled}
        onChange={(e) => onChange({ ...value, initial_state: e.target.value })}>
        {value.states.map((state) => <option key={state.code} value={state.code}>
          {state.label || state.code}</option>)}
      </select>
    </label>
    {value.states.map((state, index) => (
      <Group key={index} heading={"Состояние " + (index + 1)}>
        <label>Код
          <input disabled={disabled} value={state.code}
            onChange={(e) => patchState(index, { code: e.target.value })} />
        </label>
        <label>Название
          <input disabled={disabled} value={state.label}
            onChange={(e) => patchState(index, { label: e.target.value })} />
        </label>
        <label className="config-checkbox">
          <input type="checkbox" disabled={disabled} checked={state.terminal}
            onChange={(e) => patchState(index, { terminal: e.target.checked })} />
          Конечное состояние (только независимое решение)
        </label>
        {!disabled && <button type="button" onClick={() => onChange({
          ...value, states: value.states.filter((_, i) => i !== index),
        })}>Удалить состояние</button>}
      </Group>
    ))}
    {!disabled && <button type="button" disabled={value.states.length >= 8}
      onClick={() => onChange({ ...value, states: [...value.states, {
        code: "", label: "", terminal: false,
      }] })}>Добавить состояние</button>}

    <h4>Маршруты переходов · до 24</h4>
    {value.transitions.map((route, index) => (
      <Group key={index} heading={"Переход " + (index + 1)}>
        <label>Код перехода
          <input disabled={disabled} value={route.code}
            onChange={(e) => patchRoute(index, { code: e.target.value })} />
        </label>
        <label>Действие
          <input disabled={disabled} value={route.label}
            onChange={(e) => patchRoute(index, { label: e.target.value })} />
        </label>
        <label>Из состояния
          <select disabled={disabled} value={route.from_state}
            onChange={(e) => patchRoute(index, { from_state: e.target.value })}>
            {value.states.map((state) => <option key={state.code} value={state.code}>
              {state.label || state.code}</option>)}
          </select>
        </label>
        <label>В состояние
          <select disabled={disabled} value={route.to_state}
            onChange={(e) => patchRoute(index, { to_state: e.target.value })}>
            {value.states.map((state) => <option key={state.code} value={state.code}>
              {state.label || state.code}</option>)}
          </select>
        </label>
        <label>Кто выполняет
          <select disabled={disabled} value={route.actor}
            onChange={(e) => patchRoute(index, {
              actor: e.target.value as WorkflowTransition["actor"],
            })}>
            {Object.entries(actorLabels).map(([key, label]) =>
              <option key={key} value={key}>{label}</option>)}
          </select>
        </label>
        <label className="config-checkbox">
          <input type="checkbox" disabled={disabled}
            checked={route.independent_review}
            onChange={(e) => patchRoute(index, { independent_review: e.target.checked })} />
          Независимое рассмотрение (не автором заявки)
        </label>
        {!disabled && <button type="button" onClick={() => onChange({
          ...value, transitions: value.transitions.filter((_, i) => i !== index),
        })}>Удалить переход</button>}
      </Group>
    ))}
    {!disabled && <button type="button" disabled={value.transitions.length >= 24}
      onClick={() => onChange({ ...value, transitions: [...value.transitions, {
        code: "", label: "", from_state: value.initial_state,
        to_state: value.states[1]?.code ?? "",
        actor: "manager", independent_review: false,
      }] })}>Добавить переход</button>}
  </div>;
}
