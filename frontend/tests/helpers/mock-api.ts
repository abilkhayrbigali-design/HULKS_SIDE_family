import type { Page, Route } from "@playwright/test";
import { readFileSync } from "node:fs";
// Explicit synthetic status for browser tests; never a product fallback.
export const syntheticBudget = () => ({
  currency: "USD", limit_usd: "10.000000", committed_upper_usd: "0.000000",
  reserved_usd: "0.000000", available_usd: "10.000000", next_request_upper_usd: "0.587400",
  active_reservations: 0, unknown_reservations: 0, model: "gpt-6-luna", service_tier: "default",
  pricing_version: "gpt-6-luna-standard-2026-11-08-v1", accounting_started_at: "2026-11-08T00:00:00Z",
  enabled: true, blocked_reason: null as string | null,
});
export const fixture = (file: string) =>
  JSON.parse(
    readFileSync(
      new URL(`../../../data/fixtures/synthetic/${file}`, import.meta.url),
      "utf8",
    ),
  );
export const pageOf = (items: unknown[]) => ({
  items,
  total: items.length,
  limit: 100,
  offset: 0,
});
// Explicit test-only API interception: the product has no mock evaluation fallback.
export async function mockAPI(
  page: Page,
  o: {
    completed?: boolean;
    noKey?: boolean;
    poll?: boolean;
    conflict?: boolean;
    languages?: boolean;
    pagination101?: boolean;
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
    if (path === "/ai-budget") return json(syntheticBudget());
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
        id: decodeURIComponent(path.split("/").at(-1)!),
        current_transcript_version_id: "latest-different-version",
        transcript_version_id:
          url.searchParams.get("transcript_version_id") ??
          "latest-different-version",
      });
    if (path === "/checklists" && req.method() === "GET") {
      if (o.pagination101) {
        const offset = Number(url.searchParams.get("offset") ?? 0);
        const first = fixture("checklists.response.json").items[0];
        const items = Array.from({ length: 101 }, (_, i) => ({
          ...first,
          id: `checklist-${i + 1}`,
          name: `Чек-лист ${i + 1}`,
        }));
        return json({
          items: items.slice(offset, offset + 100),
          total: 101,
          limit: 100,
          offset,
        });
      }
      return json(fixture("checklists.response.json"));
    }
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
    if (path === "/appeals")
      return json(
        pageOf(
          appeals.map((a) => ({
            ...a,
            current_revision: evaluation.revision,
            current: evaluation.final.criteria.find(
              (c: any) => c.criterion_id === a.criterion_id,
            ),
          })),
        ),
      );
    if (path.endsWith("/decisions")) {
      const appeal = appeals.find((a) => path.includes(a.id));
      if (o.conflict) {
        evaluation.revision = 1;
        return fail("REVISION_CONFLICT", 409);
      }
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
        result: structuredClone(
          evaluation.final.criteria.find(
            (c: any) => c.criterion_id === appeal.criterion_id,
          ),
        ),
      };
      return json({ appeal, evaluation });
    }
    return fail("NOT_FOUND", 404);
  });
  return { posts, observed, consoleLines, checklist, conversation, evaluation };
}

/** Dedicated, explicitly synthetic wire snapshots; never a product data fallback. */
export async function mockWorkspaceAPI(page: Page) {
  const current = fixture("workspace/conversation.current.json");
  const archived = fixture("workspace/conversation.archived.json");
  const v1 = fixture("workspace/checklist.v1.json"),
    v2 = fixture("workspace/checklist.v2.json");
  const archivedEvaluation = fixture("workspace/evaluation.archived.json"),
    currentEvaluation = fixture("workspace/evaluation.current.json");
  const requests: string[] = [],
    consoleLines: string[] = [];
  page.on("console", (message) => {
    if (["error", "warning"].includes(message.type()))
      consoleLines.push(message.text());
  });
  await page.route("**/api/v1/**", async (route) => {
    const request = route.request(),
      url = new URL(request.url()),
      path = url.pathname.replace("/api/v1", "");
    requests.push(path + url.search);
    const send = (json: unknown, status = 200) =>
      route.fulfill({ json, status });
    if (path === "/ai-budget") return send(syntheticBudget());
    if (request.method() !== "GET")
      return send(
        {
          error: {
            code: "AI_NOT_CONFIGURED",
            message: "Synthetic test server: no live calls",
            details: [],
          },
        },
        503,
      );
    if (path === "/conversations") {
      const summary = {
        ...current,
        latest_evaluation: {
          id: currentEvaluation.id,
          status: currentEvaluation.status,
          original_total: currentEvaluation.original.total,
          final_total: currentEvaluation.final.total,
          created_at: currentEvaluation.created_at,
        },
      };
      return send(pageOf([summary]));
    }
    if (path.startsWith("/conversations/"))
      return send(
        url.searchParams.get("transcript_version_id") ===
          archived.transcript_version_id
          ? archived
          : current,
      );
    if (path === "/checklists")
      return send(
        pageOf([
          {
            id: v2.checklist_id,
            name: v2.name,
            latest_version_id: v2.id,
            latest_version_number: v2.version_number,
          },
        ]),
      );
    if (path.startsWith("/checklists/"))
      return send({
        id: v2.checklist_id,
        name: v2.name,
        current_version: v2,
        versions: [v2, v1],
      });
    if (path.startsWith("/checklist-versions/"))
      return send(path.endsWith(v1.id) ? v1 : v2);
    if (path === "/evaluations")
      return send(fixture("workspace/evaluations.page.json"));
    if (path.startsWith("/evaluations/"))
      return send(
        path.endsWith(archivedEvaluation.id)
          ? archivedEvaluation
          : currentEvaluation,
      );
    if (path === "/appeals")
      return send(
        url.searchParams.get("evaluation_id") === archivedEvaluation.id
          ? fixture("workspace/appeals.page.json")
          : pageOf([]),
      );
    return send(
      {
        error: {
          code: "NOT_FOUND",
          message: "Test route missing",
          details: [],
        },
      },
      404,
    );
  });
  return {
    current,
    archived,
    v1,
    v2,
    archivedEvaluation,
    currentEvaluation,
    requests,
    consoleLines,
  };
}
