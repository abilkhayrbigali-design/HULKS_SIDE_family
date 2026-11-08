import {
  AlertCircle,
  ArrowLeft,
  LoaderCircle,
  X,
  CircleCheck,
  CircleX,
  Clock3,
} from "lucide-react";
import { useRef } from "react";
import { Badge } from "./components/ui/badge";
import { Button } from "./components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetTitle,
  SheetDescription,
} from "./components/ui/sheet";
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
    <Badge variant="outline" className={`badge ${status}`}>
      {status === "completed" ? (
        <CircleCheck size={11} />
      ) : status === "failed" ? (
        <CircleX size={11} />
      ) : status === "running" ? (
        <LoaderCircle size={11} className="spin" />
      ) : (
        <Clock3 size={11} />
      )}{" "}
      {statusLabel[status]}
    </Badge>
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
  description = "Импорт группы данных или загрузка JSON с транскриптами.",
}: {
  title: string;
  onClose: () => void;
  children: ReactNode;
  description?: string;
}) {
  const previousFocus = useRef(document.activeElement as HTMLElement | null),
    closeButton = useRef<HTMLButtonElement>(null);
  return (
    <Sheet
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <SheetContent
        className="import-sheet"
        side="right"
        showCloseButton={false}
        onOpenAutoFocus={(event) => {
          event.preventDefault();
          closeButton.current?.focus();
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          previousFocus.current?.focus();
        }}
      >
        <header>
          <SheetTitle>{title}</SheetTitle>
          <Button
            ref={closeButton}
            variant="ghost"
            size="icon-sm"
            aria-label="Закрыть"
            onClick={onClose}
          >
            <X size={18} />
          </Button>
        </header>
        <SheetDescription className="sr-only">
          {description}
        </SheetDescription>
        <div className="import-sheet-body">{children}</div>
      </SheetContent>
    </Sheet>
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
