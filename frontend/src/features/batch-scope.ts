import type { Conversation, Page } from "../api/types";

export interface BatchFilters { language: string; channel: string; group: string }
export class BatchScopeError extends Error {}
export function batchScopeQuery(filters: BatchFilters, offset: number) {
  const query = new URLSearchParams({ limit: "100", offset: String(offset) });
  if (filters.language) query.set("language", filters.language);
  if (filters.channel) query.set("channel", filters.channel);
  if (filters.group.trim()) query.set("group_id", filters.group.trim());
  return query.toString();
}
export async function loadBatchScope(
  load: (offset: number) => Promise<Page<Conversation>>,
  active = () => true,
) {
  const items: Conversation[] = [];
  const ids = new Set<string>();
  let total: number | undefined;
  while (active()) {
    const page = await load(items.length);
    if (!active()) return null;
    if (!Number.isSafeInteger(page.total) || page.total < 0 || !Array.isArray(page.items))
      throw new BatchScopeError("Не удалось загрузить полный набор. Подготовьте набор заново.");
    if (page.total > 1000)
      throw new BatchScopeError("В наборе больше 1000 диалогов. Уточните группу, язык или канал.");
    if (total !== undefined && total !== page.total)
      throw new BatchScopeError("Состав набора изменился при загрузке. Подготовьте набор заново.");
    total = page.total;
    for (const item of page.items) {
      if (ids.has(item.id))
        throw new BatchScopeError("Состав набора изменился при загрузке. Подготовьте набор заново.");
      ids.add(item.id);
      items.push(item);
    }
    if (items.length === total) return items;
    if (items.length > total || page.items.length === 0)
      throw new BatchScopeError("Не удалось загрузить полный набор. Подготовьте набор заново.");
  }
  return null;
}
