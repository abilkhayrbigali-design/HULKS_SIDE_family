import { describe, expect, it, vi } from "vitest";
import type { Conversation } from "../api/types";
import { batchScopeQuery, loadBatchScope } from "./batch-scope";

const conversations = (count: number) => Array.from({ length: count }, (_, i) => ({ id: String(i) } as Conversation));
describe("fixed full batch scope", () => {
  it("collects more than the queue page and keeps filters on every page", async () => {
    const items = conversations(101);
    const load = vi.fn(async (offset: number) => ({ items: items.slice(offset, offset + 100), total: 101, limit: 100, offset }));
    expect((await loadBatchScope(load))?.map((c) => c.id)).toEqual(items.map((c) => c.id));
    expect(load.mock.calls.map(([offset]) => offset)).toEqual([0, 100]);
    const query = new URLSearchParams(batchScopeQuery({ group: " DEV ", language: "KZ", channel: "voice call" }, 100));
    expect(Object.fromEntries(query)).toEqual({ limit: "100", offset: "100", group_id: "DEV", language: "KZ", channel: "voice call" });
  });
  it("rejects an oversized scope before walking the remaining pages", async () => {
    const load = vi.fn(async (offset: number) => ({ items: conversations(100), total: 1001, limit: 100, offset }));
    await expect(loadBatchScope(load)).rejects.toThrow("больше 1000");
    expect(load).toHaveBeenCalledTimes(1);
  });
  it("refuses changed totals, duplicate IDs and incomplete pages instead of silently shrinking scope", async () => {
    const items = conversations(100);
    for (const second of [
      { items: [{ id: "last" } as Conversation], total: 102 },
      { items: [items[0]], total: 101 },
      { items: [], total: 101 },
    ]) {
      const load = async (offset: number) => ({ ...(offset ? second : { items, total: 101 }), limit: 100, offset });
      await expect(loadBatchScope(load)).rejects.toThrow();
    }
  });
  it("does not continue reading an obsolete preparation", async () => {
    let active = true;
    const load = vi.fn(async (offset: number) => {
      active = false;
      return { items: conversations(100), total: 101, limit: 100, offset };
    });
    expect(await loadBatchScope(load, () => active)).toBeNull();
    expect(load).toHaveBeenCalledTimes(1);
  });
});
