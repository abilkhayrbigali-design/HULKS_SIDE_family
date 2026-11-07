import { createContext, useContext, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { api, ApiError, logFailure } from "../api/client";
import type { BatchCreate, EvaluationBatch } from "../api/types";
import { useWorkspace } from "./context";

const storageKey = "cqa.batch";
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
function restore(): { id: string | null; attempt: BatchCreate | null } {
  try {
    const value = JSON.parse(sessionStorage.getItem(storageKey) ?? "null");
    const attempt = value?.attempt;
    return {
      id: typeof value?.id === "string" && uuid.test(value.id) ? value.id : null,
      attempt:
        attempt && uuid.test(attempt.request_id) && uuid.test(attempt.checklist_version_id) &&
        Array.isArray(attempt.conversation_ids) && attempt.conversation_ids.length > 0 &&
        attempt.conversation_ids.length <= 1000 &&
        attempt.conversation_ids.every((id: unknown) => typeof id === "string" && uuid.test(id)) &&
        new Set(attempt.conversation_ids).size === attempt.conversation_ids.length
          ? {
            request_id: attempt.request_id,
            checklist_version_id: attempt.checklist_version_id,
            conversation_ids: attempt.conversation_ids,
          } : null,
    };
  } catch {
    return { id: null, attempt: null };
  }
}
export const batchFinished = (batch: EvaluationBatch) =>
  batch.status === "completed" || batch.status === "completed_with_errors";

interface BatchState {
  id: string | null;
  batch: EvaluationBatch | null;
  error: unknown;
  loading: boolean;
  busy: boolean;
  attempt: BatchCreate | null;
  revision: number;
  select: (id: string) => void;
  refresh: () => void;
  create: (conversation_ids: string[], checklist_version_id: string) => Promise<void>;
  retryUnconfirmed: () => Promise<void>;
  retryFailed: () => Promise<void>;
}
const Context = createContext<BatchState | null>(null);
export function BatchProvider({ children }: { children: ReactNode }) {
  const [initial] = useState(restore);
  const [id, setId] = useState(initial.id);
  const [attempt, setAttempt] = useState(initial.attempt);
  const [batch, setBatch] = useState<EvaluationBatch | null>(null);
  const [error, setError] = useState<unknown>();
  const [readError, setReadError] = useState<unknown>();
  const [loading, setLoading] = useState(Boolean(initial.id));
  const [busy, setBusy] = useState(false);
  const [reload, setReload] = useState(0);
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const pending = useRef(false);
  const current = useRef<EvaluationBatch | null>(null);
  const workspace = useWorkspace();
  const refreshQueue = useRef(workspace.refreshQueue);
  refreshQueue.current = workspace.refreshQueue;
  const persist = (nextId: string | null, nextAttempt: BatchCreate | null) => {
    try {
      sessionStorage.setItem(storageKey, JSON.stringify({ id: nextId, attempt: nextAttempt }));
    } catch {
      /* The mounted provider still survives page navigation without storage. */
    }
  };
  const apply = (value: EvaluationBatch) => {
    const previous = current.current;
    if (previous?.id === value.id &&
        (previous.completed !== value.completed || previous.failed !== value.failed))
      refreshQueue.current();
    current.current = value;
    setBatch(value);
  };
  useEffect(() => {
    const token = ++generation.current;
    let active = true;
    let timer: ReturnType<typeof setTimeout> | undefined;
    if (!id) {
      setLoading(false);
      return;
    }
    setLoading(true);
    setReadError(undefined);
    const read = async () => {
      if (!active || generation.current !== token) return;
      try {
        const value = await api.batch(id);
        if (!active || generation.current !== token) return;
        if (value.id !== id) {
          logFailure(200, "INVALID_RESPONSE");
          throw new ApiError(200, "INVALID_RESPONSE");
        }
        apply(value);
        setLoading(false);
        if (!batchFinished(value)) timer = setTimeout(() => void read(), 2000);
      } catch (e) {
        if (!active || generation.current !== token) return;
        setReadError(e);
        setLoading(false);
        // Stop after the first failure; only an explicit refresh retries reading.
      }
    };
    void read();
    return () => {
      active = false;
      clearTimeout(timer);
    };
  }, [id, reload]);

  const run = async (operation: () => Promise<EvaluationBatch>, request: BatchCreate | null) => {
    if (pending.current) return;
    pending.current = true;
    setBusy(true);
    setError(undefined);
    setReadError(undefined);
    const token = ++generation.current;
    if (request) {
      setAttempt(request);
      persist(id, request);
    }
    try {
      const value = await operation();
      if (generation.current !== token) return;
      apply(value);
      setId(value.id);
      setAttempt(null);
      persist(value.id, null);
      setRevision((v) => v + 1);
      setReload((v) => v + 1);
      refreshQueue.current();
    } catch (e) {
      if (generation.current === token) {
        setError(e);
        // A transport failure may have committed. Keep the exact request ID.
        setReload((v) => v + 1);
      }
    } finally {
      pending.current = false;
      setBusy(false);
    }
  };
  return <Context.Provider value={{
    id, batch, error: error ?? readError, loading, busy, attempt, revision,
    select: (nextId) => {
      if (pending.current || nextId === id) return;
      ++generation.current;
      current.current = null;
      setBatch(null);
      setId(nextId);
      setError(undefined);
      setReadError(undefined);
      persist(nextId, attempt);
    },
    refresh: () => {
      if (pending.current) return;
      setError(undefined);
      setReload((v) => v + 1);
    },
    create: async (conversation_ids, checklist_version_id) => {
      const same = attempt?.checklist_version_id === checklist_version_id &&
        JSON.stringify(attempt.conversation_ids) === JSON.stringify(conversation_ids);
      const request = same ? attempt! : {
        request_id: crypto.randomUUID(), conversation_ids, checklist_version_id,
      };
      await run(() => api.createBatch(request), request);
    },
    retryUnconfirmed: async () => {
      if (attempt) await run(() => api.createBatch(attempt), attempt);
    },
    retryFailed: async () => {
      if (id) await run(() => api.retryBatch(id), null);
    },
  }}>{children}</Context.Provider>;
}
export function useBatches() {
  const value = useContext(Context);
  if (!value) throw new Error("Batch context is unavailable");
  return value;
}
