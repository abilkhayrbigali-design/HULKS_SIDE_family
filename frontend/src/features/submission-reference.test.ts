import { describe, expect, it, vi } from "vitest";
import { parseSubmissionReference, readSubmissionReference, referenceMaxBytes, validPreflight } from "./submission-reference";

const records = [{ conversation_id: " external-A ", transcript: "PRIVATE_REFERENCE_MARKER" }, { conversation_id: "external-B" }];
const envelope = () => ({ isSuccess: true, error: null, data: { records, total_records: 2 } });
describe("independent source reference", () => {
  it("keeps only trimmed external source IDs, not transcript or batch state", () => {
    const expected = { expected_conversation_ids: ["external-A", "external-B"], expected_total_records: 2 };
    expect(parseSubmissionReference(envelope())).toEqual(expected);
    expect(parseSubmissionReference({ records })).toEqual(expected);
    expect(parseSubmissionReference({ records, total_records: 2 })).toEqual(expected);
    expect(JSON.stringify(parseSubmissionReference(envelope()))).not.toContain("PRIVATE_REFERENCE_MARKER");
  });
  it("rejects contradictory totals and upstream failures instead of silently shrinking the reference", () => {
    for (const total_records of [undefined, null, "2", 1, 2.5, 0, true]) {
      expect(() => parseSubmissionReference({ ...envelope(), data: { records, total_records } })).toThrow();
    }
    expect(() => parseSubmissionReference({ records, total_records: "2" })).toThrow();
    expect(() => parseSubmissionReference({ ...envelope(), isSuccess: false })).toThrow();
    expect(() => parseSubmissionReference({ ...envelope(), error: "PRIVATE_REFERENCE_MARKER" })).toThrow();
  });
  it("rejects duplicate-after-trim, missing and non-string IDs and unsupported roots", () => {
    for (const value of [null, [], records, {}, { records: [] }, { records: [{ conversation_id: 123 }] }, { records: [{ conversation_id: " " }] }, { records: [null] }, { records: [{ conversation_id: "A" }, { conversation_id: " A " }] }]) {
      expect(() => parseSubmissionReference(value)).toThrow();
    }
    expect(() => parseSubmissionReference({ records: Array.from({ length: 1001 }, (_, i) => ({ conversation_id: String(i) })) })).toThrow();
  });
  it("checks file bytes before reading and discards parser payload errors", async () => {
    const text = vi.fn(async () => JSON.stringify(envelope()));
    await expect(readSubmissionReference({ size: referenceMaxBytes + 1, text })).rejects.toThrow("16 МиБ");
    expect(text).not.toHaveBeenCalled();
    await expect(readSubmissionReference({ size: 10, text: async () => "PRIVATE_REFERENCE_MARKER invalid" })).rejects.toThrow("формат");
    await expect(readSubmissionReference({ size: referenceMaxBytes, text })).resolves.toMatchObject({ expected_total_records: 2 });
  });
  it("refuses a preflight that reports true for a contradictory scope or malformed counts", () => {
    const reference = parseSubmissionReference(envelope());
    const result = { expected_count: 2, batch_count: 2, missing_count: 0, extra_count: 0, matches: true };
    expect(validPreflight(result, reference, 2)).toBe(true);
    expect(validPreflight({ ...result, missing_count: 1, extra_count: 1, matches: false }, reference, 2)).toBe(true);
    expect(validPreflight({ ...result, missing_count: 1 }, reference, 2)).toBe(false);
    expect(validPreflight(result, reference, 3)).toBe(false);
    expect(validPreflight({ ...result, extra_count: -1 }, reference, 2)).toBe(false);
  });
});
