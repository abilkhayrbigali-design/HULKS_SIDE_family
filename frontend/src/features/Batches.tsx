import { useEffect, useRef, useState } from "react";
import { Download, Layers, Play, RefreshCw } from "lucide-react";
import { api, allPages, ApiError, logFailure, errorMessage } from "../api/client";
import type { ChecklistDetail, ChecklistSummary, Conversation, EvaluationBatch } from "../api/types";
import { Button } from "../components/ui/button";
import { date, Empty, ErrorBox, Loading, StatusBadge } from "../ui";
import { batchFinished, useBatches } from "../workspace/batches";
import { BatchScopeError, batchScopeQuery, loadBatchScope } from "./batch-scope";
import type { BatchFilters } from "./batch-scope";

export function Batches() {
  const state = useBatches();
  const [history, setHistory] = useState<EvaluationBatch[]>([]);
  const [historyError, setHistoryError] = useState<unknown>();
  const [reload, setReload] = useState(0);
  useEffect(() => {
    let active = true;
    allPages((offset) => api.batches(offset)).then((value) => {
      if (active) { setHistory(value); setHistoryError(undefined); }
    }).catch((e) => { if (active) setHistoryError(e); });
    return () => { active = false; };
  }, [state.revision, reload]);
  const listed = history.some((b) => b.id === state.id);
  return <>
    <section className="page-heading">
      <div>
        <div className="eyebrow">ОЦЕНКА НАБОРА ДИАЛОГОВ</div>
        <h1>Пакетная оценка</h1>
        <p>Один набор, одна сохранённая версия правил. Каждый запуск остаётся в истории.</p>
      </div>
      <Layers size={26} aria-hidden />
    </section>
    <div className="batch-layout">
      <BatchForm />
      <section className="panel batch-panel" aria-label="Сохранённый пакет">
        <div className="batch-history">
          <label className="field">Сохранённые пакеты
            <select aria-label="Сохранённые пакеты" disabled={state.busy || !history.length}
              value={state.id ?? ""} onChange={(e) => state.select(e.target.value)}>
              {!listed && <option value={state.id ?? ""}>{state.id ? "Текущий пакет" : "Выберите пакет"}</option>}
              {history.map((b) => <option key={b.id} value={b.id}>
                {date(b.created_at)} · {b.total} диалогов · {b.id.slice(0, 8)}
              </option>)}
            </select>
          </label>
          <Button variant="outline" size="icon-sm" aria-label="Обновить список пакетов" onClick={() => setReload((v) => v + 1)}><RefreshCw size={16} /></Button>
        </div>
        {Boolean(historyError) && <ErrorBox error={historyError} onRetry={() => setReload((v) => v + 1)} />}
        {state.attempt && <div className="batch-unconfirmed" role="status">
          <strong>Запуск не подтверждён</strong>
          <p>Сохранён запрос на {state.attempt.conversation_ids.length} диалогов. Повтор отправит тот же запрос и не создаст второй пакет.</p>
          <Button size="sm" variant="outline" disabled={state.busy} onClick={() => void state.retryUnconfirmed()}>Повторить запрос запуска</Button>
        </div>}
        {Boolean(state.error) && <ErrorBox error={state.error} onRetry={state.id ? state.refresh : undefined} />}
        {state.loading && !state.batch ? <Loading text="Загружаем сохранённый пакет…" /> : state.batch ?
          <BatchProgress batch={state.batch} /> : <Empty title="Пакет ещё не выбран" text="Подготовьте набор и запустите оценку или выберите сохранённый пакет." />}
      </section>
    </div>
    <p className="info-strip">Завершённый пакет подтверждает обработку данных. Точность AI проверяется отдельно по человеческой разметке.</p>
  </>;
}

