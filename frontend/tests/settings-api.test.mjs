import assert from "node:assert/strict";
import { afterEach, test } from "node:test";
import { api } from "../lib/api.ts";

const originalFetch = globalThis.fetch;
afterEach(() => { globalThis.fetch = originalFetch; });

test("new story sends the pinned provider and model", async () => {
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return Response.json({ token: "test-token", root: {}, provider: "deepseek", model_id: "deepseek-flash" });
  };

  await api.createSession("deepseek", "deepseek-flash");

  assert.equal(request.url, "http://127.0.0.1:8000/sessions");
  assert.equal(request.init.method, "POST");
  assert.deepEqual(JSON.parse(request.init.body), { provider: "deepseek", model_id: "deepseek-flash" });
});

test("key is sent only in the settings write body", async () => {
  let request;
  globalThis.fetch = async (url, init) => {
    request = { url, init };
    return Response.json({ configured: true });
  };

  await api.saveKey("deepseek", "test-secret-value");

  assert.equal(request.url, "http://127.0.0.1:8000/local-settings/keys/deepseek");
  assert.equal(request.init.method, "PUT");
  assert.deepEqual(JSON.parse(request.init.body), { api_key: "test-secret-value" });
  assert.equal(request.init.headers.Authorization, undefined);
});
