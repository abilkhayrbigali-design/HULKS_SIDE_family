import { createContext, useCallback, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { Wallet, RefreshCw, LockKeyhole } from "lucide-react";
import { api, ApiError, errorMessage, logFailure } from "../api/client";
import type { AiBudget } from "../api/types";
import { Button } from "../components/ui/button";
import { ErrorBox, Loading, Modal, date } from "../ui";

const reasons = new Set([
  "AI_BUDGET_DISABLED", "AI_BUDGET_EXCEEDED", "AI_BUDGET_POLICY_UNSUPPORTED",
  "AI_BUDGET_UNAVAILABLE", "AI_BUDGET_RESERVATION_CONFLICT", "AI_BUDGET_WAITING",
]);
const money = (value: unknown) => typeof value === "string" && /^\d+\.\d{6}$/.test(value);
export function validBudget(value: AiBudget) {
  return value && value.currency === "USD" &&
    [value.limit_usd, value.committed_upper_usd, value.reserved_usd, value.available_usd].every(money) &&
    (value.next_request_upper_usd === null || money(value.next_request_upper_usd)) &&
    [value.active_reservations, value.unknown_reservations].every((n) => Number.isSafeInteger(n) && n >= 0) &&
    typeof value.enabled === "boolean" &&
    (!value.enabled || (value.blocked_reason === null && value.next_request_upper_usd !== null && value.pricing_version !== null)) &&
    (value.blocked_reason === null || reasons.has(value.blocked_reason)) &&
    typeof value.model === "string" && value.service_tier === "default" &&
    (value.pricing_version === null || typeof value.pricing_version === "string") &&
    typeof value.accounting_started_at === "string" && Number.isFinite(Date.parse(value.accounting_started_at));
}
interface BudgetState {
  value: AiBudget | null;
  error: unknown;
  loading: boolean;
  allowed: boolean;
  refresh: () => Promise<void>;
}
const Context = createContext<BudgetState | null>(null);
export function BudgetProvider({ children }: { children: ReactNode }) {
  const [value, setValue] = useState<AiBudget | null>(null);
  const [error, setError] = useState<unknown>();
  const [loading, setLoading] = useState(true);
  const mounted = useRef(false);
  const generation = useRef(0);
  const refresh = useCallback(async () => {
    if (!mounted.current) return;
    const token = ++generation.current;
    setLoading(true);
    setError(undefined);
    try {
      const next = await api.aiBudget();
      if (!mounted.current || generation.current !== token) return;
      if (!validBudget(next)) {
        logFailure(200, "INVALID_RESPONSE");
        throw new ApiError(200, "INVALID_RESPONSE");
      }
      setValue(next);
    } catch (e) {
      if (mounted.current && generation.current === token) setError(e);
    } finally {
      if (mounted.current && generation.current === token) setLoading(false);
    }
  }, []);
  useEffect(() => {
    mounted.current = true;
    void refresh();
    return () => { mounted.current = false; ++generation.current; };
  }, [refresh]);
  return <Context.Provider value={{ value, error, loading,
    allowed: !loading && !error && value?.enabled === true && value.blocked_reason === null,
    refresh,
  }}>{children}</Context.Provider>;
}
export function useBudget() {
  const value = useContext(Context);
  if (!value) throw new Error("Budget context is unavailable");
  return value;
}
export function BudgetNotice() {
  const budget = useBudget();
  return <div className={`budget-notice ${budget.allowed ? "available" : "blocked"}`} aria-live="polite">
    <p>{budget.loading ? "Проверяем общий бюджет AI…" : budget.error ? "Статус бюджета недоступен. Новые AI-вызовы заблокированы." : budget.allowed
      ? `Общий бюджет AI · доступно ${budget.value!.available_usd} USD`
      : errorMessage(budget.value?.blocked_reason ?? "AI_BUDGET_UNAVAILABLE")}</p>
    {!budget.loading && <Button size="sm" variant="ghost" onClick={() => void budget.refresh()}><RefreshCw size={13} />Обновить бюджет</Button>}
  </div>;
}
export function BudgetStatus() {
  const budget = useBudget();
  const [open, setOpen] = useState(false);
  const label = budget.loading ? "проверяется" : budget.allowed ? "доступен" : "запуски заблокированы";
  return <>
    <Button className="budget-shell-button" size="sm" variant="outline" aria-label={`Бюджет AI: ${label}`} onClick={() => setOpen(true)}>
      {budget.allowed ? <Wallet size={15} /> : <LockKeyhole size={15} />}
      <span className="budget-shell-label">Бюджет AI · {label}</span>
    </Button>
    {open && <Modal title="Общий бюджет AI" description="Чтение общего денежного лимита, резервов и доступности AI-вызовов." onClose={() => setOpen(false)}>
      <p className="muted">Единый локальный учёт для одиночных оценок, пакетов и повторов. Суммы — консервативные верхние оценки и резервы; фактический счёт доступен у провайдера.</p>
      <BudgetNotice />
      {budget.loading ? <Loading /> : budget.error ? <ErrorBox error={budget.error} onRetry={() => void budget.refresh()} /> : budget.value && <>
        <dl className="budget-amounts">
          {[["Общий лимит", budget.value.limit_usd], ["Учтённая верхняя оценка", budget.value.committed_upper_usd], ["Удержано в резерве", budget.value.reserved_usd], ["Доступно", budget.value.available_usd], ["Резерв следующей попытки", budget.value.next_request_upper_usd]].map(([label, amount]) => <div key={label}><dt>{label}</dt><dd>{amount === null ? "Неизвестен" : `${amount} USD`}</dd></div>)}
          <div><dt>Активные резервы</dt><dd>{budget.value.active_reservations}</dd></div>
          <div><dt>Резервы с неизвестной стоимостью</dt><dd>{budget.value.unknown_reservations}</dd></div>
        </dl>
        <p className="muted">Неизвестные затраты остаются удержанными. Начало учёта: {date(budget.value.accounting_started_at)}; предыдущие вызовы автоматически в учёт не включены.</p>
        <p className="muted">Модель: {budget.value.model} · тариф: {budget.value.service_tier}</p>
      </>}
      <p className="muted">Лимит настраивает оператор сервера после отдельного разрешения. Здесь доступны только чтение и обновление статуса.</p>
    </Modal>}
  </>;
}
