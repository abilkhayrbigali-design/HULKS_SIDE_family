import { test, expect, type Page } from "@playwright/test";
import { fixture, mockWorkspaceAPI, pageOf, mockAPI } from "./helpers/mock-api";
const viewport = (page: Page) =>
  page.locator('.transcript-scroll [data-slot="scroll-area-viewport"]');
async function archive(page: Page) {
  const data = await mockWorkspaceAPI(page);
  await page.goto(
    `/#/dialogues/${data.current.id}?evaluation=${data.archivedEvaluation.id}`,
  );
  await expect(page.locator(".score-main")).toContainText("69,57");
  return data;
}
async function twoConversations(page: Page) {
  const data = await mockWorkspaceAPI(page);
  const b = {
    ...data.current,
    id: "72000000-0000-4000-8000-000000000002",
    external_id: "SECOND_SYNTHETIC_DIALOGUE",
  };
  const bRun = {
    ...data.currentEvaluation,
    id: "72000000-0000-4000-8000-000000000032",
    conversation_id: b.id,
  };
  await page.route("**/api/v1/conversations?*", (route) =>
    route.fulfill({ json: pageOf([data.current, b]) }),
  );
  await page.route(`**/api/v1/conversations/${b.id}*`, (route) =>
    route.fulfill({ json: b }),
  );
  await page.route("**/api/v1/evaluations?*", (route) =>
    new URL(route.request().url()).searchParams.get("conversation_id") === b.id
      ? route.fulfill({ json: pageOf([bRun]) })
      : route.fallback(),
  );
  await page.route(`**/api/v1/evaluations/${bRun.id}`, (route) =>
    route.fulfill({ json: bRun }),
  );
  return { ...data, b, bRun };
}
test("workspace pins archived snapshots, arbitrary criteria and original weights", async ({
  page,
}) => {
  const data = await archive(page);
  await expect(page.locator(".criterion-result")).toHaveCount(12);
  await expect(page.locator(".message")).toHaveCount(120);
  await expect(page.locator(".score-secondary")).toContainText("65,22");
  await expect(page.locator(".gross-warning")).toBeVisible();
  await page
    .locator(".criterion-select")
    .filter({ hasText: "Идентификация" })
    .click();
  await expect(page.locator("#message-m0008")).toHaveClass(/highlight/);
  await expect(page.locator("#message-m0008")).toContainText("Система");
  await expect(page.locator(".message.highlight")).toHaveCount(4);
  await expect(
    page
      .locator(".criterion-result")
      .filter({ hasText: "Идентификация" })
      .locator(".criterion-weight"),
  ).toHaveText("20");
  expect(
    data.requests.some((url) =>
      url.includes(
        `transcript_version_id=${data.archived.transcript_version_id}`,
      ),
    ),
  ).toBe(true);
  expect(data.requests.some((url) => url.includes(data.v1.id))).toBe(true);
  await page
    .getByRole("tab", { name: "Апелляции и история", exact: true })
    .click();
  await expect(page.locator(".decision-result").last()).toContainText("Нет");
  await expect(page.locator(".appeal-comparison").last()).toContainText("Да");
  await page.getByRole("tab", { name: "Запуски", exact: true }).click();
  await page
    .locator(`.history-row[href*="${data.currentEvaluation.id}"]`)
    .click();
  await expect(page.locator(".criterion-result")).toHaveCount(13);
  await expect(page.locator(".score-main")).toContainText("100,00");
  await expect(page.locator(".gross-warning")).toHaveCount(0);
  await page.screenshot({
    path: "test-results/workspace-dark.png",
    fullPage: true,
  });
});
test("neutral selection, theme, keyboard resize and collapse preserve evidence", async ({
  page,
}) => {
  const data = await archive(page);
  await page
    .locator(".criterion-select")
    .filter({ hasText: "Завершение" })
    .click();
  await expect(page.locator("#message-m0118")).toHaveClass(/highlight/);
  const hash = await page.evaluate(() => location.hash);
  await page.getByRole("button", { name: "Светлая тема", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await expect(page.locator("#message-m0118")).toHaveClass(/highlight/);
  expect(await page.evaluate(() => location.hash)).toBe(hash);
  const selected = await page
    .locator(".criterion-result.is-selected")
    .evaluate((el) => getComputedStyle(el).backgroundColor);
  const evidence = await page
    .locator("#message-m0118")
    .evaluate((el) => getComputedStyle(el).backgroundColor);
  expect(selected).not.toBe(evidence);
  const handle = page.getByRole("separator", {
    name: "Изменить ширину очереди",
    exact: true,
  });
  const before = (await page.locator("#queue-panel").boundingBox())!.width;
  await handle.focus();
  await handle.press("ArrowRight");
  await expect
    .poll(async () => (await page.locator("#queue-panel").boundingBox())!.width)
    .not.toBe(before);
  await page
    .getByRole("button", { name: "Свернуть очередь", exact: true })
    .click();
  await expect(page.locator("#queue-panel")).toHaveCSS("width", "0px");
  await page
    .getByRole("button", { name: "Показать очередь", exact: true })
    .click();
  await expect(page.locator("#queue-panel")).not.toHaveCSS("width", "0px");
  await expect(page.locator("#message-m0118")).toHaveClass(/highlight/);
  await expect(page.locator(".score-main")).toContainText("69,57");
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  expect(data.requests.length).toBeGreaterThan(0);
  await page.screenshot({
    path: "test-results/workspace-light.png",
    fullPage: true,
  });
});
test("narrow evidence scroll has priority over restored transcript scroll", async ({
  page,
}) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await archive(page);
  await viewport(page).evaluate((element) => {
    element.scrollTop = 1000;
  });
  await page.getByRole("tab", { name: "Качество", exact: true }).click();
  await page
    .locator(".criterion-select")
    .filter({ hasText: "Завершение" })
    .click();
  await expect(
    page.getByRole("tab", { name: "Диалог", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect
    .poll(async () =>
      page.locator("#message-m0118").evaluate((element) => {
        const box = element.getBoundingClientRect(),
          vp = element
            .closest('[data-slot="scroll-area-viewport"]')!
            .getBoundingClientRect();
        return box.top >= vp.top && box.bottom <= vp.bottom;
      }),
    )
    .toBe(true);
  await expect(page.locator("#message-m0118")).toBeFocused();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".workspace")).toHaveAttribute(
    "data-active-pane",
    "transcript",
  );
  await expect(page.locator("#message-m0118")).toHaveClass(/highlight/);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: "test-results/workspace-narrow.png",
    fullPage: true,
  });
});
test("failed selected-run load never presents an old successful score", async ({
  page,
}) => {
  const data = await mockWorkspaceAPI(page);
  await page.goto(
    `/#/dialogues/${data.current.id}?evaluation=${data.currentEvaluation.id}`,
  );
  await expect(page.locator(".score-main")).toContainText("100,00");
  await page.route(
    `**/api/v1/evaluations/${data.archivedEvaluation.id}`,
    (route) =>
      route.fulfill({
        status: 503,
        json: {
          error: {
            code: "DATABASE_UNAVAILABLE",
            message: "PRIVATE_SOURCE_MARKER",
            details: [],
          },
        },
      }),
  );
  await page.getByRole("tab", { name: "Запуски", exact: true }).click();
  await page
    .locator(`.history-row[href*="${data.archivedEvaluation.id}"]`)
    .click();
  await expect(page.getByRole("alert")).toContainText("DATABASE_UNAVAILABLE");
  await expect(page.locator(".score-main")).toHaveCount(0);
  await expect(page.locator(".message")).toHaveCount(0);
  await page.setViewportSize({ width: 800, height: 900 });
  await page.getByRole("tab", { name: "Качество", exact: true }).click();
  await expect(page.getByRole("alert")).toContainText("DATABASE_UNAVAILABLE");
  expect(data.consoleLines.join(" ")).not.toContain("PRIVATE_SOURCE_MARKER");
});
test("late evaluation creation cannot navigate B or A-B-A back to an obsolete run", async ({
  page,
}) => {
  const data = await twoConversations(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route("**/api/v1/evaluations", async (route) => {
    if (route.request().method() !== "POST") return route.fallback();
    await gate;
    await route.fulfill({
      status: 202,
      json: {
        ...data.archivedEvaluation,
        id: "73000000-0000-4000-8000-000000000099",
      },
    });
  });
  await page.goto(
    `/#/dialogues/${data.current.id}?evaluation=${data.archivedEvaluation.id}`,
  );
  await expect(page.locator(".score-main")).toContainText("69,57");
  await page.getByText("Настроить новый анализ", { exact: true }).click();
  await page
    .getByRole("button", { name: "Оценить диалог", exact: true })
    .click();
  await page.locator(`.queue-item[href*="${data.b.id}"]`).click();
  await expect(page.locator(".score-main")).toContainText("100,00");
  await page.locator(`.queue-item[href*="${data.current.id}"]`).click();
  await expect(page.locator(".score-main")).toContainText("100,00");
  const hash = await page.evaluate(() => location.hash);
  release();
  await page.waitForTimeout(150);
  expect(await page.evaluate(() => location.hash)).toBe(hash);
  await expect(page.locator(".criterion-result")).toHaveCount(13);
});
test("late appeal decision cannot combine A scores with B transcript", async ({
  page,
}) => {
  const data = await twoConversations(page);
  const open = {
    ...fixture("workspace/appeals.page.json").items[0],
    status: "open",
    decision: null,
  };
  await page.route("**/api/v1/appeals?*", (route) =>
    route.fulfill({ json: pageOf([open]) }),
  );
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(`**/api/v1/appeals/${open.id}/decisions`, async (route) => {
    await gate;
    await route.fulfill({
      json: fixture("workspace/decision.override.response.json"),
    });
  });
  await page.goto(
    `/#/dialogues/${data.current.id}?evaluation=${data.archivedEvaluation.id}`,
  );
  await expect(page.locator(".score-main")).toContainText("69,57");
  await page
    .getByRole("tab", { name: "Апелляции и история", exact: true })
    .click();
  await page.getByText("Рассмотреть как проверяющий", { exact: true }).click();
  await page
    .getByRole("textbox", { name: "Причина решения", exact: true })
    .fill("Synthetic deferred decision");
  await page
    .getByRole("button", { name: "Сохранить решение", exact: true })
    .click();
  await page.locator(`.queue-item[href*="${data.b.id}"]`).click();
  await expect(page.locator(".score-main")).toContainText("100,00");
  release();
  await page.waitForTimeout(150);
  await expect(page.locator(".transcript-heading h1")).toHaveText(
    data.b.external_id,
  );
  await expect(page.locator(".score-main")).toContainText("100,00");
  await expect(page.locator(".criterion-result")).toHaveCount(13);
});

test("narrow quality close returns focus to transcript without losing selection", async ({
  page,
}) => {
  await page.setViewportSize({ width: 800, height: 900 });
  await archive(page);
  await page.getByRole("tab", { name: "Качество", exact: true }).click();
  await page
    .locator(".criterion-select")
    .filter({ hasText: "Идентификация" })
    .click();
  await page.getByRole("tab", { name: "Качество", exact: true }).click();
  await page
    .locator(".quality-heading")
    .getByRole("button", { name: "Свернуть оценку", exact: true })
    .click();
  await expect(
    page.getByRole("tab", { name: "Диалог", exact: true }),
  ).toHaveAttribute("aria-selected", "true");
  await expect(
    page.getByRole("tab", { name: "Диалог", exact: true }),
  ).toBeFocused();
  await expect(page.locator("#message-m0008")).toHaveClass(/highlight/);
});
test("appeal drafts are isolated by criterion, selected run and conversation", async ({
  page,
}) => {
  const data = await twoConversations(page);
  await page.goto(
    `/#/dialogues/${data.current.id}?evaluation=${data.archivedEvaluation.id}`,
  );
  await expect(page.locator(".score-main")).toContainText("69,57");
  await page
    .getByRole("tab", { name: "Апелляции и история", exact: true })
    .click();
  const picker = page.getByRole("combobox", {
    name: "Спорный критерий",
    exact: true,
  });
  const comment = page.getByRole("textbox", {
    name: "Комментарий",
    exact: true,
  });
  await picker.selectOption("contact");
  await comment.fill("Synthetic contact draft");
  await picker.selectOption("needs");
  await expect(comment).toHaveValue("");
  await comment.fill("Synthetic needs draft");
  await picker.selectOption("contact");
  await expect(comment).toHaveValue("Synthetic contact draft");
  await page.getByRole("button", { name: "Светлая тема", exact: true }).click();
  await expect(comment).toHaveValue("Synthetic contact draft");
  await page.locator(`.queue-item[href*="${data.b.id}"]`).click();
  await expect(page.locator(".score-main")).toContainText("100,00");
  await page
    .getByRole("tab", { name: "Апелляции и история", exact: true })
    .click();
  await expect(comment).toHaveValue("");
  await page.locator(`.queue-item[href*="${data.current.id}"]`).click();
  await expect(page.locator(".score-main")).toContainText("100,00");
  await page.getByRole("tab", { name: "Запуски", exact: true }).click();
  await page
    .locator(`.history-row[href*="${data.archivedEvaluation.id}"]`)
    .click();
  await expect(page.locator(".score-main")).toContainText("69,57");
  await page
    .getByRole("tab", { name: "Апелляции и история", exact: true })
    .click();
  await expect(comment).toHaveValue("Synthetic contact draft");
  await picker.selectOption("needs");
  await expect(comment).toHaveValue("Synthetic needs draft");
  expect(
    await page.evaluate(() =>
      Object.keys(localStorage).some((key) => /draft|appeal/i.test(key)),
    ),
  ).toBe(false);
});

test("inactive and collapsed panes expose no hidden keyboard targets", async ({
  page,
}) => {
  await archive(page);
  const handle = page.getByRole("separator", {
    name: "Изменить ширину очереди",
    exact: true,
  });
  await handle.focus();
  await handle.press("Home");
  await expect(
    page.getByRole("button", { name: "Показать очередь", exact: true }),
  ).toBeVisible();
  await expect(page.locator("#queue-panel")).toHaveAttribute("inert", "");
  await page
    .getByRole("button", { name: "Показать очередь", exact: true })
    .click();
  await page
    .getByRole("button", { name: "Свернуть очередь", exact: true })
    .click();
  await expect(page.locator("#queue-panel")).toHaveAttribute("inert", "");
  await expect(
    page.getByRole("button", { name: "Импортировать диалоги", exact: true }),
  ).toHaveCount(0);
  await page
    .getByRole("button", { name: "Свернуть оценку", exact: true })
    .first()
    .click();
  await expect(page.locator("#quality-panel")).toHaveAttribute("inert", "");
  await page
    .getByRole("button", { name: "Открыть качество диалога", exact: true })
    .click();
  await expect(page.locator("#quality-panel")).not.toHaveAttribute("inert", "");
  await expect(page.locator(".score-main")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("tab", { name: "Качество", exact: true }).click();
  await page
    .locator(".criterion-select")
    .filter({ hasText: "Завершение" })
    .click();
  await expect(page.locator("#quality-panel")).toHaveAttribute("inert", "");
  expect(
    await page
      .locator("#quality-panel button")
      .evaluateAll(
        (elements) =>
          elements.filter(
            (el) =>
              getComputedStyle(el).visibility === "visible" &&
              el.getClientRects().length > 0,
          ).length,
      ),
  ).toBe(0);
  await page.getByRole("tab", { name: "Диалог", exact: true }).focus();
  for (let i = 0; i < 7; i++) {
    await page.keyboard.press("Tab");
    expect(
      await page.evaluate(
        () => document.activeElement?.closest("[inert]") !== null,
      ),
    ).toBe(false);
  }
});
test("quality stays scrollable at short heights and with long review warnings", async ({
  page,
}) => {
  const data = await mockWorkspaceAPI(page);
  const run = {
    ...data.archivedEvaluation,
    review_required: true,
    review_reasons: Array.from(
      { length: 20 },
      (_, i) => `Synthetic review reason ${i + 1}: requires a human check.`,
    ),
  };
  await page.route(`**/api/v1/evaluations/${run.id}`, (route) =>
    route.fulfill({ json: run }),
  );
  await page.setViewportSize({ width: 1280, height: 600 });
  await page.goto(`/#/dialogues/${data.current.id}?evaluation=${run.id}`);
  await expect(page.locator(".score-main")).toContainText("69,57");
  await page.getByText("Настроить новый анализ", { exact: true }).click();
  const quality = page.locator(
    '.quality-body-scroll>[data-slot="scroll-area-viewport"]',
  );
  await quality.evaluate((el) => {
    el.scrollTop = el.scrollHeight;
  });
  const appealsTab = page.getByRole("tab", {
    name: "Апелляции и история",
    exact: true,
  });
  await appealsTab.scrollIntoViewIfNeeded();
  await expect(appealsTab).toBeInViewport({ ratio: 1 });
  await page.getByRole("tab", { name: /Критерии/ }).click();
  await page.locator(".appeal-criterion-action").scrollIntoViewIfNeeded();
  await expect(page.locator(".appeal-criterion-action")).toBeInViewport({
    ratio: 1,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollHeight <= innerHeight,
    ),
  ).toBe(true);
});
test("queue filters and selected route survive a visit to checklists", async ({
  page,
}) => {
  const data = await mockWorkspaceAPI(page);
  await page.goto(
    `/#/dialogues/${data.current.id}?evaluation=${data.archivedEvaluation.id}`,
  );
  await expect(page.locator(".score-main")).toContainText("69,57");
  await page.getByLabel("Язык", { exact: true }).selectOption("KZ");
  const before = await page.evaluate(() => location.hash);
  await page.getByRole("link", { name: "Чек-листы", exact: true }).click();
  await expect(
    page.getByRole("heading", { name: "Чек-листы", exact: true }),
  ).toBeVisible();
  await page.getByRole("link", { name: "Диалоги", exact: true }).click();
  await expect(page.getByLabel("Язык", { exact: true })).toHaveValue("KZ");
  expect(await page.evaluate(() => location.hash)).toBe(before);
});
test("partial scale is amber with maximum while arbitrary flags stay neutral", async ({
  page,
}) => {
  const basic = await mockAPI(page, { completed: true });
  await page.goto(`/#/dialogues/${basic.conversation.id}`);
  await expect(page.locator(".score-main")).toContainText("70,00");
  const partial = page
    .locator(".criterion-result")
    .filter({ hasText: "Понятность инструкции" })
    .locator(".answer-badge");
  await expect(partial).toContainText("5/10");
  await expect(partial).toHaveClass(/partial/);
  await expect(partial).not.toHaveClass(/positive/);
});
test("custom flag and long queue IDs keep semantics and layout bounds", async ({
  page,
}) => {
  const data = await mockWorkspaceAPI(page);
  await page.goto(`/#/dialogues/${data.current.id}`);
  await expect(page.locator(".score-main")).toContainText("100,00");
  const rule = data.v2.criteria.find(
    (criterion: { id: string }) => criterion.id === "supervisor_offer",
  );
  const flag = page
    .locator(".criterion-result")
    .filter({ hasText: rule.name })
    .locator(".answer-badge");
  await expect(flag).toHaveClass(/neutral/);
  await expect(flag).toContainText("Обнаружено");
  const bounds = await page.locator(".queue-item").evaluate((element) => {
    const box = element.getBoundingClientRect();
    return Array.from(
      element.querySelectorAll(
        ".language-tag,.queue-item-summary,.queue-item-bottom",
      ),
    ).every((child) => child.getBoundingClientRect().right <= box.right + 1);
  });
  expect(bounds).toBe(true);
});
test("late submitted comment never clears a newer draft after A-B-A", async ({
  page,
}) => {
  const data = await twoConversations(page);
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route(
    `**/api/v1/evaluations/${data.archivedEvaluation.id}/appeals`,
    async (route) => {
      await gate;
      await route.fulfill({
        status: 201,
        json: {
          ...fixture("workspace/appeals.page.json").items[0],
          status: "open",
          decision: null,
          comment: route.request().postDataJSON().comment,
        },
      });
    },
  );
  await page.goto(
    `/#/dialogues/${data.current.id}?evaluation=${data.archivedEvaluation.id}`,
  );
  await expect(page.locator(".score-main")).toContainText("69,57");
  await page
    .getByRole("tab", { name: "Апелляции и история", exact: true })
    .click();
  const picker = page.getByRole("combobox", {
      name: "Спорный критерий",
      exact: true,
    }),
    comment = page.getByRole("textbox", { name: "Комментарий", exact: true });
  await picker.selectOption("needs");
  await comment.fill("Synthetic submitted old draft");
  await page
    .getByRole("button", { name: "Отправить апелляцию", exact: true })
    .click();
  await page.locator(`.queue-item[href*="${data.b.id}"]`).click();
  await expect(page.locator(".score-main")).toContainText("100,00");
  await page.locator(`.queue-item[href*="${data.current.id}"]`).click();
  await expect(page.locator(".score-main")).toContainText("100,00");
  await page.getByRole("tab", { name: "Запуски", exact: true }).click();
  await page
    .locator(`.history-row[href*="${data.archivedEvaluation.id}"]`)
    .click();
  await expect(page.locator(".score-main")).toContainText("69,57");
  await page
    .getByRole("tab", { name: "Апелляции и история", exact: true })
    .click();
  await picker.selectOption("needs");
  await comment.fill("Synthetic NEWER draft");
  release();
  await page.waitForTimeout(150);
  await expect(comment).toHaveValue("Synthetic NEWER draft");
  await picker.selectOption("contact");
  await picker.selectOption("needs");
  await expect(comment).toHaveValue("Synthetic NEWER draft");
});
