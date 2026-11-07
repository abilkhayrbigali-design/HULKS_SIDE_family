import { useEffect, useState } from "react";
import {
  Check,
  CornerDownRight,
  MessageSquarePlus,
  ShieldCheck,
} from "lucide-react";
import { api, allPages, ApiError, logFailure } from "../api/client";
import type {
  Appeal,
  ChecklistVersion,
  Criterion,
  Decision,
  Evaluation,
  Evidence,
  Message,
} from "../api/types";
import { date, Empty, ErrorBox, Loading } from "../ui";
import { answerLabel } from "./ConversationView";
export function Appeals({
  evaluation,
  definitions,
  messages,
  initialCriterion,
  onEvidence,
  onUpdated,
}: {
  evaluation: Evaluation;
  definitions: ChecklistVersion;
  messages: Message[];
  initialCriterion: string | null;
  onEvidence: (e: Evidence) => void;
  onUpdated: (e: Evaluation) => void;
}) {
  const [items, setItems] = useState<Appeal[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>();
  const [criterion, setCriterion] = useState(
    initialCriterion ?? definitions.criteria[0]?.id ?? "",
  );
  const [comment, setComment] = useState("");
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  useEffect(() => {
    if (initialCriterion) setCriterion(initialCriterion);
  }, [initialCriterion]);
  useEffect(() => {
    let active = true;
    setLoading(true);
    allPages((offset) => api.appeals(evaluation.id, offset))
      .then((all) => {
        if (active) {
          setItems(all);
          setError(undefined);
        }
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
  }, [evaluation.id, reload]);
  const submit = async () => {
    if (!comment.trim()) return;
    setBusy(true);
    setError(undefined);
    try {
      await api.appeal(evaluation.id, criterion, comment.trim());
      setComment("");
      setReload((v) => v + 1);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <div className="appeals-content">
      <div className="appeal-create">
        <h3>
          <MessageSquarePlus size={18} />
          Подать апелляцию
        </h3>
        <p className="muted">
          Опишите, с чем не согласны. Исходная оценка сохранится.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          <fieldset disabled={busy} className="form-fieldset">
            <label className="field">
              Спорный критерий
              <select
                value={criterion}
                onChange={(e) => setCriterion(e.target.value)}
              >
                {definitions.criteria.map((c) => (
                  <option key={c.id} value={c.id}>
                    {c.name}
                  </option>
                ))}
              </select>
            </label>
            <label className="field">
              Комментарий
              <textarea
                required
                rows={3}
                value={comment}
                onChange={(e) => setComment(e.target.value)}
                placeholder="Почему оценку стоит пересмотреть?"
              />
            </label>
            <button
              className="button primary small"
              disabled={
                busy ||
                !comment.trim() ||
                items.some(
                  (a) => a.criterion_id === criterion && a.status === "open",
                )
              }
            >
              Отправить апелляцию
            </button>
            {items.some(
              (a) => a.criterion_id === criterion && a.status === "open",
            ) && (
              <p className="muted">
                По этому критерию уже есть открытая апелляция.
              </p>
            )}
          </fieldset>
        </form>
      </div>
      <div className="appeal-history-heading">
        <h3>История обращений</h3>
        <button className="text-button" onClick={() => setReload((v) => v + 1)}>
          Обновить историю
        </button>
      </div>
      {Boolean(error) && <ErrorBox error={error} />}
      {loading && items.length === 0 ? (
        <Loading />
      ) : items.length === 0 ? (
        <Empty
          title="Обращений пока нет"
          text="После отправки здесь появятся комментарий, решение и основания пересмотра."
        />
      ) : (
        items.map((a) => (
          <AppealCard
            key={a.id}
            appeal={a}
            definition={
              definitions.criteria.find((c) => c.id === a.criterion_id)!
            }
            messages={messages}
            onEvidence={onEvidence}
            onReload={async () => {
              const [next, refreshed] = await Promise.all([
                api.evaluation(evaluation.id),
                allPages((offset) => api.appeals(evaluation.id, offset)),
              ]);
              onUpdated(next);
              setItems(refreshed);
            }}
            onDecision={(next, resolved) => {
              onUpdated(next);
              setItems((current) =>
                current.map((item) =>
                  item.id === resolved.id ? resolved : item,
                ),
              );
              setReload((v) => v + 1);
            }}
          />
        ))
      )}
    </div>
  );
}
function AppealCard({
  appeal: a,
  definition: d,
  messages,
  onEvidence,
  onReload,
  onDecision,
}: {
  appeal: Appeal;
  definition: Criterion;
  messages: Message[];
  onEvidence: (e: Evidence) => void;
  onReload: () => Promise<void>;
  onDecision: (e: Evaluation, appeal: Appeal) => void;
}) {
  const [action, setAction] = useState<"confirm" | "override">("confirm");
  const [reason, setReason] = useState("");
  const [applicability, setApplicability] = useState<
    "applicable" | "not_applicable"
  >(a.current.applicability);
  const [answer, setAnswer] = useState<string>(
    String(
      a.current.answer ?? (d.type === "scale" ? d.scale?.[0]?.value : false),
    ),
  );
  const [kind, setKind] = useState<"message" | "range">("message");
  const [start, setStart] = useState(
    a.current.evidence[0]?.kind === "message"
      ? a.current.evidence[0].message_id
      : (a.current.evidence[0]?.start_message_id ?? messages[0]?.id ?? ""),
  );
  const [end, setEnd] = useState(
    a.current.evidence[0]?.kind === "range"
      ? a.current.evidence[0].end_message_id
      : (messages[messages.length - 1]?.id ?? ""),
  );
  const [error, setError] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const submit = async () => {
    if (!reason.trim()) return;
    const evidence: Evidence[] =
      kind === "message"
        ? [{ kind, message_id: start }]
        : [{ kind, start_message_id: start, end_message_id: end }];
    if (
      action === "override" &&
      kind === "range" &&
      messages.findIndex((m) => m.id === start) >
        messages.findIndex((m) => m.id === end)
    ) {
      setError(new Error("Начало диапазона должно идти до его конца."));
      logFailure(422, "VALIDATION_ERROR");
      return;
    }
    const decision: Decision =
      action === "confirm"
        ? {
            action,
            reason: reason.trim(),
            expected_revision: a.current_revision,
          }
        : {
            action,
            reason: reason.trim(),
            expected_revision: a.current_revision,
            applicability,
            answer:
              applicability === "not_applicable"
                ? null
                : d.type === "scale"
                  ? Number(answer)
                  : answer === "true",
            evidence,
          };
    setBusy(true);
    setError(undefined);
    try {
      const response = await api.decide(a.id, decision);
      onDecision(response.evaluation, response.appeal);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  };
  return (
    <article className="appeal-card">
      <div className="appeal-card-heading">
        <span
          className={`badge ${a.status === "open" ? "queued" : "completed"}`}
        >
          {a.status === "open" ? "Ожидает решения" : "Рассмотрена"}
        </span>
        <small>
          {date(a.created_at)} · базовая ревизия {a.base_revision} · текущая{" "}
          {a.current_revision}
        </small>
      </div>
      <h3>{d.name}</h3>
      <blockquote>{a.comment}</blockquote>
      <div className="appeal-comparison">
        <span>
          Исходный ответ<strong>{answerLabel(a.original, d)}</strong>
        </span>
        <CornerDownRight size={18} />
        <span>
          Текущий ответ<strong>{answerLabel(a.current, d)}</strong>
        </span>
      </div>
      <div className="evidence-list">
        {a.current.evidence.map((e, i) => (
          <button
            key={i}
            className="evidence-button"
            onClick={() => onEvidence(e)}
          >
            {e.kind === "message"
              ? e.message_id
              : `${e.start_message_id}–${e.end_message_id}`}
          </button>
        ))}
      </div>
      {a.decision ? (
        <div className="decision-record">
          <strong>
            <Check size={16} />
            {a.decision.action === "confirm"
              ? "Оценка подтверждена"
              : "Оценка изменена"}
          </strong>
          <p>{a.decision.reason}</p>
          <div className="decision-result">
            <span>
              Принятый ответ:{" "}
              <strong>{answerLabel(a.decision.result, d)}</strong>
            </span>
            <p>{a.decision.result.explanation}</p>
            <div className="evidence-list">
              {a.decision.result.evidence.map((e, i) => (
                <button
                  key={i}
                  className="evidence-button"
                  onClick={() => onEvidence(e)}
                >
                  {e.kind === "message"
                    ? e.message_id
                    : `${e.start_message_id}–${e.end_message_id}`}
                </button>
              ))}
            </div>
          </div>
          <small>
            {date(a.decision.created_at)} · принято на базе ревизии{" "}
            {a.decision.expected_revision}
          </small>
        </div>
      ) : (
        <details className="decision-editor">
          <summary>
            <ShieldCheck size={17} />
            Рассмотреть как проверяющий
          </summary>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void submit();
            }}
          >
            <fieldset disabled={busy} className="form-fieldset">
              <label className="field">
                Решение
                <select
                  value={action}
                  onChange={(e) =>
                    setAction(e.target.value as "confirm" | "override")
                  }
                >
                  <option value="confirm">Подтвердить текущую оценку</option>
                  <option value="override">Изменить оценку</option>
                </select>
              </label>
              {action === "override" && (
                <>
                  <label className="field">
                    Применимость
                    <select
                      value={applicability}
                      onChange={(e) =>
                        setApplicability(
                          e.target.value as "applicable" | "not_applicable",
                        )
                      }
                    >
                      <option value="applicable">Применим</option>
                      {d.allow_na && (
                        <option value="not_applicable">N/A · неприменим</option>
                      )}
                    </select>
                  </label>
                  {applicability === "applicable" && (
                    <label className="field">
                      Новый ответ
                      <select
                        value={answer}
                        onChange={(e) => setAnswer(e.target.value)}
                      >
                        {d.type === "scale" ? (
                          d.scale!.map((p) => (
                            <option key={p.value} value={p.value}>
                              {p.value} · {p.description}
                            </option>
                          ))
                        ) : (
                          <>
                            <option value="true">
                              {d.type === "flag" ? "Да · обнаружено" : "Да"}
                            </option>
                            <option value="false">
                              {d.type === "flag"
                                ? "Нет · не обнаружено"
                                : "Нет"}
                            </option>
                          </>
                        )}
                      </select>
                    </label>
                  )}
                  <label className="field">
                    Вид доказательства
                    <select
                      value={kind}
                      onChange={(e) =>
                        setKind(e.target.value as "message" | "range")
                      }
                    >
                      <option value="message">Реплика</option>
                      <option value="range">Диапазон реплик</option>
                    </select>
                  </label>
                  <label className="field">
                    {kind === "range" ? "Начало диапазона" : "Реплика"}
                    <select
                      value={start}
                      onChange={(e) => setStart(e.target.value)}
                    >
                      {messages.map((m) => (
                        <option key={m.id} value={m.id}>
                          {m.id} · {m.speaker} · {m.timestamp}
                        </option>
                      ))}
                    </select>
                  </label>
                  {kind === "range" && (
                    <label className="field">
                      Конец диапазона
                      <select
                        value={end}
                        onChange={(e) => setEnd(e.target.value)}
                      >
                        {messages.map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.id} · {m.speaker} · {m.timestamp}
                          </option>
                        ))}
                      </select>
                    </label>
                  )}
                </>
              )}
              <label className="field">
                Причина решения
                <textarea
                  required
                  rows={3}
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  placeholder="Объясните решение на основе диалога"
                />
              </label>
              {Boolean(error) && <ErrorBox error={error} />}
              {error instanceof ApiError && error.status === 409 && (
                <div className="warning-box">
                  <p>
                    Сохранённые данные изменились. Обновите обращение и
                    проверьте актуальное решение перед повтором.
                  </p>
                  <button
                    type="button"
                    className="button small"
                    disabled={busy}
                    onClick={async () => {
                      setBusy(true);
                      try {
                        await onReload();
                        setError(undefined);
                      } catch (e) {
                        setError(e);
                      } finally {
                        setBusy(false);
                      }
                    }}
                  >
                    Обновить обращение
                  </button>
                </div>
              )}
              <button
                className="button primary small"
                disabled={busy || !reason.trim()}
              >
                {busy ? "Сохраняем…" : "Сохранить решение"}
              </button>
            </fieldset>
          </form>
        </details>
      )}
    </article>
  );
}
