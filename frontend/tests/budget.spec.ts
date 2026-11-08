import { test, expect } from "@playwright/test";
import { mockAPI, syntheticBudget } from "./helpers/mock-api";

test("loading and zero global budget block single analysis without blocking saved data", async ({ page }) => {
  const s = await mockAPI(page, { completed: true });
  let release!: () => void;
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/v1/ai-budget", async (route) => {
    await held;
    return route.fulfill({ json: { ...syntheticBudget(), limit_usd: "0.000000", available_usd: "0.000000", enabled: false, blocked_reason: "AI_BUDGET_DISABLED" } });
  });
  await page.goto(`/#/dialogues/${s.conversation.id}`);
  await expect(page.locator(".score-main")).toContainText("70,00");
  await page.locator(".evaluation-controls summary").click();
  const start = page.getByRole("button", { name: "Оценить диалог", exact: true });
  await expect(start).toBeDisabled();
  release();
  await expect(page.locator(".budget-notice")).toContainText("лимит равен нулю");
  await expect(start).toBeDisabled();
  await expect(page.locator(".criterion-result")).toHaveCount(s.evaluation.final.criteria.length);
  expect(s.posts).toHaveLength(0);
});

test("invalid or failed budget reads stay closed and show only safe diagnostics", async ({ page }) => {
  const s = await mockAPI(page);
  let failure = false;
  let reads = 0;
  await page.route("**/api/v1/ai-budget", (route) => {
    reads++;
    return route.fulfill(failure
      ? { status: 503, json: { error: { code: "AI_BUDGET_UNAVAILABLE", message: "PRIVATE_BUDGET_MARKER", details: [] } } }
      : { json: { ...syntheticBudget(), available_usd: "PRIVATE_BUDGET_MARKER" } });
  });
  await page.goto(`/#/dialogues/${s.conversation.id}`);
  await expect(page.getByRole("button", { name: "Оценить диалог", exact: true })).toBeDisabled();
  await page.getByRole("button", { name: /Бюджет AI:/ }).click();
  await expect(page.getByRole("alert")).toContainText("INVALID_RESPONSE");
  failure = true;
  await page.getByRole("dialog").getByRole("button", { name: "Обновить бюджет", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("AI_BUDGET_UNAVAILABLE");
  const count = reads;
  await page.waitForTimeout(2300);
  expect(reads).toBe(count);
  expect(s.posts).toHaveLength(0);
  expect(s.consoleLines.join(" ")).toContain("event=ui_operation_failed status=503 error=AI_BUDGET_UNAVAILABLE");
  expect(s.consoleLines.join(" ")).not.toContain("PRIVATE_BUDGET_MARKER");
  await expect(page.locator("body")).not.toContainText("PRIVATE_BUDGET_MARKER");
});

test("unknown held reservations preserve exact displayed amounts and server enablement", async ({ page }) => {
  const s = await mockAPI(page);
  await page.route("**/api/v1/ai-budget", (route) => route.fulfill({ json: {
    ...syntheticBudget(), committed_upper_usd: "0.000001", reserved_usd: "0.587400",
    available_usd: "9.412599", active_reservations: 0, unknown_reservations: 1,
  } }));
  await page.goto(`/#/dialogues/${s.conversation.id}`);
  await expect(page.getByRole("button", { name: "Оценить диалог", exact: true })).toBeEnabled();
  await page.getByRole("button", { name: /Бюджет AI:/ }).click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toContainText("9.412599 USD");
  await expect(dialog).toContainText("0.000001 USD");
  await expect(dialog).toContainText("Резервы с неизвестной стоимостью1");
  expect(await dialog.locator("input").count()).toBe(0);
  await page.getByRole("button", { name: "Закрыть", exact: true }).click();
  await expect(page.getByRole("button", { name: "Оценить диалог", exact: true })).toBeEnabled();
  expect(s.posts).toHaveLength(0);
});
