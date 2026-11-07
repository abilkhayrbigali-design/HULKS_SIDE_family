import { AlertCircle, ArrowLeft, LoaderCircle, X } from "lucide-react";
import { useEffect, useRef } from "react";
import type { ReactNode } from "react";
import { ApiError } from "./api/client";
import type { Status } from "./api/types";
export const number = (n: number | null | undefined) =>
  n == null
    ? "—"
    : new Intl.NumberFormat("ru-RU", {
        maximumFractionDigits: 2,
        minimumFractionDigits: 2,
      }).format(n);
export const date = (s: string) =>
  new Date(s).toLocaleString("ru-RU", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  });
export const statusLabel: Record<Status, string> = {
  queued: "В очереди",
  running: "Анализируется",
  completed: "Оценён",
  failed: "Ошибка оценки",
};
export function StatusBadge({ status }: { status: Status }) {
  return (
    <span className={`badge ${status}`}>
      {["queued", "running"].includes(status) && (
        <LoaderCircle size={12} className="spin" />
      )}
      {statusLabel[status]}
    </span>
  );
}
export function ErrorBox({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry?: () => void;
}) {
  return (
    <div className="error-box" role="alert">
      <AlertCircle size={20} />
      <div>
        <strong>
          {error instanceof Error
            ? error.message
            : "Не удалось выполнить действие."}
        </strong>
        {error instanceof ApiError && (
          <small>
            Код: {error.code}
            {error.status ? ` · HTTP ${error.status}` : ""}
          </small>
        )}
      </div>
      {onRetry && (
        <button className="button small" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}
export function Loading({ text = "Загружаем данные…" }: { text?: string }) {
  return (
    <div className="loading" role="status">
      <LoaderCircle className="spin" size={23} />
      {text}
    </div>
  );
}
export function Modal({
  title,
  onClose,
  children,
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
}) {
  const modal = useRef<HTMLElement>(null);
  const previousFocus = useRef(document.activeElement as HTMLElement | null);
  const close = useRef(onClose);
  close.current = onClose;
  useEffect(() => {

    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        close.current();
      }
      if (event.key === "Tab") {
        const focusable = Array.from(
          modal.current?.querySelectorAll<HTMLElement>(
            "button:not(:disabled),input:not(:disabled),select:not(:disabled),textarea:not(:disabled),a[href]",
          ) ?? [],
        ).filter((e) => e.getClientRects().length > 0);
        const first = focusable[0],
          last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last?.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first?.focus();
        }
      }
    };
    modal.current?.focus();
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("keydown", onKey);
      previousFocus.current?.focus();
    };
  }, []);
  return (
    <div
      className="modal-backdrop"
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
    >
      <section
        className="modal"
        ref={modal}
        tabIndex={-1}
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <header>
          <h2>{title}</h2>
          <button
            className="icon-button"
            aria-label="Закрыть"
            onClick={onClose}
          >
            <X size={20} />
          </button>
        </header>
        {children}
      </section>
    </div>
  );
}
export function BackLink() {
  return (
    <a className="back-link" href="#/dialogues">
      <ArrowLeft size={16} />
      Все диалоги
    </a>
  );
}
export function Empty({
  title,
  text,
  children,
}: {
  title: string;
  text: string;
  children?: ReactNode;
}) {
  return (
    <div className="empty">
      <div className="empty-symbol">↗</div>
      <h2>{title}</h2>
      <p>{text}</p>
      {children}
    </div>
  );
}
