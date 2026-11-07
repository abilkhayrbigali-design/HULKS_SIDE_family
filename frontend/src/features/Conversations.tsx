import { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  MessageSquare,
  Phone,
  Plus,
  Search,
  Upload,
  X,
  RefreshCw,
  ListFilter,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { Button } from "../components/ui/button";
import { ScrollArea } from "../components/ui/scroll-area";
import { useWorkspace } from "../workspace/context";
import { api, logFailure } from "../api/client";
import type {
  Conversation,
  ImportSummary,
  OrganizerRecord,
  Page,
} from "../api/types";
import { Empty, ErrorBox, Loading, Modal, StatusBadge, number } from "../ui";
const synthetic: OrganizerRecord[] = [
  {
    conversation_id: "учебный-ru-001",
    language: "RU",
    channel: "agent chat",
    audio_url: null,
    transcript: [
      {
        timestamp: "00:01",
        speaker: "client",
        text: "Здравствуйте! Где скачать отчёт по счёту?",
      },
      {
        timestamp: "00:04",
        speaker: "operator",
        text: "Здравствуйте! Меня зовут Алия. Откройте личный кабинет → Документы → Отчёт по счёту, выберите период и нажмите «Скачать».",
      },
      { timestamp: "00:13", speaker: "client", text: "Спасибо, получилось." },
      {
        timestamp: "00:16",
        speaker: "operator",
        text: "Рада помочь! Если появятся вопросы, напишите нам. До свидания!",
      },
    ],
  },
];
export function normalizeImport(value: unknown): OrganizerRecord[] {
  const payload = value as { records?: unknown; data?: { records?: unknown } };
  const records = Array.isArray(value)
    ? value
    : (payload?.records ?? payload?.data?.records);
  if (!Array.isArray(records) || records.length === 0)
    throw new Error(
      "В JSON нужен непустой массив диалогов, объект records или data.records.",
    );
  return records as OrganizerRecord[];
}
export function Conversations({ selectedId }: { selectedId: string | null }) {
  const workspace = useWorkspace();
  const [page, setPage] = useState<Page<Conversation> | null>(null),
    [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true),
    [language, setLanguage] = useState(""),
    [channel, setChannel] = useState(""),
    [group, setGroup] = useState(""),
    [search, setSearch] = useState(""),
    [offset, setOffset] = useState(0),
    [reload, setReload] = useState(0),
    [importOpen, setImportOpen] = useState(false),
    [summary, setSummary] = useState<ImportSummary | null>(null),
    [filters, setFilters] = useState(false);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(undefined);
    const query = new URLSearchParams({ limit: "25", offset: String(offset) });
    if (language) query.set("language", language);
    if (channel) query.set("channel", channel);
    if (group.trim()) query.set("group_id", group.trim());
    api
      .conversations(query.toString())
      .then((result) => {
        if (active) setPage(result);
      })
      .catch((e) => {
        if (active) setError(e);
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [language, channel, group, offset, reload, workspace.queueRevision]);
  const filtered =
    page?.items.filter((c) =>
      c.external_id.toLowerCase().includes(search.toLowerCase()),
    ) ?? [];
  const selectNext = (
    event: React.KeyboardEvent<HTMLAnchorElement>,
    index: number,
  ) => {
    if (!["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next =
      event.key === "Home"
        ? 0
        : event.key === "End"
          ? filtered.length - 1
          : Math.max(
              0,
              Math.min(
                filtered.length - 1,
                index + (event.key === "ArrowDown" ? 1 : -1),
              ),
            );
    const target = document.getElementById(`queue-item-${filtered[next]?.id}`);
    target?.focus();
    if (filtered[next])
      location.hash = `/dialogues/${encodeURIComponent(filtered[next].id)}`;
  };
  return (
    <section className="queue-content" aria-label="Очередь диалогов">
      <header className="pane-heading queue-heading">
        <div>
          <h1>
            Очередь <span className="heading-count">{page?.total ?? "—"}</span>
          </h1>
          <p>Диалоги для оценки</p>
        </div>
        <div className="queue-tools">
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Обновить очередь"
            onClick={() => setReload((v) => v + 1)}
          >
            <RefreshCw size={15} />
          </Button>
          <Button
            variant="default"
            size="icon-sm"
            aria-label="Импортировать диалоги"
            onClick={() => setImportOpen(true)}
          >
            <Plus size={17} />
          </Button>
        </div>
      </header>
      <div className="queue-filters">
        <label className="search-field">
          <Search size={15} />
          <input
            aria-label="Поиск ID на странице"
            placeholder="Найти диалог на странице"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <kbd>/</kbd>
        </label>
        <div className="queue-filter-row">
          <label>
            <span className="sr-only">Язык</span>
            <select
              aria-label="Язык"
              value={language}
              onChange={(e) => {
                setLanguage(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">Все языки</option>
              {["RU", "KZ", "EN"].map((v) => (
                <option key={v}>{v}</option>
              ))}
            </select>
          </label>
          <Button
            variant="outline"
            size="sm"
            aria-pressed={filters}
            onClick={() => setFilters(!filters)}
          >
            <ListFilter size={14} />
            Фильтры{(channel || group) && <span className="filter-dot" />}
          </Button>
        </div>
        {filters && (
          <div className="queue-extra-filters">
            <label className="field">
              Канал
              <select
                aria-label="Канал"
                value={channel}
                onChange={(e) => {
                  setChannel(e.target.value);
                  setOffset(0);
                }}
              >
                <option value="">Все каналы</option>
                <option value="agent chat">Чат</option>
                <option value="voice call">Звонок</option>
              </select>
            </label>
            <label className="field">
              Группа
              <input
                aria-label="Группа"
                value={group}
                placeholder="Все группы"
                onChange={(e) => {
                  setGroup(e.target.value);
                  setOffset(0);
                }}
              />
            </label>
          </div>
        )}
      </div>
      {summary && (
        <div className="success-box" role="status">
          <div>
            <strong>Импорт завершён · {summary.received}</strong>
            <span>
              Новых {summary.created} · версий {summary.new_versions} · без
              изменений {summary.unchanged}
            </span>
          </div>
          <button
            className="icon-button"
            aria-label="Скрыть результат импорта"
            onClick={() => setSummary(null)}
          >
            <X size={15} />
          </button>
        </div>
      )}
      <ScrollArea className="queue-scroll" aria-label="Список диалогов">
        {loading ? (
          <Loading />
        ) : error ? (
          <ErrorBox error={error} onRetry={() => setReload((v) => v + 1)} />
        ) : filtered.length === 0 ? (
          <Empty
            title={page?.total ? "Ничего не найдено" : "Первый диалог"}
            text={
              page?.total
                ? "Измените фильтры или поиск."
                : "Импортируйте группу или JSON с транскриптами."
            }
          >
            <Button size="sm" onClick={() => setImportOpen(true)}>
              <Upload size={15} />
              Импортировать
            </Button>
          </Empty>
        ) : (
          <div className="queue-list">
            {filtered.map((c, index) => (
              <a
                className={`queue-item ${c.id === selectedId ? "is-selected" : ""}`}
                aria-current={c.id === selectedId ? "page" : undefined}
                href={`#/dialogues/${encodeURIComponent(c.id)}`}
                id={`queue-item-${c.id}`}
                key={c.id}
                onKeyDown={(event) => selectNext(event, index)}
              >
                <div className="queue-item-top">
                  <span className="queue-channel">
                    {c.channel === "voice call" ? (
                      <Phone size={14} />
                    ) : (
                      <MessageSquare size={14} />
                    )}
                    <span>{c.external_id}</span>
                  </span>
                  <span className="language-tag">{c.language}</span>
                </div>
                <div className="queue-item-summary">
                  <span>
                    {c.message_count} реплик · {c.group_id}
                  </span>
                  <span>
                    {c.latest_evaluation
                      ? number(c.latest_evaluation.final_total)
                      : "—"}
                  </span>
                </div>
                <div className="queue-item-bottom">
                  {c.latest_evaluation ? (
                    <StatusBadge status={c.latest_evaluation.status} />
                  ) : (
                    <span className="badge neutral">Не оценён</span>
                  )}
                  <span>{c.source === "dataset" ? "Набор" : "JSON"}</span>
                </div>
              </a>
            ))}
          </div>
        )}
      </ScrollArea>
      <footer className="queue-pagination">
        <span>
          {page?.total
            ? `${offset + 1}–${Math.min(offset + (page?.items.length ?? 0), page.total)} / ${page.total}`
            : "0 диалогов"}
        </span>
        <div>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Предыдущая страница"
            disabled={offset === 0}
            onClick={() => setOffset(Math.max(0, offset - 25))}
          >
            <ChevronLeft size={16} />
          </Button>
          <Button
            variant="ghost"
            size="icon-sm"
            aria-label="Следующая страница"
            disabled={offset + 25 >= (page?.total ?? 0)}
            onClick={() => setOffset(offset + 25)}
          >
            <ChevronRight size={16} />
          </Button>
        </div>
      </footer>
      {importOpen && (
        <ImportDialog
          onClose={() => setImportOpen(false)}
          onImported={(result) => {
            setSummary(result);
            setImportOpen(false);
            setOffset(0);
            setReload((v) => v + 1);
            workspace.refreshQueue();
          }}
        />
      )}
    </section>
  );
}
function ImportDialog({
  onClose,
  onImported,
}: {
  onClose: () => void;
  onImported: (s: ImportSummary) => void;
}) {
  const [tab, setTab] = useState<"group" | "file">("group");
  const [group, setGroup] = useState("DEV");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const file = useRef<HTMLInputElement>(null);
  const run = async (operation: () => Promise<ImportSummary>) => {
    setBusy(true);
    setError(undefined);
    try {
      onImported(await operation());
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <Modal
      title="Импорт диалогов"
      onClose={() => {
        if (!busy) onClose();
      }}
    >
      <div className="tabs">
        <button
          className={tab === "group" ? "selected" : ""}
          onClick={() => setTab("group")}
        >
          Набор по группе
        </button>
        <button
          className={tab === "file" ? "selected" : ""}
          onClick={() => setTab("file")}
        >
          JSON-файл
        </button>
      </div>
      {tab === "group" ? (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void run(() => api.importDataset(group.trim()));
          }}
        >
          <p className="muted">
            Источник и секретная ссылка настроены на сервере. Можно указать DEV
            или другую доступную группу.
          </p>
          <label className="field">
            ID группы
            <input
              autoFocus
              required
              maxLength={200}
              value={group}
              onChange={(e) => setGroup(e.target.value)}
            />
          </label>
          <button disabled={busy || !group.trim()} className="button primary">
            <ArrowDownToLine size={17} />
            {busy ? "Импортируем…" : "Получить набор"}
          </button>
        </form>
      ) : (
        <div>
          <p className="muted">
            Массив диалогов или объект с records / data.records. Весь файл
            проверяется до сохранения.
          </p>
          <input
            ref={file}
            type="file"
            accept="application/json,.json"
            aria-label="Выбрать JSON-файл"
            disabled={busy}
            onChange={async (e) => {
              const selected = e.target.files?.[0];
              if (!selected) return;
              setError(undefined);
              if (selected.size > 20 * 1024 * 1024) {
                setError(new Error("Выберите JSON-файл размером до 20 МБ."));
                logFailure(422, "VALIDATION_ERROR");
                return;
              }
              await run(async () => {
                let parsed: unknown;
                try {
                  parsed = JSON.parse(await selected.text());
                } catch {
                  logFailure(422, "VALIDATION_ERROR");
                  throw new Error(
                    "Не удалось прочитать JSON. Проверьте синтаксис файла.",
                  );
                }
                let records: OrganizerRecord[];
                try {
                  records = normalizeImport(parsed);
                } catch {
                  logFailure(422, "VALIDATION_ERROR");
                  throw new Error(
                    "В JSON нужен непустой массив диалогов, records или data.records.",
                  );
                }
                return api.importRecords(records);
              });
            }}
          />
          <div className="synthetic-box">
            <strong>Нужен пример формата?</strong>
            <p>
              Учебная синтетическая переписка. Она импортируется как обычный
              диалог и не содержит готовых оценок.
            </p>
            <button
              className="button small"
              disabled={busy}
              onClick={() => void run(() => api.importRecords(synthetic))}
            >
              Загрузить учебный пример
            </button>
          </div>
        </div>
      )}
      {Boolean(error) && <ErrorBox error={error} />}
      <div className="modal-footer">
        <button className="button subtle" disabled={busy} onClick={onClose}>
          Закрыть
        </button>
        <span>RU · KZ · EN / чаты и звонки</span>
      </div>
    </Modal>
  );
}