function BatchForm() {
  const state = useBatches();
  const [checklists, setChecklists] = useState<ChecklistSummary[]>([]);
  const [checklistId, setChecklistId] = useState("");
  const [detail, setDetail] = useState<ChecklistDetail | null>(null);
  const [version, setVersion] = useState("");
  const [filters, setFilters] = useState<BatchFilters>({ language: "", channel: "", group: "" });
  const [prepared, setPrepared] = useState<Conversation[] | null>(null);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [preparing, setPreparing] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<unknown>();
  const [listError, setListError] = useState<unknown>();
  const [detailError, setDetailError] = useState<unknown>();
  const [reload, setReload] = useState(0);
  const generation = useRef(0);
  useEffect(() => {
    let active = true;
    setLoading(true);
    setListError(undefined);
    allPages((offset) => api.checklists(offset)).then((value) => {
      if (!active) return;
      setChecklists(value);
      setChecklistId((previous) => value.some((c) => c.id === previous) ? previous : value[0]?.id ?? "");
    }).catch((e) => { if (active) setListError(e); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reload]);
  useEffect(() => {
    let active = true;
    setDetail(null);
    setVersion("");
    setDetailError(undefined);
    if (checklistId) api.checklist(checklistId).then((value) => {
      if (!active) return;
      setDetail(value);
      setVersion(value.current_version.id);
    }).catch((e) => { if (active) setDetailError(e); });
    return () => { active = false; };
  }, [checklistId, reload]);
  useEffect(() => () => { ++generation.current; }, []);
  const invalidate = () => {
    ++generation.current;
    setPrepared(null);
    setSelected(new Set());
    setPreparing(false);
    setError(undefined);
  };
  const changeFilters = (value: Partial<BatchFilters>) => {
    invalidate();
    setFilters((previous) => ({ ...previous, ...value }));
  };
  const prepare = async () => {
    const token = ++generation.current;
    setPreparing(true);
    setPrepared(null);
    setSelected(new Set());
    setError(undefined);
    try {
      const value = await loadBatchScope((offset) => api.conversations(batchScopeQuery(filters, offset)), () => generation.current === token);
      if (!value || generation.current !== token) return;
      setPrepared(value);
      setSelected(new Set(value.map((c) => c.id)));
    } catch (e) {
      if (generation.current !== token) return;
      if (e instanceof BatchScopeError) logFailure(422, "VALIDATION_ERROR");
      setError(e);
    } finally {
      if (generation.current === token) setPreparing(false);
    }
  };
  return <section className="panel batch-panel" aria-label="Новый пакет">
    <h2>Новый пакет</h2>
    <p className="muted">Состав загружается со всех страниц по этим фильтрам. Поиск и текущая страница рабочей очереди не влияют на пакет.</p>
    {loading ? <Loading /> : <>
      <fieldset disabled={state.busy} className="batch-fieldset">
        <legend className="sr-only">Правила и состав пакета</legend>
        <label className="field">Чек-лист пакета
          <select aria-label="Чек-лист пакета" value={checklistId} onChange={(e) => { invalidate(); setChecklistId(e.target.value); }}>
            {!checklists.length && <option value="">Нет чек-листов</option>}
            {checklists.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
          </select>
        </label>
        <label className="field">Версия чек-листа пакета
          <select aria-label="Версия чек-листа пакета" value={version} disabled={!detail} onChange={(e) => { invalidate(); setVersion(e.target.value); }}>
            {!detail && <option value="">{detailError ? "Не удалось загрузить версии" : checklistId ? "Загружаем версии…" : "Сначала выберите чек-лист"}</option>}
            {detail?.versions.map((v) => <option key={v.id} value={v.id}>Версия {v.version_number} · {v.criteria.length} критериев</option>)}
          </select>
        </label>
        <div className="form-grid">
          <label className="field">Язык набора
            <select aria-label="Язык набора" value={filters.language} onChange={(e) => changeFilters({ language: e.target.value })}>
              <option value="">Все языки</option>{["RU", "KZ", "EN"].map((v) => <option key={v}>{v}</option>)}
            </select>
          </label>
          <label className="field">Канал набора
            <select aria-label="Канал набора" value={filters.channel} onChange={(e) => changeFilters({ channel: e.target.value })}>
              <option value="">Все каналы</option><option value="agent chat">Чат</option><option value="voice call">Звонок</option>
            </select>
          </label>
        </div>
        <label className="field">Группа набора
          <input aria-label="Группа набора" maxLength={200} value={filters.group} placeholder="Все группы" onChange={(e) => changeFilters({ group: e.target.value })} />
        </label>
        <Button variant="outline" disabled={preparing || !version} onClick={() => void prepare()}>
          <RefreshCw size={15} className={preparing ? "spin" : ""} />{preparing ? "Загружаем набор…" : "Подготовить набор"}
        </Button>
        {prepared && <div className="batch-scope">
          <strong role="status">Найдено: {prepared.length} · выбрано: {selected.size}</strong>
          {prepared.length > 0 && <>
            <label className="batch-select-all"><input type="checkbox" checked={selected.size === prepared.length} onChange={(e) => setSelected(new Set(e.target.checked ? prepared.map((c) => c.id) : []))} /> Выбрать все {prepared.length} диалогов</label>
            <div className="batch-selection" role="group" aria-label="Диалоги в новом пакете">
              {prepared.map((c) => <label key={c.id}>
                <input type="checkbox" checked={selected.has(c.id)} onChange={(e) => setSelected((previous) => {
                  const next = new Set(previous); if (e.target.checked) next.add(c.id); else next.delete(c.id); return next;
                })} />
                <span>{c.external_id}<small>{c.language} · {c.channel === "voice call" ? "Звонок" : "Чат"} · {c.group_id}</small></span>
              </label>)}
            </div>
          </>}
          <p className="muted">При запуске сервер зафиксирует текущие транскрипты и выбранную версию правил. Оценка использует AI.</p>
          <Button disabled={!version || !selected.size} onClick={() => void state.create(prepared.filter((c) => selected.has(c.id)).map((c) => c.id), version)}>
            <Play size={15} />{state.busy ? "Создаём пакет…" : `Запустить пакет · ${selected.size}`}
          </Button>
        </div>}
      </fieldset>
    </>}
    {Boolean(listError) && <ErrorBox error={listError} onRetry={() => { invalidate(); setReload((v) => v + 1); }} />}
    {Boolean(detailError) && <ErrorBox error={detailError} onRetry={() => { invalidate(); setReload((v) => v + 1); }} />}
    {Boolean(error) && <ErrorBox error={error} onRetry={() => void prepare()} />}
  </section>;
}

function BatchProgress({ batch }: { batch: EvaluationBatch }) {
  const state = useBatches();
  const finished = batchFinished(batch);
  return <div className="batch-progress">
    <div className="batch-progress-heading">
      <div><h2>{finished ? "Пакет завершён" : "Пакет обрабатывается"}</h2><p className="muted">{date(batch.created_at)} · {batch.id.slice(0, 8)}</p></div>
      <Button variant="outline" size="icon-sm" aria-label="Обновить пакет" disabled={state.loading || state.busy} onClick={state.refresh}><RefreshCw size={16} /></Button>
    </div>
    {batch.source_batch_id && <p className="muted">Повтор ошибок исходного пакета <button className="text-button" disabled={state.busy} onClick={() => state.select(batch.source_batch_id!)}>{batch.source_batch_id.slice(0, 8)}</button>. Исходная история сохранена.</p>}
    <p className="muted">Версия правил зафиксирована: {batch.checklist_version_id}</p>
    <progress aria-label="Прогресс пакета" max={batch.total} value={batch.completed + batch.failed} />
    <dl className="batch-counts" aria-live="polite">
      {[["Всего", batch.total], ["В очереди", batch.queued], ["В работе", batch.running], ["Готово", batch.completed], ["Ошибок", batch.failed]].map(([name, count]) => <div key={String(name)}><dt>{name}</dt><dd>{count}</dd></div>)}
    </dl>
    <div className="batch-actions">
      <Button variant="outline" disabled={!finished || !batch.failed || state.busy} onClick={() => void state.retryFailed()}>
        <RefreshCw size={15} />{state.busy ? "Создаём повтор…" : `Повторить ошибки · ${batch.failed}`}
      </Button>
      <p className="muted">Новый пакет сохранит успешные оценки и повторит только ошибки по исходным снимкам. Новые вызовы AI нужны только для ошибок; экспорт сохранит полный набор.</p>
    </div>
    <div className="batch-items" role="list" aria-label="Результаты пакета">
      {batch.items.map((item, i) => <div role="listitem" key={item.evaluation_id}>
        <a href={`#/dialogues/${encodeURIComponent(item.conversation_id)}?evaluation=${encodeURIComponent(item.evaluation_id)}`}>Диалог {i + 1} · {item.conversation_id.slice(0, 8)}</a>
        <StatusBadge status={item.status} />
        {item.error_code && <span className="batch-item-error">{errorMessage(item.error_code)}</span>}
      </div>)}
    </div>
    <BatchExport key={batch.id} batch={batch} />
  </div>;
}

function BatchExport({ batch }: { batch: EvaluationBatch }) {
  const [team, setTeam] = useState("HULK’S FAMILY");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>();
  const [downloaded, setDownloaded] = useState(false);
  const active = useRef(true);
  const pending = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  const download = async () => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true); setError(undefined); setDownloaded(false);
    try {
      const document = await api.submissionExport(batch.id, team.trim());
      if (!active.current) return;
      const url = URL.createObjectURL(new Blob([JSON.stringify(document, null, 2)], { type: "application/json;charset=utf-8" }));
      const link = window.document.createElement("a");
      link.href = url; link.download = "results.json";
      window.document.body.append(link); link.click(); link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      setDownloaded(true);
    } catch (e) {
      if (!active.current) return;
      if (e instanceof ApiError) setError(e);
      else { logFailure(0, "API_ERROR"); setError(new ApiError(0, "API_ERROR")); }
    } finally {
      pending.current = false;
      if (active.current) setBusy(false);
    }
  };
  return <section className="batch-export" aria-label="Официальный экспорт">
    <h3>Официальный results.json</h3>
    <p className="muted">Экспорт использует сохранённые исходные оценки до апелляций. Новых вызовов AI нет. Незавершённые, ошибочные и требующие проверки оценки сохраняются строками error. Чек-лист должен быть совместим с официальным форматом.</p>
    <label className="field">Название команды<input aria-label="Название команды" value={team} maxLength={200} disabled={busy} onChange={(e) => { setTeam(e.target.value); setDownloaded(false); }} /></label>
    <Button disabled={busy || !team.trim() || !batchFinished(batch)} onClick={() => void download()}><Download size={15} />{busy ? "Готовим файл…" : "Скачать results.json"}</Button>
    {!batchFinished(batch) && <p className="muted">Скачивание доступно после завершения пакета.</p>}
    {downloaded && <p role="status">Файл results.json подготовлен к скачиванию.</p>}
    {Boolean(error) && <ErrorBox error={error} />}
  </section>;
}
