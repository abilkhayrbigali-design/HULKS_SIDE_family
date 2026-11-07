import { useEffect, useRef, useState } from "react";
import {
  ArrowDownToLine,
  ArrowRight,
  FileJson,
  MessageSquare,
  Phone,
  Plus,
  Search,
  Upload,
  X,
} from "lucide-react";
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
export function Conversations() {
  const [page, setPage] = useState<Page<Conversation> | null>(null);
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const [language, setLanguage] = useState("");
  const [channel, setChannel] = useState("");
  const [group, setGroup] = useState("");
  const [search, setSearch] = useState("");
  const [offset, setOffset] = useState(0);
  const [reload, setReload] = useState(0);
  const [importOpen, setImportOpen] = useState(false);
  const [summary, setSummary] = useState<ImportSummary | null>(null);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(undefined);
    const q = new URLSearchParams({ limit: "25", offset: String(offset) });
    if (language) q.set("language", language);
    if (channel) q.set("channel", channel);
    if (group.trim()) q.set("group_id", group.trim());
    api
      .conversations(q.toString())
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
  }, [language, channel, group, offset, reload]);
  const filtered =
    page?.items.filter((c) =>
      c.external_id.toLowerCase().includes(search.toLowerCase()),
    ) ?? [];
  return (
    <>
      <section className="page-heading">
        <div>
          <div className="eyebrow">КАЧЕСТВО КЛИЕНТСКОГО ОПЫТА</div>
          <h1>
            Диалоги <span className="heading-count">{page?.total ?? "—"}</span>
          </h1>
          <p>От реплики к решению. Анализируйте диалоги по вашим правилам.</p>
        </div>
        <button className="button primary" onClick={() => setImportOpen(true)}>
          <Plus size={18} />
          Импортировать диалоги
        </button>
      </section>
      <section
        className="overview-grid"
        aria-label="Информация о рабочем процессе"
      >
        <div className="overview-card">
          <div className="overview-icon">
            <MessageSquare size={20} />
          </div>
          <div>
            <span>Доступно в выборке</span>
            <strong>
              {page?.total ?? "—"} <small>диалогов</small>
            </strong>
          </div>
        </div>
        <div className="overview-card">
          <div className="overview-icon pale">
            <FileJson size={20} />
          </div>
          <div>
            <span>Чаты и звонки</span>
            <strong>
              RU <i>·</i> KZ <i>·</i> EN
            </strong>
          </div>
        </div>
        <div className="overview-card feature">
          <div>
            <span>Проверяемые решения</span>
            <strong>Оценка + доказательства</strong>
            <small>Неизменяемые версии и история апелляций</small>
          </div>
          <ArrowRight size={22} />
        </div>
      </section>
      {summary && (
        <div className="success-box" role="status">
          <div>
            <strong>Импорт завершён · {summary.received} диалогов</strong>
            <span>
              Новых: {summary.created} · Новых версий: {summary.new_versions} ·
              Без изменений: {summary.unchanged}
            </span>
          </div>
          <button
            className="icon-button"
            aria-label="Скрыть результат импорта"
            onClick={() => setSummary(null)}
          >
            <X size={17} />
          </button>
        </div>
      )}
      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>Все диалоги</h2>
            <p>Выберите диалог, чтобы изучить переписку и запустить оценку.</p>
          </div>
          <button
            className="button subtle small"
            onClick={() => setReload((v) => v + 1)}
          >
            Обновить
          </button>
        </div>
        <div className="filters">
          <label className="search-field">
            <Search size={17} />
            <input
              aria-label="Поиск ID на странице"
              placeholder="Поиск по ID на странице"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
            />
          </label>
          <label className="filter-field">
            <span>Язык</span>
            <select
              aria-label="Язык"
              value={language}
              onChange={(e) => {
                setLanguage(e.target.value);
                setOffset(0);
              }}
            >
              <option value="">Все языки</option>
              {["RU", "KZ", "EN"].map((x) => (
                <option key={x}>{x}</option>
              ))}
            </select>
          </label>
          <label className="filter-field">
            <span>Канал</span>
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
          <label className="filter-field">
            <span>Группа</span>
            <input
              aria-label="Группа"
              placeholder="Все группы"
              value={group}
              onChange={(e) => {
                setGroup(e.target.value);
                setOffset(0);
              }}
            />
          </label>
        </div>
        {loading ? (
          <Loading />
        ) : error ? (
          <ErrorBox error={error} onRetry={() => setReload((v) => v + 1)} />
        ) : filtered.length === 0 ? (
          <Empty
            title={
              page?.total
                ? "По этим условиям ничего нет"
                : "Начните с первого диалога"
            }
            text={
              page?.total
                ? "Измените фильтры или строку поиска."
                : "Импортируйте набор по группе или загрузите JSON с транскриптами."
            }
          >
            <button
              className="button primary"
              onClick={() => setImportOpen(true)}
            >
              <Upload size={17} />
              Импортировать
            </button>
          </Empty>
        ) : (
          <>
            <div className="table-scroll">
              <table className="conversations-table">
                <thead>
                  <tr>
                    <th>ДИАЛОГ</th>
                    <th>КАНАЛ / ЯЗЫК</th>
                    <th>ГРУППА</th>
                    <th>СТАТУС</th>
                    <th>ИТОГ</th>
                    <th>
                      <span className="sr-only">Открыть</span>
                    </th>
                  </tr>
                </thead>
                <tbody>
                  {filtered.map((c) => (
                    <tr key={c.id}>
                      <td>
                        <a
                          href={`#/dialogues/${encodeURIComponent(c.id)}`}
                          className="conversation-title"
                        >
                          {c.external_id}
                        </a>
                        <small>
                          {c.message_count} реплик ·{" "}
                          {c.source === "dataset"
                            ? "Набор данных"
                            : "Загружен JSON"}
                        </small>
                      </td>
                      <td>
                        <div className="channel">
                          {c.channel === "voice call" ? (
                            <Phone size={15} />
                          ) : (
                            <MessageSquare size={15} />
                          )}{" "}
                          {c.channel === "voice call" ? "Звонок" : "Чат"}
                          <span className="language-tag">{c.language}</span>
                        </div>
                      </td>
                      <td>
                        <span className="group-tag">{c.group_id}</span>
                      </td>
                      <td>
                        {c.latest_evaluation ? (
                          <StatusBadge status={c.latest_evaluation.status} />
                        ) : (
                          <span className="badge neutral">Не оценён</span>
                        )}
                      </td>
                      <td>
                        <strong className="score-cell">
                          {number(c.latest_evaluation?.final_total)}
                          <small>/ 100</small>
                        </strong>
                      </td>
                      <td>
                        <a
                          className="icon-link"
                          aria-label={`Открыть ${c.external_id}`}
                          href={`#/dialogues/${encodeURIComponent(c.id)}`}
                        >
                          <ArrowRight size={18} />
                        </a>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="pagination">
              <span>
                {offset + 1}–
                {Math.min(offset + (page?.items.length ?? 0), page?.total ?? 0)}{" "}
                из {page?.total}
              </span>
              <div>
                <button
                  className="button small"
                  disabled={offset === 0}
                  onClick={() => setOffset(Math.max(0, offset - 25))}
                >
                  Назад
                </button>
                <button
                  className="button small"
                  disabled={offset + 25 >= (page?.total ?? 0)}
                  onClick={() => setOffset(offset + 25)}
                >
                  Далее
                </button>
              </div>
            </div>
          </>
        )}
      </section>
      <div className="hint-line">
        <span className="mini-dot" />
        Баллы рассчитываются на сервере по выбранной версии чек-листа. N/A
        исключается из применимых весов.
      </div>
      {importOpen && (
        <ImportDialog
          onClose={() => setImportOpen(false)}
          onImported={(result) => {
            setSummary(result);
            setImportOpen(false);
            setOffset(0);
            setReload((v) => v + 1);
          }}
        />
      )}
    </>
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
