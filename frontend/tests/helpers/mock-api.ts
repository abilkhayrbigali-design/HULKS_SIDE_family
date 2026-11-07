import type { Page, Route } from "@playwright/test";
import { readFileSync } from "node:fs";
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
