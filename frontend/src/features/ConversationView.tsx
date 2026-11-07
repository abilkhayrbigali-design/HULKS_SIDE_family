import { useEffect, useRef, useState } from "react";
import {
  ArrowUpRight,
  ChevronRight,
  Clock3,
  Flag,
  Play,
  RefreshCw,
  ShieldCheck,
  PanelRightClose,
  LockKeyhole,
  Headphones,
  Headset,
  UserRound,
  Bot,
  Settings2,
  Quote,
  FlaskConical,
  Sparkles,
  ChevronDown,
  LoaderCircle,
  AlertCircle,
  Minus,
  CircleX,
  CircleCheck,
  MessageSquarePlus,
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
import { date, Empty, ErrorBox, Loading, number, StatusBadge } from "../ui";
import { Appeals } from "./Appeals";
import { Button } from "../components/ui/button";
import { ScrollArea } from "../components/ui/scroll-area";
import { ResizableHandle, ResizablePanel } from "../components/ui/resizable";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/ui/tabs";
import { useWorkspace } from "../workspace/context";
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
  const workspace = useWorkspace();
  const transcriptRoot = useRef<HTMLDivElement>(null);
  const transcriptScroll = useRef(0);
  const [focusedCriterion, setFocusedCriterion] = useState<string | null>(null);
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
  const [tab, setTab] = useState<"criteria" | "appeals" | "runs">("criteria");
  const [appealCriterion, setAppealCriterion] = useState<string | null>(null);
  const refs = useRef<Record<string, HTMLDivElement | null>>({});
  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(undefined);
    setPollError(undefined);
    setHighlight([]);
    setFocusedCriterion(null);
    transcriptScroll.current = 0;
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
    if (!evaluation || !polling || evaluation.conversation_id !== id) return;
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
  }, [id, evaluationId, evaluation?.id, polling, reload]);
  useEffect(() => {
    requestAnimationFrame(() => {
      const viewport = transcriptRoot.current?.querySelector<HTMLElement>(
        '[data-slot="scroll-area-viewport"]',
      );
      if (viewport) viewport.scrollTop = transcriptScroll.current;
    });
  }, [workspace.activePane, workspace.narrow]);
  const showEvidence = (evidence: Evidence) => {
    if (!conversation) return;
    const ids = evidenceIds(evidence, conversation.messages);
    setHighlight(ids);
    if (workspace.narrow) workspace.setActivePane("transcript");
    requestAnimationFrame(() => {
      const viewport = transcriptRoot.current?.querySelector<HTMLElement>(
        '[data-slot="scroll-area-viewport"]',
      );
      const target = refs.current[ids[0]];
      if (viewport && target) {
        const top =
          target.getBoundingClientRect().top -
          viewport.getBoundingClientRect().top +
          viewport.scrollTop -
          viewport.clientHeight / 2 +
          target.clientHeight / 2;
        viewport.scrollTo({
          top: Math.max(0, top),
          behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "auto"
            : "smooth",
        });
        target.focus({ preventScroll: true });
      }
    });
  };
  const start = async () => {
    if (!versionId) return;
    setBusy(true);
    setActionError(undefined);
    try {
      const result = await api.evaluate(id, versionId);
      location.hash = `/dialogues/${encodeURIComponent(id)}?evaluation=${encodeURIComponent(result.id)}`;
      workspace.refreshQueue();
      if (result.id === evaluationId) setReload((v) => v + 1);
    } catch (e) {
      setActionError(e);
    } finally {
      setBusy(false);
    }
  };
  const ready = !loading && conversation?.id === id;
  const final = ready ? evaluation?.final : null;
  const original = ready ? evaluation?.original : null;
  const criterion =
    final?.criteria.find((c) => c.criterion_id === focusedCriterion) ??
    final?.criteria[0];
  const definition = definitions?.criteria.find(
    (c) => c.id === criterion?.criterion_id,
  );
  const chooseCriterion = (result: CriterionAssessment) => {
    setFocusedCriterion(result.criterion_id);
    showEvidence(result.evidence[0]);
  };
  const assessmentChanged = (next: Evaluation) => {
    setEvaluation(next);
    setHistory((items) =>
      items.map((item) => (item.id === next.id ? next : item)),
    );
    setAppealCriterion(null);
    workspace.refreshQueue();
  };
  const tabs = (
    <TabsList className="result-tabs" variant="line">
      <TabsTrigger value="criteria">
        Критерии{" "}
        <span className="tab-count">{final?.criteria.length ?? 0}</span>
      </TabsTrigger>
      <TabsTrigger value="appeals">Апелляции и история</TabsTrigger>
      <TabsTrigger value="runs">Запуски</TabsTrigger>
    </TabsList>
  );
  return (
    <>
      <ResizablePanel
        id="transcript-panel"
        className="workspace-panel transcript-panel"
        defaultSize="50.6%"
        minSize={workspace.narrow ? 0 : 320}
      >
        <section className="transcript-content" aria-label="Транскрипт диалога">
          <header className="pane-heading transcript-heading">
            <div>
              <div className="pane-eyebrow">
                ДИАЛОГ / {ready ? conversation.language : "…"}
              </div>
              <h1>{ready ? conversation.external_id : "Загрузка диалога"}</h1>
            </div>
            <div className="transcript-heading-actions">
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Обновить диалог"
                onClick={() => setReload((v) => v + 1)}
              >
                <RefreshCw size={15} />
              </Button>
              <Button
                variant="ghost"
                size="icon-sm"
                aria-label="Открыть качество диалога"
                onClick={() => workspace.setActivePane("quality")}
              >
                <ShieldCheck size={16} />
              </Button>
            </div>
          </header>
          {ready && (
            <div className="transcript-metadata">
              <span className="group-tag">
                {conversation.channel === "voice call" ? "Звонок" : "Чат"}
              </span>
              <span>{conversation.message_count} реплик</span>
              <span>{conversation.group_id}</span>
              {evaluation && <StatusBadge status={evaluation.status} />}
            </div>
          )}
          {ready && (
            <div className="transcript-version">
              <LockKeyhole size={12} />
              <span>Версия транскрипта</span>
              <code>{conversation.transcript_version_id.slice(0, 8)}</code>
              {conversation.transcript_version_id !==
                conversation.current_transcript_version_id && (
                <span className="archive-label">Архивная версия оценки</span>
              )}
            </div>
          )}
          {ready &&
            conversation.audio_url &&
            /^https?:\/\//i.test(conversation.audio_url) && (
              <div className="audio-card">
                <a
                  href={conversation.audio_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  referrerPolicy="no-referrer"
                >
                  <Headphones size={15} />
                  Открыть запись звонка
                  <ExternalLink size={12} />
                </a>
                <small>
                  Оригинальная запись · время реплик не привязано к перемотке.
                </small>
              </div>
            )}
          <ScrollArea
            className="transcript-scroll"
            ref={transcriptRoot}
            onScrollCapture={(event) => {
              const target = event.target as HTMLElement;
              if (target.dataset.slot === "scroll-area-viewport")
                transcriptScroll.current = target.scrollTop;
            }}
          >
            {loading || !ready ? (
              error ? (
                <ErrorBox
                  error={error}
                  onRetry={() => setReload((v) => v + 1)}
                />
              ) : (
                <Loading />
              )
            ) : (
              <div className="transcript-messages">
                {conversation.messages.map((message) => (
                  <div
                    className={`message ${message.speaker} ${highlight.includes(message.id) ? "highlight" : ""}`}
                    key={message.id}
                    id={`message-${message.id}`}
                    ref={(node) => {
                      refs.current[message.id] = node;
                    }}
                    tabIndex={-1}
                  >
                    <div className="message-avatar" aria-hidden="true">
                      {message.speaker === "operator" ? (
                        <Headset size={15} />
                      ) : message.speaker === "client" ? (
                        <UserRound size={15} />
                      ) : message.speaker === "bot" ? (
                        <Bot size={15} />
                      ) : (
                        <Settings2 size={15} />
                      )}
                    </div>
                    <div className="message-body">
                      <div className="message-meta">
                        <strong>{roles[message.speaker]}</strong>
                        <code>{message.id}</code>
                        <time>{message.timestamp}</time>
                      </div>
                      <p>{message.text}</p>
                      {highlight.includes(message.id) && (
                        <span className="evidence-marker">
                          <Quote size={11} />
                          Доказательство
                        </span>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
          <footer className="transcript-status">
            <span>
              <ShieldCheck size={13} />
              {highlight.length
                ? `Выделено реплик: ${highlight.length}`
                : "Оценивается оператор · все роли сохранены как контекст"}
            </span>
            {highlight.length > 0 && (
              <button className="text-button" onClick={() => setHighlight([])}>
                Снять выделение
              </button>
            )}
          </footer>
        </section>
      </ResizablePanel>
      <ResizableHandle
        aria-label="Изменить ширину оценки"
        className="workspace-handle"
      />
      <ResizablePanel
        id="quality-panel"
        className="workspace-panel quality-panel"
        defaultSize="30.4%"
        minSize={workspace.narrow ? 0 : 300}
        maxSize="43%"
        collapsible
        collapsedSize="0%"
        panelRef={workspace.qualityRef}
      >
        <section className="quality-content" aria-label="Оценка и решения">
          <header className="pane-heading quality-heading">
            <h2>
              <ShieldCheck size={17} />
              Качество диалога
            </h2>
            <Button
              variant="ghost"
              size="icon-sm"
              aria-label="Свернуть оценку"
              onClick={workspace.toggleQuality}
            >
              <PanelRightClose size={16} />
            </Button>
          </header>
          {!ready ? (
            <Loading />
          ) : (
            <>
              {evaluation?.provenance?.provider === "synthetic" && (
                <div className="synthetic-banner" role="status">
                  <FlaskConical size={14} />
                  <span>Синтетическая оценка · тестовые данные</span>
                </div>
              )}
              <div className="score-overview">
                <div className="score-secondary">
                  <span>Исходная оценка AI</span>
                  <strong>
                    {number(original?.total)}
                    <small>/100</small>
                  </strong>
                </div>
                <div className="score-main">
                  <span>Финальный итог</span>
                  <strong>
                    {number(final?.total)}
                    <small>/100</small>
                  </strong>
                </div>
                <div className="score-revision">
                  <span>
                    Решения проверяющего · ревизия {evaluation?.revision ?? 0}
                  </span>
                  <code>
                    {definitions
                      ? `Чек-лист v${definitions.version_number}`
                      : "Правила не выбраны"}
                  </code>
                </div>
              </div>
              {final?.no_applicable_reason && (
                <div className="notice">{final.no_applicable_reason}</div>
              )}
              <details
                className="evaluation-controls"
                open={!evaluation || evaluation.status === "failed"}
              >
                <summary>
                  <Sparkles size={14} />
                  {evaluation?.status === "failed"
                    ? "Повторить анализ"
                    : "Настроить новый анализ"}
                  <ChevronDown size={14} />
                </summary>
                <div className="evaluation-form">
                  <label className="field">
                    Чек-лист
                    <select
                      aria-label="Чек-лист для оценки"
                      value={checklistId}
                      onChange={(event) => setChecklistId(event.target.value)}
                      disabled={busy || !checklists.length}
                    >
                      <option value="" disabled>
                        Выберите чек-лист
                      </option>
                      {checklists.map((checklist) => (
                        <option key={checklist.id} value={checklist.id}>
                          {checklist.name}
                        </option>
                      ))}
                    </select>
                  </label>
                  <label className="field">
                    Версия
                    <select
                      aria-label="Версия чек-листа для оценки"
                      value={versionId}
                      onChange={(event) => setVersionId(event.target.value)}
                      disabled={busy || !selection}
                    >
                      <option value="" disabled>
                        Выберите версию
                      </option>
                      {selection?.versions.map((version) => (
                        <option key={version.id} value={version.id}>
                          v{version.version_number} · {date(version.created_at)}
                        </option>
                      ))}
                    </select>
                  </label>
                  <Button
                    disabled={busy || !versionId || polling}
                    onClick={() => void start()}
                  >
                    <Play size={14} />
                    {busy ? "Запускаем…" : "Оценить диалог"}
                  </Button>
                </div>
                <p className="control-note">
                  Новый запуск использует последнюю версию транскрипта.
                </p>
                {!checklists.length && (
                  <a className="text-button" href="#/checklists">
                    Создать чек-лист
                  </a>
                )}
                {Boolean(selectionError) && (
                  <ErrorBox
                    error={selectionError}
                    onRetry={() => setReload((v) => v + 1)}
                  />
                )}
              </details>
              {Boolean(actionError) && <ErrorBox error={actionError} />}
              {polling && (
                <div className="analysis-pending" role="status">
                  <LoaderCircle className="spin" size={14} />
                  {evaluation?.status === "queued"
                    ? "Диалог в очереди на анализ…"
                    : "AI анализирует диалог и проверяет доказательства…"}
                </div>
              )}
              {Boolean(pollError) && (
                <ErrorBox
                  error={pollError}
                  onRetry={() => setReload((v) => v + 1)}
                />
              )}
              {evaluation?.status === "failed" && (
                <div className="error-box" role="alert">
                  <AlertCircle size={17} />
                  <div>
                    <strong>{errorMessage(evaluation.error?.code)}</strong>
                    <small>
                      Код: {safeCode(evaluation.error?.code)} · запуск сохранён
                      как failed
                    </small>
                    <p>После исправления причины создайте новый запуск.</p>
                  </div>
                </div>
              )}
              {evaluation?.review_required && (
                <div className="warning-box">
                  <strong>Нужна ручная проверка</strong>
                  <ul>
                    {evaluation.review_reasons.map((reason, index) => (
                      <li key={index}>{reason}</li>
                    ))}
                  </ul>
                </div>
              )}
              <Tabs
                className="quality-tabs"
                value={tab}
                onValueChange={(value) => setTab(value as typeof tab)}
              >
                {tabs}
                <TabsContent
                  value="criteria"
                  forceMount
                  hidden={tab !== "criteria"}
                  className="criteria-tab-content"
                >
                  {final ? (
                    <>
                      <ScrollArea className="criteria-scroll">
                        <div
                          className="criteria-table"
                          role="table"
                          aria-label="Оценки по критериям"
                        >
                          <div className="criteria-table-heading" role="row">
                            <span role="columnheader">Критерий</span>
                            <span role="columnheader">Ответ</span>
                            <span role="columnheader">Вклад /100</span>
                            <span role="columnheader" className="sr-only">
                              Апелляция
                            </span>
                          </div>
                          {final.criteria.map((result, index) => {
                            const rule = definitions?.criteria.find(
                              (item) => item.id === result.criterion_id,
                            );
                            const flag = rule?.type === "flag";
                            const negative = flag
                              ? result.answer === true
                              : result.answer === false || result.answer === 0;
                            const na =
                              result.applicability === "not_applicable";
                            return (
                              <article
                                role="row"
                                className={`criterion-result ${result.criterion_id === criterion?.criterion_id ? "is-selected" : ""}`}
                                key={result.criterion_id}
                              >
                                <div role="cell">
                                  <button
                                    className="criterion-select"
                                    onClick={() => chooseCriterion(result)}
                                    aria-pressed={
                                      result.criterion_id ===
                                      criterion?.criterion_id
                                    }
                                  >
                                    <span className="criterion-index">
                                      {String(index + 1).padStart(2, "0")}
                                    </span>
                                    <span>
                                      {rule?.name ?? result.criterion_id}
                                    </span>
                                  </button>
                                </div>
                                <span
                                  role="cell"
                                  className={`answer-badge ${na ? "na" : negative ? "negative" : flag ? "neutral" : "positive"}`}
                                >
                                  {na ? (
                                    <Minus size={12} />
                                  ) : negative ? (
                                    <CircleX size={12} />
                                  ) : (
                                    <CircleCheck size={12} />
                                  )}
                                  <span>{answerLabel(result, rule)}</span>
                                </span>
                                <span role="cell" className="criterion-value">
                                  {flag ? (
                                    <Flag size={13} />
                                  ) : na ? (
                                    "—"
                                  ) : (
                                    number(result.effective_points)
                                  )}
                                </span>
                                <Button
                                  variant="ghost"
                                  size="icon-xs"
                                  aria-label="Оспорить"
                                  onClick={() => {
                                    setFocusedCriterion(result.criterion_id);
                                    setAppealCriterion(result.criterion_id);
                                    setTab("appeals");
                                  }}
                                >
                                  <MessageSquarePlus size={13} />
                                </Button>
                              </article>
                            );
                          })}
                        </div>
                        {final.gross_error === true && (
                          <div className="warning-box gross-warning">
                            <Flag size={14} />
                            <strong>Обнаружена грубая ошибка</strong>
                            <p>
                              Отдельный флаг · итог не обнуляется автоматически.
                            </p>
                          </div>
                        )}
                      </ScrollArea>
                      {criterion && (
                        <section
                          className="criterion-evidence"
                          aria-label="Основание выбранного критерия"
                        >
                          <div className="evidence-heading">
                            <Quote size={14} />
                            <span>Основание оценки</span>
                            {criterion.review_required && (
                              <span className="badge queued">Проверить</span>
                            )}
                          </div>
                          <h3>{definition?.name ?? criterion.criterion_id}</h3>
                          <p>{criterion.explanation}</p>
                          <div className="criterion-points">
                            <span>
                              Исходный вес{" "}
                              <strong>{number(criterion.weight)}</strong>
                            </span>
                            <span>
                              {definition?.type === "flag"
                                ? "Отдельный флаг"
                                : criterion.applicability === "not_applicable"
                                  ? "N/A · вес исключён"
                                  : `Применимый вес ${number(criterion.effective_weight)}`}
                            </span>
                          </div>
                          {criterion.review_reasons.length > 0 && (
                            <p className="criterion-review">
                              {criterion.review_reasons.join("; ")}
                            </p>
                          )}
                          <div className="evidence-list">
                            {criterion.evidence.map((evidence, index) => (
                              <button
                                key={index}
                                className="evidence-button"
                                onClick={() => showEvidence(evidence)}
                              >
                                <ArrowUpRight size={13} />
                                {evidence.kind === "message"
                                  ? evidence.message_id
                                  : `${evidence.start_message_id}–${evidence.end_message_id}`}
                              </button>
                            ))}
                          </div>
                          <Button
                            className="appeal-criterion-action"
                            variant="outline"
                            size="sm"
                            onClick={() => {
                              setAppealCriterion(criterion.criterion_id);
                              setTab("appeals");
                            }}
                          >
                            <MessageSquarePlus size={14} />
                            Оспорить критерий
                          </Button>
                        </section>
                      )}
                    </>
                  ) : (
                    <Empty
                      title="Здесь появится оценка"
                      text="Каждый критерий будет сопровождаться объяснением и ссылкой на исходную реплику."
                    />
                  )}
                </TabsContent>
                <TabsContent
                  value="appeals"
                  forceMount
                  hidden={tab !== "appeals"}
                  className="appeals-tab-content"
                >
                  <ScrollArea className="quality-scroll">
                    {evaluation?.status === "completed" && definitions ? (
                      <Appeals
                        key={evaluation.id}
                        evaluation={evaluation}
                        definitions={definitions}
                        messages={conversation.messages}
                        initialCriterion={appealCriterion}
                        onEvidence={showEvidence}
                        onUpdated={assessmentChanged}
                      />
                    ) : (
                      <Empty
                        title="Апелляции появятся после оценки"
                        text="Можно оспорить критерий завершённого анализа."
                      />
                    )}
                  </ScrollArea>
                </TabsContent>
                <TabsContent
                  value="runs"
                  forceMount
                  hidden={tab !== "runs"}
                  className="runs-tab-content"
                >
                  <ScrollArea className="quality-scroll">
                    <section className="run-history">
                      <header className="section-heading">
                        <Clock3 size={15} />
                        <h3>История запусков</h3>
                      </header>
                      {history.length ? (
                        history.map((run) => (
                          <a
                            key={run.id}
                            className={`history-row ${run.id === evaluation?.id ? "selected" : ""}`}
                            href={`#/dialogues/${encodeURIComponent(id)}?evaluation=${encodeURIComponent(run.id)}`}
                          >
                            <div>
                              <time>{date(run.created_at)}</time>
                              <code>{run.id.slice(0, 8)}</code>
                            </div>
                            <StatusBadge status={run.status} />
                            <strong>
                              {number(run.final?.total)}
                              <small>/100</small>
                            </strong>
                            <ChevronRight size={14} />
                          </a>
                        ))
                      ) : (
                        <p className="muted history-empty">
                          Анализ ещё не запускался.
                        </p>
                      )}
                    </section>
                    {evaluation?.provenance && (
                      <section className="provenance">
                        <h3>Параметры AI-анализа</h3>
                        <p>
                          {evaluation.provenance.provider} ·{" "}
                          {evaluation.provenance.model_reported ??
                            evaluation.provenance.model_requested}
                        </p>
                        <dl>
                          <div>
                            <dt>Промпт</dt>
                            <dd>{evaluation.provenance.prompt_version}</dd>
                          </div>
                          <div>
                            <dt>Длительность</dt>
                            <dd>
                              {number(evaluation.provenance.duration_ms / 1000)}{" "}
                              с
                            </dd>
                          </div>
                          <div>
                            <dt>Запросы</dt>
                            <dd>{evaluation.provenance.usage.request_count}</dd>
                          </div>
                          <div>
                            <dt>Токены</dt>
                            <dd>
                              {evaluation.provenance.usage.total_tokens ??
                                "Неизвестно"}
                            </dd>
                          </div>
                          <div>
                            <dt>Стоимость</dt>
                            <dd>
                              {evaluation.provenance.estimated_cost_usd == null
                                ? "Не рассчитана"
                                : `$${evaluation.provenance.estimated_cost_usd.toFixed(4)}`}
                            </dd>
                          </div>
                        </dl>
                      </section>
                    )}
                    {final?.sections.length ? (
                      <section className="section-scores">
                        <h3>Итоги по разделам</h3>
                        {final.sections.map((section, index) => (
                          <div key={index}>
                            <span>{section.name ?? "Без раздела"}</span>
                            <strong>{number(section.total)}</strong>
                          </div>
                        ))}
                      </section>
                    ) : null}
                  </ScrollArea>
                </TabsContent>
              </Tabs>
            </>
          )}
        </section>
      </ResizablePanel>
    </>
  );
}
