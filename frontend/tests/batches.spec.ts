import { test, expect } from "@playwright/test";
import type { Page } from "@playwright/test";
import { readFileSync } from "node:fs";
import { fixture, mockAPI } from "./helpers/mock-api";

const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const version = fixture("checklist-version.response.json").id;
function makeBatch(n: number, conversations: string[], requestId = id(4000), failed = 0) {
  return {
    id: id(n), request_id: requestId, source_batch_id: null as string | null,
    checklist_version_id: version, created_at: "2026-11-08T04:00:00Z",
    status: failed ? "completed_with_errors" : "queued",
    total: conversations.length, queued: failed ? 0 : conversations.length,
    running: 0, completed: failed ? conversations.length - failed : 0, failed,
    items: conversations.map((conversation_id, index) => ({
      conversation_id, transcript_version_id: id(5000 + index), evaluation_id: id(6000 + index),
      status: failed ? (index < failed ? "failed" : "completed") : "queued", error_code: index < failed ? "AI_TIMEOUT" : null,
    })),
  };
}
async function setup(page: Page, count = 101) {
  const original = await mockAPI(page);
  const template = fixture("conversations.response.json").items[0];
  const conversations = Array.from({ length: count }, (_, i) => ({ ...template, id: id(100 + i), external_id: `synthetic-batch-${i + 1}`, latest_evaluation: null }));
  const s = {
    ...original,
    conversations,
    batches: [] as ReturnType<typeof makeBatch>[],
    creates: [] as any[], retries: [] as string[], exports: [] as any[],
    reads: [] as string[], queueReads: 0,
    noKey: false, loseResponse: false, readFailure: false, exportConflict: false,
    document: { schema_version: "1.0", team_name: "HULK’S FAMILY", model: { name: "synthetic", mode: "external_api" }, results: [{ conversation_id: "synthetic-batch-1", status: "error", error: { code: "AI_TIMEOUT" } }] },
  };
  await page.route("**/api/v1/conversations?**", async (route) => {
    const url = new URL(route.request().url());
    const offset = Number(url.searchParams.get("offset"));
    const limit = Number(url.searchParams.get("limit"));
    if (limit === 25) ++s.queueReads;
    await route.fulfill({ json: { items: conversations.slice(offset, offset + limit), total: count, limit, offset } });
  });
  await page.route("**/api/v1/evaluation-batches**", async (route) => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    const fail = (code: string, status: number) => route.fulfill({ status, json: { error: { code, message: "PRIVATE_BATCH_SERVER_MARKER", details: [] } } });
    if (path.endsWith("/retry-failed")) {
      const source = s.batches.find((b) => path.includes(b.id))!;
      s.retries.push(source.id);
      const child = makeBatch(3001, source.items.filter((item) => item.status === "failed").map((item) => item.conversation_id), id(4001));
      child.source_batch_id = source.id;
      s.batches.unshift(child);
      return route.fulfill({ status: 202, json: child });
    }
    if (request.method() === "POST") {
      const body = request.postDataJSON(); s.creates.push(body);
      if (s.noKey) return fail("AI_NOT_CONFIGURED", 503);
      let batch = s.batches.find((b) => b.request_id === body.request_id);
      if (!batch) { batch = makeBatch(3000, body.conversation_ids, body.request_id); s.batches.unshift(batch); }
      if (s.loseResponse) { s.loseResponse = false; return route.abort("failed"); }
      return route.fulfill({ status: 202, json: batch });
    }
    const batchId = path.split("/").at(-1)!;
    if (batchId === "evaluation-batches") return route.fulfill({ json: { items: s.batches, total: s.batches.length, limit: 100, offset: 0 } });
    s.reads.push(batchId);
    if (s.readFailure) return fail("DATABASE_UNAVAILABLE", 503);
    return route.fulfill({ json: s.batches.find((b) => b.id === batchId) });
  });
  await page.route("**/api/v1/submission-exports", async (route) => {
    s.exports.push(route.request().postDataJSON());
    if (s.exportConflict) return route.fulfill({ status: 409, json: { error: { code: "SUBMISSION_CHECKLIST_INCOMPATIBLE", message: "PRIVATE_BATCH_SERVER_MARKER", details: [] } } });
    return route.fulfill({ json: s.document, headers: { "Content-Disposition": "attachment; filename=results.json" } });
  });
  return s;
}
async function prepare(page: Page) {
  await page.goto("/#/batches");
  await expect(page.getByLabel("Версия чек-листа пакета")).toHaveValue(version);
  await page.getByRole("button", { name: "Подготовить набор", exact: true }).click();
}

