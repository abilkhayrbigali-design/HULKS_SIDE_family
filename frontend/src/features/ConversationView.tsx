import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  CheckCircle2,
  ChevronRight,
  Clock3,
  FileCheck2,
  Flag,
  Play,
  RefreshCw,
  ExternalLink,
} from "lucide-react";
import {
  api,
  allPages,
  ApiError,
  errorMessage,
  logFailure,
  safeCode,
} from "../api/client";
import type {
  ChecklistDetail,
  ChecklistSummary,
  ChecklistVersion,
  ConversationDetail,
  Criterion,
  CriterionAssessment,
  Evaluation,
  Evidence,
} from "../api/types";
import {
  BackLink,
  date,
  Empty,
  ErrorBox,
  Loading,
  number,
  StatusBadge,
} from "../ui";
import { Appeals } from "./Appeals";
const roles = {
  operator: "Оператор",
  client: "Клиент",
  bot: "Бот",
  system: "Система",
};
export function evidenceIds(e: Evidence, messages: { id: string }[]) {
  if (e.kind === "message")
    return messages.some((m) => m.id === e.message_id) ? [e.message_id] : [];
  const start = messages.findIndex((m) => m.id === e.start_message_id);
  const end = messages.findIndex((m) => m.id === e.end_message_id);
  return start >= 0 && end >= start
    ? messages.slice(start, end + 1).map((m) => m.id)
    : [];
}
export function answerLabel(
  c: Pick<CriterionAssessment, "answer" | "applicability">,
  d?: Criterion,
) {
  if (c.applicability === "not_applicable") return "N/A";
  if (typeof c.answer === "boolean")
    return d?.type === "flag"
      ? c.answer
        ? "Обнаружено"
        : "Не обнаружено"
      : c.answer
        ? "Да"
        : "Нет";
  return String(c.answer ?? "—");
}
export function ConversationView({
  id,
  evaluationId,
}: {
  id: string;
  evaluationId: string | null;
}) {
  const [conversation, setConversation] = useState<ConversationDetail | null>(
    null,
  );
  const [evaluation, setEvaluation] = useState<Evaluation | null>(null);
  const [history, setHistory] = useState<Evaluation[]>([]);
  const [definitions, setDefinitions] = useState<ChecklistVersion | null>(null);
  const [checklists, setChecklists] = useState<ChecklistSummary[]>([]);
  const [checklistId, setChecklistId] = useState("");
  const [selection, setSelection] = useState<ChecklistDetail | null>(null);
  const [versionId, setVersionId] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>();
  const [actionError, setActionError] = useState<unknown>();
  const [selectionError, setSelectionError] = useState<unknown>();
  const [pollError, setPollError] = useState<unknown>();
  const [reload, setReload] = useState(0);
  const [busy, setBusy] = useState(false);
  const [highlight, setHighlight] = useState<string[]>([]);
  const [tab, setTab] = useState<"criteria" | "appeals">("criteria");
  const [appealCriterion, setAppealCriterion] = useState<string | null>(null);
  const refs = useRef<Record<string, HTMLDivElement | null>>({});
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(undefined);
    setPollError(undefined);
    setHighlight([]);
    setAppealCriterion(null);
    async function load() {
      try {
        const [runs, lists] = await Promise.all([
          allPages((offset) => api.evaluations(id, offset)),
          allPages((offset) => api.checklists(offset)),
        ]);
        const run = evaluationId
          ? await api.evaluation(evaluationId)
          : (runs[0] ?? null);
        if (run && run.conversation_id !== id)
          throw new ApiError(404, "NOT_FOUND");
        const [detail, snapshot] = await Promise.all([
          api.conversation(id, run?.transcript_version_id),
          run ? api.version(run.checklist_version_id) : Promise.resolve(null),
        ]);
        if (active) {
          setHistory(runs);
          setEvaluation(run);
          setConversation(detail);
          setDefinitions(snapshot);
          setChecklists(lists);
          setChecklistId((old) =>
            lists.some((c) => c.id === old) ? old : (lists[0]?.id ?? ""),
          );
        }
      } catch (e) {
        if (active) setError(e);
      } finally {
        if (active) setLoading(false);
      }
    }
    void load();
    return () => {
      active = false;
    };
  }, [id, evaluationId, reload]);
  useEffect(() => {
    if (!checklistId) {
      setSelection(null);
      setVersionId("");
      return;
    }
    let active = true;
    setSelection(null);
    setSelectionError(undefined);
    setVersionId("");
    api
      .checklist(checklistId)
      .then((d) => {
        if (active) {
          setSelection(d);
          setVersionId(d.current_version.id);
        }
      })
      .catch((e) => {
        if (active) setSelectionError(e);
      });
    return () => {
      active = false;
    };
  }, [checklistId, reload]);
  const polling =
    !!evaluation && ["running", "queued"].includes(evaluation.status);
  useEffect(() => {
    if (!evaluation || !polling) return;
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        const next = await api.evaluation(evaluation.id, true);
        if (active) {
          setEvaluation(next);
          setHistory((items) =>
            items.map((e) => (e.id === next.id ? next : e)),
          );
          if (["running", "queued"].includes(next.status))
            timer = setTimeout(poll, 2000);
        }
      } catch (e) {
        if (active) {
          const failure =
            e instanceof ApiError ? e : new ApiError(0, "NETWORK_ERROR");
          logFailure(failure.status, failure.code);
          setPollError(failure);
        }
      }
    };
    timer = setTimeout(poll, 2000);
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [evaluation?.id, polling, reload]);
  const showEvidence = (e: Evidence) => {
    if (!conversation) return;
    const ids = evidenceIds(e, conversation.messages);
    setHighlight(ids);
    if (ids[0])
      requestAnimationFrame(() => {
        refs.current[ids[0]]?.scrollIntoView({
          behavior: "smooth",
          block: "center",
        });
        refs.current[ids[0]]?.focus({ preventScroll: true });
      });
  };
  const start = async () => {
    if (!versionId) return;
    setBusy(true);
    setActionError(undefined);
    try {
      const result = await api.evaluate(id, versionId);
      location.hash = `/dialogues/${encodeURIComponent(id)}?evaluation=${encodeURIComponent(result.id)}`;
      if (result.id === evaluationId) setReload((v) => v + 1);
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(false);
    }
  };
  if (loading)
    return (
      <>
        <BackLink />
        <Loading />
      </>
    );
  if (error)
    return (
      <>
        <BackLink />
        <ErrorBox error={error} onRetry={() => setReload((v) => v + 1)} />
      </>
    );
  if (!conversation) return null;
  const final = evaluation?.final;
  const original = evaluation?.original;
  return (
    <>
      <BackLink />
      <section className="page-heading detail-heading">
        <div>
          <div className="eyebrow">КАРТОЧКА ДИАЛОГА</div>
          <h1>{conversation.external_id}</h1>
          <div className="detail-tags">
            <span className="language-tag">{conversation.language}</span>
            <span className="group-tag">
              {conversation.channel === "voice call" ? "Звонок" : "Чат"}
            </span>
            <span className="group-tag">{conversation.group_id}</span>
            <span className="muted">{conversation.message_count} реплик</span>
            {evaluation && <StatusBadge status={evaluation.status} />}
          </div>
        </div>
        <button className="button" onClick={() => setReload((v) => v + 1)}>
          <RefreshCw size={16} />
          Обновить
        </button>
      </section>
      <section className="panel evaluation-controls">
        <div className="evaluation-control-title">
          <span className="overview-icon">
            <FileCheck2 size={22} />
          </span>
          <div>
            <h2>Новая оценка</h2>
            <p>Будет проанализирована последняя версия транскрипта.</p>
          </div>
        </div>
        <div className="evaluation-form">
          <label className="field">
            Чек-лист
            <select
              aria-label="Чек-лист для оценки"
              value={checklistId}
              onChange={(e) => setChecklistId(e.target.value)}
              disabled={busy || !checklists.length}
            >
              <option value="" disabled>
                Выберите чек-лист
              </option>
              {checklists.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </label>
          <label className="field">
            Версия
            <select
              aria-label="Версия чек-листа для оценки"
              value={versionId}
              onChange={(e) => setVersionId(e.target.value)}
              disabled={busy || !selection}
            >
              <option value="" disabled>
                Выберите версию
              </option>
              {selection?.versions.map((v) => (
                <option key={v.id} value={v.id}>
                  v{v.version_number} · {date(v.created_at)}
                </option>
              ))}
            </select>
          </label>
          <button
            className="button primary"
            disabled={busy || !versionId || polling}
            onClick={() => void start()}
          >
            <Play size={16} />
            {busy ? "Запускаем…" : "Оценить диалог"}
          </button>
        </div>
        {!checklists.length && (
          <div className="notice">
            Сначала <a href="#/checklists">создайте чек-лист</a>.
          </div>
        )}
        {Boolean(selectionError) && (
          <ErrorBox
            error={selectionError}
            onRetry={() => setReload((v) => v + 1)}
          />
        )}
        <p className="control-note">
          OpenAI · модель задаётся на сервере через OPENAI_MODEL. Без
          настроенного ключа оценка недоступна.
        </p>
        {Boolean(actionError) && <ErrorBox error={actionError} />}
      </section>
      {evaluation?.provenance?.provider === "synthetic" && (
        <div className="warning-box" role="status">
          <strong>Синтетическая оценка · тестовые данные</strong>
          <p>
            Этот результат не подтверждает качество или выполнение реального
            AI-вызова.
          </p>
        </div>
      )}
      {evaluation && (
        <section className="score-overview">
          <div className="score-main">
            <span>Финальный итог</span>
            <strong>
              {number(final?.total)}
              <small>/ 100</small>
            </strong>
            {final?.no_applicable_reason && <p>{final.no_applicable_reason}</p>}
            <span className="score-caption">
              {evaluation.status === "completed"
                ? "С учётом решений по апелляциям"
                : evaluation.status === "failed"
                  ? "Оценка не получена"
                  : "Ожидаем результат анализа"}
            </span>
          </div>
          <div className="score-secondary">
            <span>Исходная оценка AI</span>
            <strong>
              {number(original?.total)} <small>/ 100</small>
            </strong>
            <span>
              Ревизия решения <b>{evaluation.revision}</b>
            </span>
          </div>
          <div className="score-context">
            <span>Зафиксированные правила</span>
            <strong>
              {definitions?.name ?? "Чек-лист"} · v
              {definitions?.version_number ?? "—"}
            </strong>
            <small>{date(evaluation.created_at)}</small>
            <code>Запуск {evaluation.id.slice(0, 8)}</code>
          </div>
        </section>
      )}
      {polling && (
        <div className="panel">
          <Loading
            text={
              evaluation?.status === "queued"
                ? "Диалог в очереди на анализ…"
                : "AI анализирует диалог и проверяет доказательства…"
            }
          />
        </div>
      )}
      {Boolean(pollError) && (
        <ErrorBox error={pollError} onRetry={() => setReload((v) => v + 1)} />
      )}
      {evaluation?.status === "failed" && (
        <div className="error-box" role="alert">
          <div>
            <strong>{errorMessage(evaluation.error?.code)}</strong>
            <small>
              Код: {safeCode(evaluation.error?.code)}. Ошибочный запуск сохранён
              в истории.
            </small>
            <p>
              Исправьте причину и нажмите «Оценить диалог», чтобы создать новый
              запуск.
            </p>
          </div>
        </div>
      )}
      {evaluation?.review_required && (
        <div className="warning-box">
          <strong>Нужна ручная проверка</strong>
          <ul>
            {evaluation.review_reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="dialogue-workspace">
        <section className="panel transcript-panel">
          <div className="panel-heading">
            <div>
              <h2>Транскрипт</h2>
              <p>Оценивается оператор; остальные роли дают контекст.</p>
            </div>
            <span className="badge neutral">{conversation.language}</span>
          </div>
          <div className="transcript-version">
            Версия транскрипта{" "}
            <code>{conversation.transcript_version_id.slice(0, 8)}</code>
            {conversation.transcript_version_id !==
              conversation.current_transcript_version_id && (
              <strong>Архивная версия оценки</strong>
            )}
          </div>
          {conversation.audio_url &&
            /^https?:\/\//i.test(conversation.audio_url) && (
              <div className="audio-card">
                <a
                  href={conversation.audio_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  referrerPolicy="no-referrer"
                >
                  <ExternalLink size={16} />
                  Открыть запись звонка
                </a>
                <small>
                  Оригинальная запись. Перемотка к репликам не привязана к их
                  времени.
                </small>
              </div>
            )}
          <div className="transcript-messages">
            {conversation.messages.map((m) => (
              <div
                className={`message ${m.speaker} ${highlight.includes(m.id) ? "highlight" : ""}`}
                key={m.id}
                id={`message-${m.id}`}
                ref={(node) => {
                  refs.current[m.id] = node;
                }}
                tabIndex={-1}
              >
                <div className="message-meta">
                  <strong>{roles[m.speaker]}</strong>
                  <span>
                    {m.id} <i>·</i> {m.timestamp}
                  </span>
                </div>
                <p>{m.text}</p>
              </div>
            ))}
          </div>
          {highlight.length > 0 && (
            <div className="transcript-highlight-info" role="status">
              Выделено реплик: {highlight.length}
              <button className="text-button" onClick={() => setHighlight([])}>
                Снять выделение
              </button>
            </div>
          )}
        </section>
        <section className="panel results-panel">
          <div className="result-tabs">
            <button
              className={tab === "criteria" ? "selected" : ""}
              onClick={() => setTab("criteria")}
            >
              Критерии <span>{final?.criteria.length ?? 0}</span>
            </button>
            <button
              className={tab === "appeals" ? "selected" : ""}
              onClick={() => setTab("appeals")}
            >
              Апелляции и история
            </button>
          </div>
          {tab === "criteria" ? (
            final ? (
              <>
                <div className="result-intro">
                  <span>
                    <CheckCircle2 size={16} />
                    Проверенные доказательства
                  </span>
                  <small>
                    N/A перераспределяет веса; флаги отображаются отдельно.
                  </small>
                </div>
                {final.gross_error === true && (
                  <div className="warning-box">
                    <Flag size={17} />
                    <strong>Обнаружена грубая ошибка</strong>
                    <p>Флаг не обнуляет балл автоматически.</p>
                  </div>
                )}
                {final.criteria.map((c, index) => (
                  <CriterionCard
                    key={c.criterion_id}
                    result={c}
                    definition={definitions?.criteria.find(
                      (d) => d.id === c.criterion_id,
                    )}
                    original={original?.criteria.find(
                      (d) => d.criterion_id === c.criterion_id,
                    )}
                    index={index}
                    onEvidence={showEvidence}
                    onAppeal={() => {
                      setAppealCriterion(c.criterion_id);
                      setTab("appeals");
                    }}
                  />
                ))}
                {final.sections.length > 0 && (
                  <div className="section-scores">
                    <h3>Итоги по разделам</h3>
                    {final.sections.map((s, i) => (
                      <div key={i}>
                        <span>{s.name}</span>
                        <strong>{number(s.total)}</strong>
                      </div>
                    ))}
                  </div>
                )}
              </>
            ) : (
              <Empty
                title={polling ? "Анализ выполняется" : "Здесь появится оценка"}
                text="Каждый критерий будет сопровождаться объяснением и ссылкой на исходную реплику."
              />
            )
          ) : evaluation?.status === "completed" && definitions ? (
            <Appeals
              key={evaluation.id}
              evaluation={evaluation}
              definitions={definitions}
              messages={conversation.messages}
              initialCriterion={appealCriterion}
              onEvidence={showEvidence}
              onUpdated={(next) => {
                setEvaluation(next);
                setHistory((items) =>
                  items.map((e) => (e.id === next.id ? next : e)),
                );
                setAppealCriterion(null);
              }}
            />
          ) : (
            <Empty
              title="Апелляции появятся после оценки"
              text="Можно оспорить любой критерий завершённого анализа."
            />
          )}
        </section>
      </div>
      {evaluation?.provenance && (
        <section className="panel provenance">
          <div>
            <h3>Параметры анализа</h3>
            <p>
              {evaluation.provenance.provider} ·{" "}
              {evaluation.provenance.model_reported ??
                evaluation.provenance.model_requested}{" "}
              · промпт {evaluation.provenance.prompt_version}
            </p>
          </div>
          <div>
            <span>
              Длительность
              <strong>
                {number(evaluation.provenance.duration_ms / 1000)} с
              </strong>
            </span>
            <span>
              Запросы
              <strong>{evaluation.provenance.usage.request_count}</strong>
            </span>
            <span>
              Токены
              <strong>
                {evaluation.provenance.usage.total_tokens ?? "Неизвестно"}
              </strong>
            </span>
            <span>
              Стоимость
              <strong>
                {evaluation.provenance.estimated_cost_usd == null
                  ? "Не рассчитана"
                  : `$${evaluation.provenance.estimated_cost_usd.toFixed(4)}`}
              </strong>
            </span>
          </div>
        </section>
      )}
      {history.length > 0 && (
        <section className="panel run-history">
          <div className="panel-heading">
            <div>
              <h2>История запусков</h2>
              <p>Каждый запуск хранит собственные версии и исходную оценку.</p>
            </div>
            <Clock3 size={20} />
          </div>
          {history.map((run) => (
            <a
              key={run.id}
              className={`history-row ${run.id === evaluation?.id ? "selected" : ""}`}
              href={`#/dialogues/${encodeURIComponent(id)}?evaluation=${encodeURIComponent(run.id)}`}
            >
              <span>
                {date(run.created_at)}
                <code>{run.id.slice(0, 8)}</code>
              </span>
              <StatusBadge status={run.status} />
              <strong>
                {number(run.final?.total)} <small>/ 100</small>
              </strong>
              <ChevronRight size={17} />
            </a>
          ))}
        </section>
      )}
    </>
  );
}
function CriterionCard({
  result: c,
  definition: d,
  original,
  index,
  onEvidence,
  onAppeal,
}: {
  result: CriterionAssessment;
  definition?: Criterion;
  original?: CriterionAssessment;
  index: number;
  onEvidence: (e: Evidence) => void;
  onAppeal: () => void;
}) {
  const isFlag = d?.type === "flag";
  const changed =
    original &&
    (original.answer !== c.answer ||
      original.applicability !== c.applicability ||
      original.explanation !== c.explanation);
  return (
    <article className="criterion-result">
      <div className="criterion-result-heading">
        <span className="criterion-index">
          {String(index + 1).padStart(2, "0")}
        </span>
        <div>
          <small>{d?.section ?? "Критерий"}</small>
          <h3>{d?.name ?? c.criterion_id}</h3>
        </div>
        <span
          className={`answer-badge ${c.applicability === "not_applicable" ? "na" : isFlag ? (c.answer ? "negative" : "positive") : c.answer === false || c.answer === 0 ? "negative" : "positive"}`}
        >
          {answerLabel(c, d)}
        </span>
      </div>
      <p>{c.explanation}</p>
      {changed && (
        <div className="changed-line">
          Решение изменено · исходный ответ: {answerLabel(original, d)}
        </div>
      )}
      <div className="criterion-points">
        {isFlag ? (
          <span>
            <Flag size={14} />
            Отдельный флаг · вес 0
          </span>
        ) : (
          <>
            <span>
              Вклад{" "}
              <strong>
                {number(c.effective_points)} / {number(c.effective_weight)}
              </strong>
            </span>
            <span>Исходный вес {number(c.weight)}</span>
          </>
        )}
      </div>
      {c.review_required && (
        <div className="criterion-review">
          Ручная проверка: {c.review_reasons.join("; ")}
        </div>
      )}
      <div className="evidence-list">
        {c.evidence.map((e, i) => (
          <button
            className="evidence-button"
            key={i}
            onClick={() => onEvidence(e)}
          >
            <ArrowUpRight size={14} />
            {e.kind === "message"
              ? e.message_id
              : `${e.start_message_id}–${e.end_message_id}`}
          </button>
        ))}
        <button className="text-button appeal-button" onClick={onAppeal}>
          Оспорить
        </button>
      </div>
    </article>
  );
}
