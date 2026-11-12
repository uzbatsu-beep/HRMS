import { FormEvent, useEffect, useState } from "react";

type Role = "admin" | "manager" | "viewer";
type User = { id: string; username: string; role: Role; is_active: boolean };
type AuthResponse = { user: User; csrf_token: string };
type AuthStatus = "checking" | "signed_out" | "signed_in" | "working";

const roles: Record<Role, string> = {
  admin: "Администратор",
  manager: "Руководитель",
  viewer: "Наблюдатель",
};

export default function AuthPanel() {
  const [status, setStatus] = useState<AuthStatus>("checking");
  const [user, setUser] = useState<User | null>(null);
  const [csrf, setCsrf] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [newUsername, setNewUsername] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [newRole, setNewRole] = useState<Role>("viewer");
  const [createMessage, setCreateMessage] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    fetch("/api/v1/auth/me", { credentials: "same-origin", signal: controller.signal })
      .then(async (response) => {
        if (!response.ok) return null;
        return (await response.json()) as AuthResponse;
      })
      .then((data) => {
        if (!data) {
          setStatus("signed_out");
          return;
        }
        setUser(data.user);
        setCsrf(data.csrf_token);
        setStatus("signed_in");
      window.dispatchEvent(new Event("twm-auth-changed"));
      })
      .catch((reason: unknown) => {
        if (reason instanceof Error && reason.name === "AbortError") return;
        setStatus("signed_out");
      });
    return () => controller.abort();
  }, []);

  async function login(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setStatus("working");
    setError("");
    try {
      const response = await fetch("/api/v1/auth/login", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username, password }),
      });
      if (!response.ok) throw new Error("Неправильный логин, пароль или доступ запрещён.");
      const data = (await response.json()) as AuthResponse;
      setUser(data.user);
      setCsrf(data.csrf_token);
      setPassword("");
      setStatus("signed_in");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Ошибка соединения с сервером.");
      setPassword("");
      setStatus("signed_out");
    }
  }

  async function logout() {
    if (!csrf) return;
    setStatus("working");
    setError("");
    try {
      const response = await fetch("/api/v1/auth/logout", {
        method: "POST",
        credentials: "same-origin",
        headers: { "X-CSRF-Token": csrf },
      });
      if (!response.ok) throw new Error("Не удалось завершить сессию.");
      setUser(null);
      setCsrf("");
      setCreateMessage("");
      setStatus("signed_out");
      window.dispatchEvent(new Event("twm-auth-changed"));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Ошибка выхода.");
      setStatus("signed_in");
    }
  }

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError("");
    setCreateMessage("");
    try {
      const response = await fetch("/api/v1/auth/users", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-CSRF-Token": csrf },
        body: JSON.stringify({
          username: newUsername,
          password: newPassword,
          role: newRole,
        }),
      });
      if (!response.ok) {
        const message = response.status === 409
          ? "Такое имя пользователя уже существует."
          : "Не удалось создать пользователя. Проверьте поля и права доступа.";
        throw new Error(message);
      }
      const created = (await response.json()) as User;
      setCreateMessage(`Пользователь ${created.username} создан.`);
      window.dispatchEvent(new Event("twm-auth-changed"));
      setNewUsername("");
      setNewPassword("");
      setNewRole("viewer");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Ошибка создания пользователя.");
    }
  }

  return (
    <section className="auth-panel" aria-labelledby="auth-title">
      <div className="section-heading">
        <div>
          <div className="eyebrow">IDENTITY & ACCESS</div>
          <h2 id="auth-title">Доступ к системе</h2>
        </div>
        <span className="auth-badge">Phase 2 · начало</span>
      </div>
      {status === "checking" && <p role="status">Проверяем авторизацию...</p>}
      {(status === "signed_out" || (status === "working" && !user)) && (
        <>
          <form className="auth-form" onSubmit={login}>
            <label>
              Имя пользователя
              <input
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
                required
                maxLength={100}
                disabled={status === "working"}
              />
            </label>
            <label>
              Пароль
              <input
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                required
                disabled={status === "working"}
              />
            </label>
            <button className="auth-button" type="submit" disabled={status === "working"}>
              {status === "working" ? "Вход..." : "Войти"}
            </button>
          </form>
          <p className="auth-help">
            Первого администратора создают на сервере командой
            <code>python -m app.identity.bootstrap_admin</code>. Демонстрационных паролей нет.
          </p>
        </>
      )}
      {user && (status === "signed_in" || status === "working") && (
        <>
          <div className="auth-current">
            <div>
              <strong>{user.username}</strong>
              <span>{roles[user.role]} · активная серверная сессия</span>
            </div>
            <button className="auth-button auth-button-secondary" type="button"
              onClick={logout} disabled={status === "working"}>
              Выйти
            </button>
          </div>
          {user.role === "admin" && (
            <form className="auth-form auth-create" onSubmit={createUser}>
              <h3>Добавить пользователя</h3>
              <label>
                Логин
                <input value={newUsername} onChange={(event) => setNewUsername(event.target.value)}
                  required minLength={3} maxLength={100} pattern="[a-zA-Z0-9_.-]+"
                  autoComplete="off" />
              </label>
              <label>
                Временный пароль (не менее 12 символов)
                <input type="password" autoComplete="new-password" minLength={12}
                  value={newPassword} onChange={(event) => setNewPassword(event.target.value)}
                  required />
              </label>
              <label>
                Роль
                <select value={newRole} onChange={(event) => setNewRole(event.target.value as Role)}>
                  <option value="viewer">Наблюдатель</option>
                  <option value="manager">Руководитель</option>
                  <option value="admin">Администратор</option>
                </select>
              </label>
              <button className="auth-button" type="submit">Создать</button>
            </form>
          )}
          {createMessage && <p className="auth-success" role="status">{createMessage}</p>}
        </>
      )}
      {error && <p className="auth-error" role="alert">{error}</p>}
      <p className="auth-footnote">
        Ролевая проверка действует на сервере. Организационные области доступа
        настраиваются администратором в разделе ниже; доменные операции появятся позже.
      </p>
    </section>
  );
}
