import { test, expect, type Page } from "@playwright/test";
import { fixture, mockWorkspaceAPI, pageOf } from "./helpers/mock-api";
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