test("full scope, explicit launch, retained progress, failed-only retry and saved-result download", async ({ page }) => {
  const s = await setup(page);
  await prepare(page);
  await expect(page.getByText("Найдено: 101 · выбрано: 101", { exact: true })).toBeVisible();
  expect(s.creates).toHaveLength(0);
  await page.getByRole("button", { name: "Запустить пакет · 101", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Пакет обрабатывается" })).toBeVisible();
  expect(s.creates).toHaveLength(1);
  expect(s.creates[0].conversation_ids).toEqual(s.conversations.map((c) => c.id));
  expect(s.creates[0].checklist_version_id).toBe(version);
  await page.getByRole("link", { name: "Чек-листы", exact: true }).click();
  await page.getByRole("link", { name: "Диалоги", exact: true }).click();
  await expect(page.getByLabel("Очередь диалогов")).toBeVisible();
  const reads = s.queueReads;
  await page.waitForTimeout(2200);
  expect(s.queueReads).toBe(reads);
  s.batches[0] = { ...makeBatch(3000, s.creates[0].conversation_ids, s.creates[0].request_id, 2) };
  await expect.poll(() => s.queueReads).toBe(reads + 1);
  await page.getByRole("link", { name: "Пакетная оценка", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Пакет завершён" })).toBeVisible();
  await page.reload();
  await expect(page.getByRole("heading", { name: "Пакет завершён" })).toBeVisible();
  expect(s.creates).toHaveLength(1);
  const downloadEvent = page.waitForEvent("download");
  await page.getByRole("button", { name: "Скачать results.json", exact: true }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toBe("results.json");
  expect(JSON.parse(readFileSync((await download.path())!, "utf8"))).toEqual(s.document);
  expect(s.exports).toEqual([{ batch_id: id(3000), team_name: "HULK’S FAMILY" }]);
  expect(s.creates).toHaveLength(1);
  await page.getByRole("button", { name: "Повторить ошибки · 2", exact: true }).click();
  await expect(page.locator(".batch-counts")).toContainText("Всего2");
  expect(s.retries).toEqual([id(3000)]);
  expect(s.batches[0].source_batch_id).toBe(id(3000));
  await expect(page.getByRole("button", { name: "Скачать results.json", exact: true })).toBeDisabled();
});

test("no-key refuses creation, keeps one request ID for explicit retry and redacts the response", async ({ page }) => {
  const s = await setup(page, 2); s.noKey = true;
  await prepare(page);
  await page.getByRole("button", { name: "Запустить пакет · 2", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("AI_NOT_CONFIGURED");
  await expect(page.getByRole("heading", { name: "Пакет обрабатывается" })).toHaveCount(0);
  await page.getByRole("button", { name: "Повторить запрос запуска", exact: true }).click();
  await expect.poll(() => s.creates.length).toBe(2);
  expect(s.creates[0]).toEqual(s.creates[1]);
  expect(s.batches).toHaveLength(0);
  expect(s.consoleLines.join(" ")).toContain("event=ui_operation_failed status=503 error=AI_NOT_CONFIGURED");
  expect(s.consoleLines.join(" ")).not.toContain("PRIVATE_BATCH_SERVER_MARKER");
  await expect(page.locator("body")).not.toContainText("PRIVATE_BATCH_SERVER_MARKER");
});

test("lost creation response survives reload and retries the same committed request", async ({ page }) => {
  const s = await setup(page, 2); s.loseResponse = true;
  await prepare(page);
  await page.getByRole("button", { name: "Запустить пакет · 2", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("NETWORK_ERROR");
  expect(s.batches).toHaveLength(1);
  await page.reload();
  await expect(page.getByText("Запуск не подтверждён", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Повторить запрос запуска", exact: true }).click();
  await expect(page.getByRole("heading", { name: "Пакет обрабатывается" })).toBeVisible();
  expect(s.creates).toHaveLength(2);
  expect(s.creates[0]).toEqual(s.creates[1]);
  expect(s.batches).toHaveLength(1);
});

test("oversized scope is refused and a changed filter cannot apply an old preparation", async ({ page }) => {
  const s = await setup(page, 1001);
  await prepare(page);
  await expect(page.getByRole("alert")).toContainText("больше 1000");
  await expect(page.getByRole("button", { name: /^Запустить пакет/ })).toHaveCount(0);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  let started = false;
  await page.route("**/api/v1/conversations?**", async (route) => {
    started = true; await gate;
    await route.fulfill({ json: { items: s.conversations.slice(0, 1), total: 1, limit: 100, offset: 0 } });
  });
  await page.getByLabel("Группа набора", { exact: true }).fill("A");
  await page.getByRole("button", { name: "Подготовить набор", exact: true }).click();
  await expect.poll(() => started).toBe(true);
  await page.getByLabel("Группа набора", { exact: true }).fill("B");
  await page.getByLabel("Группа набора", { exact: true }).fill("A");
  release();
  await page.waitForTimeout(200);
  await expect(page.getByText(/^Найдено:/)).toHaveCount(0);
  expect(s.creates).toHaveLength(0);
});

test("a polling failure stops retries and official-format refusal remains actionable and safe", async ({ page }) => {
  const s = await setup(page, 1);
  s.batches.push(makeBatch(3000, [id(100)], id(4000), 1));
  await page.goto("/#/batches");
  await page.getByLabel("Сохранённые пакеты", { exact: true }).selectOption(id(3000));
  await expect(page.getByRole("heading", { name: "Пакет завершён" })).toBeVisible();
  s.readFailure = true;
  await page.getByRole("button", { name: "Обновить пакет", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("DATABASE_UNAVAILABLE");
  const count = s.reads.length;
  await page.waitForTimeout(2300);
  expect(s.reads).toHaveLength(count);
  s.readFailure = false;
  await page.getByRole("button", { name: "Повторить", exact: true }).click();
  await expect(page.getByRole("alert")).toHaveCount(0);
  s.exportConflict = true;
  await page.getByRole("button", { name: "Скачать results.json", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("несовместим");
  expect(s.consoleLines.join(" ")).toContain("event=ui_operation_failed status=409 error=SUBMISSION_CHECKLIST_INCOMPATIBLE");
  expect(s.consoleLines.join(" ")).not.toContain("PRIVATE_BATCH_SERVER_MARKER");
  await expect(page.locator("body")).not.toContainText("PRIVATE_BATCH_SERVER_MARKER");
});

test("a late response cannot replace the selected batch after A → B → A", async ({ page }) => {
  const s = await setup(page, 1);
  const a = makeBatch(3000, [id(100)]), b = makeBatch(3001, [id(100)], id(4001), 1);
  s.batches.push(a, b);
  let reads = 0, release!: () => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route(`**/api/v1/evaluation-batches/${a.id}`, async (route) => {
    ++reads;
    if (reads === 1) {
      await gate;
      return route.fulfill({ json: makeBatch(3000, [id(100)], id(4000), 1) });
    }
    return route.fulfill({ json: a });
  });
  await page.goto("/#/batches");
  await page.getByLabel("Сохранённые пакеты", { exact: true }).selectOption(a.id);
  await expect.poll(() => reads).toBe(1);
  await page.getByLabel("Сохранённые пакеты", { exact: true }).selectOption(b.id);
  await expect(page.getByRole("heading", { name: "Пакет завершён" })).toBeVisible();
  await page.getByLabel("Сохранённые пакеты", { exact: true }).selectOption(a.id);
  await expect(page.getByRole("heading", { name: "Пакет обрабатывается" })).toBeVisible();
  release();
  await page.waitForTimeout(200);
  await expect(page.getByRole("heading", { name: "Пакет обрабатывается" })).toBeVisible();
  await expect(page.locator(".batch-counts")).toContainText("Ошибок0");
  expect(s.creates).toHaveLength(0);
});

test("pending creation blocks duplicate launch and scope changes do not create a batch", async ({ page }) => {
  const s = await setup(page, 2);
  let release!: () => void, started = false;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/v1/evaluation-batches", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    started = true; await gate; return route.fallback();
  });
  await prepare(page);
  await page.getByLabel("Диалоги в новом пакете").getByRole("checkbox").first().uncheck();
  await expect(page.getByText("Найдено: 2 · выбрано: 1", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "Запустить пакет · 1", exact: true }).click();
  await expect.poll(() => started).toBe(true);
  await expect(page.getByLabel("Группа набора", { exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "Создаём пакет…", exact: true })).toBeDisabled();
  release();
  await expect(page.getByRole("heading", { name: "Пакет обрабатывается" })).toBeVisible();
  expect(s.creates).toHaveLength(1);
  expect(s.creates[0].conversation_ids).toEqual([s.conversations[1].id]);
  await page.getByLabel("Группа набора", { exact: true }).fill("OTHER");
  await expect(page.getByRole("button", { name: /^Запустить пакет/ })).toHaveCount(0);
  expect(s.creates).toHaveLength(1);
});

test("all-failed export stays downloadable and pending export suppresses duplicate clicks on a narrow screen", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  const s = await setup(page, 1);
  s.batches.push(makeBatch(3000, [id(100)], id(4000), 1));
  let release!: () => void, started = false;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/v1/submission-exports", async (route) => {
    started = true; await gate; return route.fallback();
  });
  await page.goto("/#/batches");
  await page.getByLabel("Сохранённые пакеты", { exact: true }).selectOption(id(3000));
  await page.getByRole("button", { name: "Скачать results.json", exact: true }).click();
  await expect.poll(() => started).toBe(true);
  await expect(page.getByRole("button", { name: "Готовим файл…", exact: true })).toBeDisabled();
  await expect(page.getByLabel("Название команды", { exact: true })).toBeDisabled();
  const download = page.waitForEvent("download");
  release(); await download;
  expect(s.exports).toHaveLength(1);
  expect(s.creates).toHaveLength(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth)).toBe(false);
});

test("a successful checklist list cannot hide a concurrent version-loading failure", async ({ page }) => {
  await setup(page, 1);
  const checklist = fixture("checklist.response.json");
  let listHeld = false, holdList = false, release!: () => void, failDetail = true;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/api/v1/checklists?**", async (route) => {
    if (holdList) { listHeld = true; await gate; }
    return route.fallback();
  });
  await page.route(`**/api/v1/checklists/${checklist.id}`, async (route) => {
    if (!failDetail) return route.fallback();
    return route.fulfill({ status: 503, json: { error: { code: "DATABASE_UNAVAILABLE", message: "PRIVATE_BATCH_SERVER_MARKER", details: [] } } });
  });
  await page.goto("/#/batches");
  await expect(page.getByRole("alert")).toContainText("DATABASE_UNAVAILABLE");
  holdList = true;
  await page.getByRole("button", { name: "Повторить", exact: true }).click();
  await expect.poll(() => listHeld).toBe(true);
  await expect(page.getByRole("alert")).toContainText("DATABASE_UNAVAILABLE");
  holdList = false; release();
  await expect(page.getByRole("option", { name: "Не удалось загрузить версии", exact: true })).toHaveCount(1);
  await expect(page.getByRole("alert")).toContainText("DATABASE_UNAVAILABLE");
  failDetail = false;
  await page.getByRole("button", { name: "Повторить", exact: true }).click();
  await expect(page.getByLabel("Версия чек-листа пакета")).toHaveValue(version);
  await expect(page.getByRole("alert")).toHaveCount(0);
});
