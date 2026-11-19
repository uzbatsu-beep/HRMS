import type { ReactNode } from "react";

export type RequestKind = "loading" | "empty" | "error";

export default function RequestState({
  kind, title, detail, actionLabel, onAction, children,
}: {
  kind: RequestKind;
  title: string;
  detail?: string;
  actionLabel?: string;
  onAction?: () => void;
  children?: ReactNode;
}) {
  return (
    <div className={`twm-request-state twm-request-${kind}`}
      role={kind === "error" ? "alert" : kind === "loading" ? "status" : undefined}>
      <strong>{title}</strong>
      {detail && <p>{detail}</p>}
      {children}
      {onAction && actionLabel && (
        <button type="button" onClick={onAction}>{actionLabel}</button>
      )}
    </div>
  );
}
