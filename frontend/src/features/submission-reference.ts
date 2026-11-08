import type { SubmissionReference, SubmissionPreflight } from "../api/types";

export const referenceMaxBytes = 16 * 1024 * 1024;
const invalid = () => new Error("В эталоне нужны 1–1000 уникальных строковых conversation_id и согласованное целое total_records.");
const object = (value: unknown): value is Record<string, unknown> =>
  value !== null && typeof value === "object" && !Array.isArray(value);

export function parseSubmissionReference(value: unknown): SubmissionReference {
  if (!object(value)) throw invalid();
  let payload: Record<string, unknown>;
  let totalRequired = false;
  if (Object.hasOwn(value, "data")) {
    if (value.isSuccess !== true || !new Set<unknown>([undefined, null, false, ""]).has(value.error) || !object(value.data)) throw invalid();
    payload = value.data;
    totalRequired = true;
  } else {
    payload = value;
  }
  if (!Array.isArray(payload.records) || !payload.records.length || payload.records.length > 1000) throw invalid();
  if (totalRequired || Object.hasOwn(payload, "total_records")) {
    if (!Number.isSafeInteger(payload.total_records) || payload.total_records !== payload.records.length) throw invalid();
  }
  const ids = payload.records.map((record) => {
    if (!object(record) || typeof record.conversation_id !== "string" || !record.conversation_id.trim()) throw invalid();
    return record.conversation_id.trim();
  });
  if (new Set(ids).size !== ids.length) throw invalid();
  return { expected_conversation_ids: ids, expected_total_records: ids.length };
}

export async function readSubmissionReference(file: Pick<File, "size" | "text">) {
  if (file.size <= 0 || file.size > referenceMaxBytes)
    throw new Error("Выберите непустой JSON-файл эталона размером до 16 МиБ.");
  let parsed: unknown;
  try { parsed = JSON.parse(await file.text()); }
  catch { throw new Error("Не удалось прочитать JSON эталона. Проверьте формат файла."); }
  return parseSubmissionReference(parsed);
}

export function validPreflight(value: SubmissionPreflight, reference: SubmissionReference, batchTotal: number) {
  return value && [value.expected_count, value.batch_count, value.missing_count, value.extra_count]
    .every((n) => Number.isSafeInteger(n) && n >= 0 && n <= 1000) &&
    value.expected_count === reference.expected_total_records && value.batch_count === batchTotal &&
    value.missing_count <= value.expected_count && value.extra_count <= value.batch_count &&
    typeof value.matches === "boolean" &&
    value.matches === (value.missing_count === 0 && value.extra_count === 0 && value.expected_count === value.batch_count);
}
