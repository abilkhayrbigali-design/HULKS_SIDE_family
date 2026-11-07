import { test, expect, type Page, type Route } from "@playwright/test";
import { readFileSync } from "node:fs";
const fixture = (file: string) =>
  JSON.parse(
    readFileSync(
      new URL(`../../data/fixtures/synthetic/${file}`, import.meta.url),
      "utf8",
    ),
  );
const pageOf = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: 100,
  offset: 0,
});
// Explicit test-only API interception: the product has no mock evaluation fallback.
async function mockAPI(
  page: Page,
  o: {
    completed?: boolean;
    noKey?: boolean;
    poll?: boolean;
    conflict?: boolean;
    languages?: boolean;
  } = {},
) {
  const checklist = fixture("checklist-version.response.json"),
    detail = fixture("checklist.response.json"),
    conversation = fixture("conversation.response.json");
  let evaluation = fixture("evaluation.completed.json"),
    conversations = fixture("conversations.response.json").items;
  let appeals: any[] = [];
  let version = 1,
    conflicted = false,
    polls = 0;
  const posts: { path: string; body: any }[] = [],
    observed: string[] = [],
    consoleLines: string[] = [];
  page.on("console", (m) => {
    if (["error", "warning"].includes(m.type())) consoleLines.push(m.text());
  });
  if (o.languages)
    conversations = ["RU", "KZ", "EN"].map((language, i) => ({
      ...conversations[0],
      id: `conv-${i}`,
      external_id: `synthetic-${language}`,
      language,
    }));
  await page.route("**/api/v1/**", async (route: Route) => {
    const req = route.request(),
      url = new URL(req.url()),
      path = url.pathname.replace("/api/v1", "");
    observed.push(req.url());
    const body = req.method() === "POST" ? req.postDataJSON() : undefined;
    if (body) posts.push({ path, body });
    const json = (value: unknown, status = 200) =>
      route.fulfill({ status, json: value });
    const fail = (code: string, status: number) =>
      json(
        { error: { code, message: "PRIVATE_SERVER_MARKER", details: [] } },
        status,
      );
    if (path === "/conversations" && req.method() === "GET") {
      const lang = url.searchParams.get("language");
      return json(
        pageOf(conversations.filter((c: any) => !lang || c.language === lang)),
      );
    }
    if (path === "/conversations/import")
      return json({
        ...fixture("import.response.json"),
        received: body.records.length,
      });
    if (path === "/datasets/import") return fail("DATASET_UNAVAILABLE", 502);
    if (path.startsWith("/conversations/"))
      return json({
        ...conversation,
        current_transcript_version_id: "latest-different-version",
        transcript_version_id:
          url.searchParams.get("transcript_version_id") ??
          "latest-different-version",
      });
    if (path === "/checklists" && req.method() === "GET")
      return json(fixture("checklists.response.json"));
    if (path === "/checklists" && req.method() === "POST")
      return json(
        { ...checklist, criteria: body.criteria, name: body.name },
        201,
      );
    if (path.endsWith("/versions") && req.method() === "POST") {
      if (o.conflict && !conflicted) {
        conflicted = true;
        version = 2;
        return fail("VERSION_CONFLICT", 409);
      }
      return json(
        {
          ...checklist,
          version_number: ++version,
          id: `version-${version}`,
          criteria: body.criteria,
        },
        201,
      );
    }
    if (path.startsWith("/checklists/"))
      return json({
        ...detail,
        current_version: { ...checklist, version_number: version },
        versions: [{ ...checklist, version_number: version }],
      });
    if (path.startsWith("/checklist-versions/")) return json(checklist);
    if (path === "/evaluations" && req.method() === "GET")
      return json(pageOf(o.completed ? [evaluation] : []));
    if (path === "/evaluations" && req.method() === "POST")
      return o.noKey
        ? fail("AI_NOT_CONFIGURED", 503)
        : json(o.poll ? fixture("evaluation.queued.json") : evaluation, 202);
    if (path.startsWith("/evaluations/") && path.endsWith("/appeals")) {
      const result = evaluation.final.criteria.find(
        (c: any) => c.criterion_id === body.criterion_id,
      );
      const appeal = {
        ...fixture("appeal.open.json"),
        id: `appeal-${appeals.length + 1}`,
        criterion_id: body.criterion_id,
        comment: body.comment,
        current_revision: evaluation.revision,
        base_revision: evaluation.revision,
        original: evaluation.original.criteria.find(
          (c: any) => c.criterion_id === body.criterion_id,
        ),
        current: result,
      };
      appeals = [appeal, ...appeals];
      return json(appeal, 201);
    }
    if (path.startsWith("/evaluations/"))
      return json(
        o.poll && polls++ === 0
          ? fixture("evaluation.running.json")
          : evaluation,
      );
    if (path === "/appeals") return json(pageOf(appeals));
    if (path.endsWith("/decisions")) {
      const appeal = appeals.find((a) => path.includes(a.id));
      if (o.conflict) return fail("REVISION_CONFLICT", 409);
      evaluation = structuredClone(evaluation);
      evaluation.revision++;
      if (body.action === "override") {
        const result = evaluation.final.criteria.find(
          (c: any) => c.criterion_id === appeal.criterion_id,
        );
        Object.assign(result, {
          answer: body.answer,
          applicability: body.applicability,
          evidence: body.evidence,
          explanation: body.reason,
        });
        evaluation.final.total = 100;
      }
      appeal.status = "resolved";
      appeal.current_revision = evaluation.revision;
      appeal.decision = {
        id: "decision",
        appeal_id: appeal.id,
        action: body.action,
        reason: body.reason,
        expected_revision: body.expected_revision,
        created_at: evaluation.created_at,
        result: appeal.current,
      };
      return json({ appeal, evaluation });
    }
    return fail("NOT_FOUND", 404);
  });
  return { posts, observed, consoleLines, checklist, conversation, evaluation };
}
test("RU/KZ/EN filters, explicit example import, no-key error and safe console", async ({
  page,
}) => {
  const s = await mockAPI(page, { noKey: true, languages: true });
  await page.goto("/");
  await page.getByLabel("Язык", { exact: true }).selectOption("KZ");
  await expect(
    page.getByRole("link", { name: "synthetic-KZ", exact: true }),
  ).toBeVisible();
  await expect(
    page.getByRole("link", { name: "synthetic-RU", exact: true }),
  ).toHaveCount(0);
  await page.getByLabel("Язык", { exact: true }).selectOption("EN");
  await expect(
    page.getByRole("link", { name: "synthetic-EN", exact: true }),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Импортировать диалоги", exact: true })
    .click();
  await page.getByRole("button", { name: "JSON-файл", exact: true }).click();
  await page
    .getByRole("button", { name: "Загрузить учебный пример", exact: true })
    .click();
  await expect(
    page.getByText("Импорт завершён", { exact: false }),
  ).toBeVisible();
  expect(s.posts[0].body.records[0].conversation_id).toContain("учебный");
  await page.getByRole("link", { name: "synthetic-EN", exact: true }).click();
  await page
    .getByRole("button", { name: "Оценить диалог", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("AI_NOT_CONFIGURED");
  await expect(page.locator(".score-overview")).toHaveCount(0);
  expect(s.consoleLines.join(" ")).toContain(
    "event=ui_operation_failed status=503 error=AI_NOT_CONFIGURED",
  );
  expect(s.consoleLines.join(" ")).not.toContain("PRIVATE_SERVER_MARKER");
  await expect(page.locator("body")).not.toContainText("PRIVATE_SERVER_MARKER");
});
test("frozen evidence, override and confirm preserve original score after reload", async ({
  page,
}) => {
  const s = await mockAPI(page, { completed: true });
  await page.goto(
    `/#/dialogues/${s.conversation.id}?evaluation=${s.evaluation.id}`,
  );
  await expect(page.getByText("Архивная версия оценки")).toBeVisible();
  expect(
    s.observed.some((u) =>
      u.includes(`transcript_version_id=${s.evaluation.transcript_version_id}`),
    ),
  ).toBe(true);
  await page
    .getByRole("button", { name: "m0001–m0004", exact: true })
    .first()
    .click();
  await expect(page.locator(".message.highlight")).toHaveCount(4);
  await expect(page.locator("#message-m0001")).toBeFocused();
  await expect(
    page.getByText("Синтетическая оценка · тестовые данные"),
  ).toBeVisible();
  await page
    .getByRole("button", { name: "Оспорить", exact: true })
    .nth(1)
    .click();
  await page
    .getByRole("textbox", {name: "Комментарий", exact: true})
    .fill("Проверить следующий шаг");
  await page.getByRole("button", { name: "Отправить апелляцию" }).click();
  await page.getByText("Рассмотреть как проверяющий", { exact: true }).click();
  await page.getByRole("combobox", {name: "Решение", exact: true}).selectOption("override");
  await page.getByRole("combobox", {name: "Новый ответ", exact: true}).selectOption("10");
  await page.getByRole("combobox", {name: "Вид доказательства", exact: true}).selectOption("range");
  await page.getByRole("combobox", {name: "Начало диапазона", exact: true}).selectOption("m0001");
  await page.getByRole("combobox", {name: "Конец диапазона", exact: true}).selectOption("m0004");
  await page
    .getByRole("textbox", {name: "Причина решения", exact: true})
    .fill("Действие подтверждено полным диапазоном");
  await page.getByRole("button", { name: "Сохранить решение" }).click();
  await expect(
    page.getByText("Оценка изменена", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(".score-main")).toContainText("100,00");
  await expect(page.locator(".score-secondary")).toContainText("70,00");
  expect(
    s.posts.find((p) => p.path.endsWith("/decisions"))?.body,
  ).toMatchObject({ expected_revision: 0, answer: 10, action: "override" });
  await page
    .getByRole("textbox", {name: "Комментарий", exact: true})
    .fill("Повторная проверка");
  await page.getByRole("button", { name: "Отправить апелляцию" }).click();
  await page.getByText("Рассмотреть как проверяющий", { exact: true }).click();
  await page.getByRole("textbox", {name: "Причина решения", exact: true}).fill("Подтверждено");
  await page.getByRole("button", { name: "Сохранить решение" }).click();
  await expect(
    page.getByText("Оценка подтверждена", { exact: true }),
  ).toBeVisible();
  expect(
    s.posts.filter((p) => p.path.endsWith("/decisions"))[1].body,
  ).toMatchObject({ expected_revision: 1, action: "confirm" });
  await page.reload();
  await expect(page.locator(".score-main")).toContainText("100,00");
  await expect(page.locator(".score-secondary")).toContainText("70,00");
  await page
    .getByRole("button", { name: "Апелляции и история", exact: true })
    .click();
  await expect(page.locator(".appeal-card")).toHaveCount(2);
  await page.screenshot({
    path: "test-results/cqa-result.png",
    fullPage: true,
  });
});
test("checklist dynamic fields survive version conflict", async ({ page }) => {
  const s = await mockAPI(page, { conflict: true });
  await page.goto("/#/checklists");
  await page
    .getByRole("button", { name: /Открыть критерии и историю версий/ })
    .click();
  const card = page.locator(".criterion-editor").first();
  await card
    .getByRole("textbox", {name: "Название", exact: true})
    .fill("Изменённый пользовательский критерий");
  await card
    .getByRole("textbox", {name: "Инструкция для AI", exact: true})
    .fill("Проверять оператора и доказательства");
  await page
    .getByRole("button", { name: "Добавить критерий", exact: true })
    .click();
  const added = page.locator(".criterion-editor").last();
  await added.getByRole("textbox", {name: "Название", exact: true}).fill("Новый флаг");
  await added
    .getByRole("textbox", {name: "Инструкция для AI", exact: true})
    .fill("Обнаружить событие");
  await added.getByRole("combobox", {name: "Тип", exact: true}).selectOption("flag");
  await expect(added.getByLabel("Вес", { exact: true })).toHaveValue("0");
  await page
    .getByRole("button", { name: "Сохранить новую версию", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("VERSION_CONFLICT");
  await expect(card.getByRole("textbox", {name: "Название", exact: true})).toHaveValue(
    "Изменённый пользовательский критерий",
  );
  await expect(added.getByRole("textbox", {name: "Название", exact: true})).toHaveValue(
    "Новый флаг",
  );
  await page
    .getByRole("button", {
      name: "Обновить базовый номер без замены правок",
      exact: true,
    })
    .click();
  await page
    .getByRole("button", { name: "Сохранить новую версию", exact: true })
    .click();
  await expect(
    page.getByText("Версия сохранена", { exact: true }),
  ).toBeVisible();
  expect(
    s.posts
      .filter((p) => p.path.endsWith("/versions"))
      .map((p) => p.body.expected_version_number),
  ).toEqual([1, 2]);
  expect(s.posts.at(-1)?.body.criteria.at(-1)).toMatchObject({
    type: "flag",
    weight: 0,
    allow_na: false,
    scale: null,
  });
});
test("malformed JSON, upstream failure and modal keyboard accessibility", async ({
  page,
}) => {
  const s = await mockAPI(page);
  await page.goto("/");
  await page
    .getByRole("button", { name: "Импортировать диалоги", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Получить набор", exact: true })
    .click();
  await expect(page.getByRole("alert")).toContainText("DATASET_UNAVAILABLE");
  await page.getByRole("button", { name: "JSON-файл", exact: true }).click();
  await page
    .getByLabel("Выбрать JSON-файл")
    .setInputFiles({
      name: "broken.json",
      mimeType: "application/json",
      buffer: Buffer.from("{PRIVATE_IMPORT_MARKER"),
    });
  await expect(page.getByRole("alert")).toContainText("Проверьте синтаксис");
  expect(s.consoleLines.join(" ")).not.toContain("PRIVATE_IMPORT_MARKER");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);
  await expect(
    page.getByRole("button", { name: "Импортировать диалоги", exact: true }),
  ).toBeFocused();
});
test("queued evaluation polls to completed", async ({ page }) => {
  const s = await mockAPI(page, { poll: true });
  await page.goto(`/#/dialogues/${s.conversation.id}`);
  await page
    .getByRole("button", { name: "Оценить диалог", exact: true })
    .click();
  await expect(page.getByText("AI анализирует диалог и проверяет доказательства…")).toBeVisible();
  await expect(page.locator(".score-main")).toContainText("70,00", {
    timeout: 12000,
  });
  await expect(page.locator(".criterion-result")).toHaveCount(4);
});
test("mobile navigation has no page overflow", async ({ page }) => {
  await mockAPI(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await page.getByRole("button", { name: "Открыть навигацию" }).click();
  await page.getByRole("link", { name: "Чек-листы", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Чек-листы", exact: true }),
  ).toBeVisible();
  await expect(page.locator(".sidebar")).not.toHaveClass(/is-open/);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/cqa-mobile.png",
    fullPage: true,
  });
});
