import { describe, expect, it } from "vitest";
import { normalizeImport } from "./Conversations";
import { validateCriteria } from "./Checklists";
import { evidenceIds } from "./ConversationView";
import type { Criterion } from "../api/types";
const criterion: Criterion = {
  id: "custom",
  name: "Пользовательский критерий",
  instruction: "Проверить действие",
  type: "scale",
  weight: 35,
  allow_na: true,
  na_rule: "Если не требовалось",
  scale: [
    { value: 0, description: "Нет" },
    { value: 8, description: "Да" },
  ],
  section: null,
};
describe("validation and evidence", () => {
  it("validates custom scales, unique IDs and N/A rule", () => {
    expect(validateCriteria([criterion])).toBeNull();
    expect(validateCriteria([criterion, { ...criterion }])).toContain(
      "уникальными",
    );
    expect(
      validateCriteria([
        {
          ...criterion,
          scale: [
            { value: 3, description: "a" },
            { value: 3, description: "b" },
          ],
        },
      ]),
    ).toContain("ступени");
    expect(validateCriteria([{ ...criterion, na_rule: " " }])).toContain("N/A");
    expect(
      validateCriteria([
        { ...criterion, type: "flag", weight: 0, allow_na: false },
      ]),
    ).toContain("балльный");
  });
  it("unwraps organizer imports without inventing data", () => {
    const records = [{ conversation_id: "own-synthetic" }];
    expect(normalizeImport({ data: { records } })).toEqual(records);
    expect(normalizeImport({ records })).toEqual(records);
    expect(normalizeImport(records)).toEqual(records);
    expect(() => normalizeImport({ data: { records: [] } })).toThrow();
  });
  it("resolves inclusive ranges in frozen transcript order", () => {
    const messages = [{ id: "m0001" }, { id: "m0002" }, { id: "m0003" }];
    expect(
      evidenceIds(
        { kind: "range", start_message_id: "m0001", end_message_id: "m0003" },
        messages,
      ),
    ).toEqual(["m0001", "m0002", "m0003"]);
    expect(
      evidenceIds(
        { kind: "range", start_message_id: "m0003", end_message_id: "m0001" },
        messages,
      ),
    ).toEqual([]);
    expect(
      evidenceIds({ kind: "message", message_id: "missing" }, messages),
    ).toEqual([]);
  });
});
