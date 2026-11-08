import { describe, expect, it } from "vitest";
import { validBudget } from "./budget";
import type { AiBudget } from "../api/types";

const budget: AiBudget = {
  currency: "USD", limit_usd: "10.000000", committed_upper_usd: "0.000001",
  reserved_usd: "0.587400", available_usd: "9.412599", next_request_upper_usd: "0.587400",
  active_reservations: 0, unknown_reservations: 1, model: "gpt-6-luna", service_tier: "default",
  pricing_version: "gpt-6-luna-standard-2026-11-08-v1", accounting_started_at: "2026-11-08T00:00:00Z", enabled: true, blocked_reason: null,
};
describe("read-only budget status", () => {
  it("accepts server enablement with unknown holds without recomputing the money policy", () => {
    expect(validBudget(budget)).toBe(true);
    expect(validBudget({ ...budget, enabled: false, blocked_reason: "AI_BUDGET_WAITING" })).toBe(true);
  });
  it("fails closed on malformed money, bools, counters or enabled unknown policy", () => {
    for (const patch of [{ limit_usd: "NaN" }, { available_usd: 1 }, { reserved_usd: "-1.000000" }, { enabled: "true" }, { unknown_reservations: -1 }, { next_request_upper_usd: null }, { blocked_reason: "PRIVATE_SERVER_MARKER" }])
      expect(validBudget({ ...budget, ...patch } as AiBudget)).toBe(false);
  });
});
