import assert from "node:assert/strict";
import { test } from "node:test";
import { ancestorIds, readingLines, knownClues } from "../lib/reading.ts";

test("history follows only selected ancestors even when a sibling is newer", () => {
  const tree = [{ id: "root", parent_id: null }, { id: "a", parent_id: "root" }, { id: "b", parent_id: "root" }, { id: "c", parent_id: "a" }];
  assert.deepEqual(ancestorIds(tree, "c"), ["root", "a", "c"]);
  assert.deepEqual(ancestorIds(tree, "b"), ["root", "b"]);
});

test("history refuses broken ancestry rather than silently presenting a partial chain", () => {
  assert.throws(() => ancestorIds([{ id: "a", parent_id: "missing" }], "a"));
  assert.throws(() => ancestorIds([{ id: "a", parent_id: "a" }], "a"));
});

test("sentence reading preserves every character and supports narration without dialogue", () => {
  const text = "雨停了。\n窗边有人！还有未完的话";
  const lines = readingLines({ narration: text, dialogue: [] });
  assert.equal(lines.map(line => line.text).join(""), text);
  assert.equal(lines.length, 3);
  assert.ok(lines.every(line => line.characterId === undefined));
  assert.deepEqual(readingLines({ narration: "雨。", dialogue: [{ character_id: "c1", text: "找到了。走吧！" }] }).map(line => line.characterId), [undefined, "c1", "c1"]);
});

test("clue records omit undiscovered and unsupported flags", () => {
  assert.deepEqual(knownClues({ clue_found: false, secret_shared: false }), []);
  assert.equal(knownClues({ clue_found: true, hidden_truth: true }).length, 1);
  assert.ok(!JSON.stringify(knownClues({ hidden_truth: true })).includes("hidden_truth"));
});
