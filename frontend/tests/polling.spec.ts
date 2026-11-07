import { test, expect, type Page } from "@playwright/test";
import { fixture, mockAPI, pageOf } from "./helpers/mock-api";

// Explicitly synthetic API responses; no provider or product fallback is used.
async function pollingAPI(page: Page, failed = false) {
  const api = await mockAPI(page);
  const initial = fixture(
    failed ? "evaluation.running.json" : "evaluation.queued.json",
  );
  const running = fixture("evaluation.running.json");
  const terminal = failed
    ? {
        ...running,
        status: "failed",
        completed_at: "2026-11-08T00:00:00Z",
        error: {
          code: "AI_TIMEOUT",
          message: "PRIVATE_SERVER_MARKER",
          details: [],
        },
      }
    : fixture("evaluation.completed.json");
  const conversation = fixture("conversation.response.json");
  let state = initial;
  let queueRequests = 0;
  let polls = 0;
  await page.route("**/api/v1/conversations?*", (route) => {
    queueRequests++;
    return route.fulfill({
      json: pageOf([
        {
          ...conversation,
          latest_evaluation: {
            id: state.id,
            status: state.status,
            original_total: state.original?.total ?? null,
            final_total: state.final?.total ?? null,
            created_at: state.created_at,
          },
        },
      ]),
    });
  });
  await page.route("**/api/v1/evaluations?*", (route) =>
    route.fulfill({ json: pageOf([initial]) }),
  );
  await page.route(`**/api/v1/evaluations/${initial.id}`, (route) => {
    state = ++polls < 3 ? running : terminal;
    return route.fulfill({ json: state });
  });
  return {
    initial,
    terminal,
    conversation,
    queueRequests: () => queueRequests,
    polls: () => polls,
    consoleLines: api.consoleLines,
  };
}

for (const failed of [false, true]) {
  test(`terminal polling refreshes the queue once on ${failed ? "failure" : "success"}`, async ({
    page,
  }) => {
    await page.clock.install();
    const data = await pollingAPI(page, failed);
    await page.goto(`/#/dialogues/${data.conversation.id}`);
    const row = page.locator(`#queue-item-${data.conversation.id}`);
    await expect(row.locator(".badge")).toHaveText(
      failed ? "Анализируется" : "В очереди",
    );
    await expect(page.locator(".analysis-pending")).toBeVisible();
    // React StrictMode may duplicate the initial load; measure subsequent refreshes.
    const initialRequests = data.queueRequests();
    expect(initialRequests).toBeGreaterThan(0);

    // Repeated nonterminal polls and an unrelated render must not reload the queue.
    for (let poll = 1; poll <= 2; poll++) {
      await page.clock.runFor(2100);
      await expect.poll(data.polls).toBe(poll);
      await expect(page.locator(".analysis-pending")).toContainText(
        "AI анализирует",
      );
      expect(data.queueRequests()).toBe(initialRequests);
    }
    await page.getByRole("button", { name: "Светлая тема", exact: true }).click();
    expect(data.queueRequests()).toBe(initialRequests);

    await page.clock.runFor(2100);
    await expect.poll(data.polls).toBe(3);
    if (failed) {
      await expect(page.getByRole("alert")).toContainText("AI_TIMEOUT");
      await expect(page.locator("body")).not.toContainText(
        "PRIVATE_SERVER_MARKER",
      );
    } else {
      await expect(page.locator(".score-main")).toContainText("70,00");
    }
    await expect(row.locator(".badge")).toHaveText(
      failed ? "Ошибка оценки" : "Оценён",
    );
    if (!failed) await expect(row).toContainText("70,00");
    expect(data.queueRequests()).toBe(initialRequests + 1);
    await page.getByRole("tab", { name: "Запуски", exact: true }).click();
    await expect(page.locator(".history-row.selected .badge")).toHaveText(
      failed ? "Ошибка оценки" : "Оценён",
    );
    await page.clock.runFor(10000);
    expect(data.queueRequests()).toBe(initialRequests + 1);
    expect(data.polls()).toBe(3);
    expect(data.consoleLines.join(" ")).not.toContain("PRIVATE_SERVER_MARKER");
  });
}

for (const sameConversation of [false, true]) {
  test(`late terminal poll does not refresh or replace a different ${sameConversation ? "evaluation" : "conversation"}`, async ({
    page,
  }) => {
    await page.clock.install();
    await mockAPI(page);
    const initial = fixture("evaluation.queued.json");
    const conversation = fixture("conversation.response.json");
    const targetConversation = {
      ...conversation,
      id: sameConversation
        ? conversation.id
        : "74000000-0000-4000-8000-000000000001",
      external_id: "synthetic-selected-target",
    };
    const target = {
      ...fixture("evaluation.completed.json"),
      id: "74000000-0000-4000-8000-000000000005",
      conversation_id: targetConversation.id,
    };
    let queueRequests = 0;
    let pollStarted = false;
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    await page.route("**/api/v1/conversations?*", (route) => {
      queueRequests++;
      return route.fulfill({
        json: pageOf([
          conversation,
          ...(sameConversation ? [] : [targetConversation]),
        ]),
      });
    });
    await page.route(`**/api/v1/conversations/${targetConversation.id}*`, (route) =>
      route.fulfill({ json: targetConversation }),
    );
    await page.route("**/api/v1/evaluations?*", (route) =>
      route.fulfill({
        json: pageOf(
          new URL(route.request().url()).searchParams.get("conversation_id") ===
            initial.conversation_id
            ? [initial, ...(sameConversation ? [target] : [])]
            : [target],
        ),
      }),
    );
    await page.route(`**/api/v1/evaluations/${target.id}`, (route) =>
      route.fulfill({ json: target }),
    );
    await page.route(`**/api/v1/evaluations/${initial.id}`, async (route) => {
      pollStarted = true;
      await held;
      await route.fulfill({
        json: {
          ...initial,
          status: "failed",
          completed_at: "2026-11-08T00:00:00Z",
          error: {
            code: "AI_TIMEOUT",
            message: "PRIVATE_SERVER_MARKER",
            details: [],
          },
        },
      });
    });
    await page.goto(`/#/dialogues/${conversation.id}`);
    await expect(page.locator(".analysis-pending")).toBeVisible();
    await page.clock.runFor(2100);
    await expect.poll(() => pollStarted).toBe(true);
    const hash = `#/dialogues/${targetConversation.id}?evaluation=${target.id}`;
    await page.evaluate((value) => {
      location.hash = value;
    }, hash);
    await expect(page.locator(".score-main")).toContainText("70,00");
    const initialRequests = queueRequests;
    const response = page.waitForResponse(`**/api/v1/evaluations/${initial.id}`);
    release();
    await response;
    await page.clock.runFor(10000);
    await expect(page.locator(".score-main")).toContainText("70,00");
    await expect(page.getByRole("alert")).toHaveCount(0);
    expect(await page.evaluate(() => location.hash)).toBe(hash);
    expect(queueRequests).toBe(initialRequests);
  });
}
