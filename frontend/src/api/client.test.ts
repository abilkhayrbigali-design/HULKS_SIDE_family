import { afterEach, describe, expect, it, vi } from "vitest";
import { allPages, ApiError, request, errorMessage } from "./client";
describe("safe API boundary", () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });
  it("drops upstream message and payload from errors and diagnostics", async () => {
    const marker = "SECRET_DIALOGUE_SIGNED_URL";
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({
            error: {
              code: "AI_NOT_CONFIGURED",
              message: marker,
              details: [{ input: marker }],
            },
          }),
          { status: 503 },
        ),
      ),
    );
    const logger = vi.spyOn(console, "error").mockImplementation(() => {});
    let failure: unknown;
    try {
      await request("/evaluations", {
        method: "POST",
        body: JSON.stringify({ private: marker }),
      });
    } catch (e) {
      failure = e;
    }
    expect(failure).toBeInstanceOf(ApiError);
    expect((failure as ApiError).code).toBe("AI_NOT_CONFIGURED");
    expect((failure as Error).message).not.toContain(marker);
    expect(logger.mock.calls).toEqual([
      ["event=ui_operation_failed status=503 error=AI_NOT_CONFIGURED"],
    ]);
  });
  it("redacts exception text and unknown codes", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new Error("PRIVATE_EXCEPTION")),
    );
    const logger = vi.spyOn(console, "error").mockImplementation(() => {});
    await expect(request("/conversations")).rejects.toMatchObject({
      code: "NETWORK_ERROR",
    });
    expect(logger.mock.calls.flat().join("")).not.toContain(
      "PRIVATE_EXCEPTION",
    );
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(JSON.stringify({ error: { code: "SECRET_CODE" } }), {
          status: 500,
        }),
      ),
    );
    await expect(request("/conversations")).rejects.toMatchObject({
      code: "API_ERROR",
    });
    expect(logger.mock.calls.flat().join("")).not.toContain("SECRET_CODE");
  });
  it("maps expected provider refusals and authentication failures to actionable messages", () => {
    expect(errorMessage("AI_AUTHENTICATION_FAILED")).toContain(
      "авторизоваться",
    );
    expect(errorMessage("AI_TIMEOUT")).toContain("не ответил вовремя");
    expect(errorMessage("AI_REFUSED")).toContain("отказался");
    expect(errorMessage("AI_INCOMPLETE")).toContain("не завершил");
  });
  it("loads every page of history", async () => {
    const load = vi.fn(async (offset: number) => ({
      items: [1, 2, 3, 4, 5].slice(offset, offset + 2),
      total: 5,
      limit: 2,
      offset,
    }));
    expect(await allPages(load)).toEqual([1, 2, 3, 4, 5]);
    expect(load.mock.calls.map((x) => x[0])).toEqual([0, 2, 4]);
  });
});
