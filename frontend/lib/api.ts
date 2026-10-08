import type { Action, AiProvider, LocalSettings, Node, Provider, Run, TreeNode, World } from "./types";

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

async function request<T>(path: string, token?: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.body ? { "Content-Type": "application/json" } : {}),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...init?.headers,
    },
    cache: "no-store",
  });
  if (!response.ok) {
    let detail = `请求失败 (${response.status})`;
    try { detail = (await response.json()).detail || detail; } catch { /* empty response */ }
    throw new Error(detail);
  }
  return response.json() as Promise<T>;
}

export const api = {
  world: () => request<World>("/world"),
  settings: () => request<LocalSettings>("/local-settings"),
  saveKey: (provider: AiProvider, apiKey: string) => request<{ configured: boolean }>(`/local-settings/keys/${provider}`, undefined, {
    method: "PUT", body: JSON.stringify({ api_key: apiKey }),
  }),
  clearKey: (provider: AiProvider) => request<{ configured: boolean }>(`/local-settings/keys/${provider}`, undefined, { method: "DELETE" }),
  createSession: (provider: Provider = "demo", modelId = "demo") => request<{ token: string; root: Node; provider: Provider; model_id: string }>("/sessions", undefined, {
    method: "POST",
    ...(provider === "demo" ? {} : { body: JSON.stringify({ provider, model_id: modelId }) }),
  }),
  currentSession: (token: string) => request<{ provider: Provider; model_id: string }>("/session", token),
  node: (token: string, id: string) => request<Node>(`/nodes/${id}`, token),
  nodeEvents: (token: string, id: string) => request<{ event_type: string; payload: Action }[]>(`/nodes/${id}/events`, token),
  tree: (token: string) => request<TreeNode[]>("/tree", token),
  run: (token: string, id: string) => request<Run>(`/runs/${id}`, token),
  turn: (token: string, parent_node_id: string, action: Action, key: string) =>
    request<{ run_id: string; status: string }>("/turns", token, {
      method: "POST",
      headers: { "Idempotency-Key": key },
      body: JSON.stringify({ parent_node_id, action }),
    }),
};

export async function readSSE(
  token: string,
  runId: string,
  after: number,
  onEvent: (event: string, data: Record<string, unknown>, seq: number) => void,
): Promise<void> {
  const response = await fetch(`${BASE}/runs/${runId}/events?after=${after}`, {
    headers: { Authorization: `Bearer ${token}` },
    cache: "no-store",
  });
  if (!response.ok || !response.body) throw new Error(`事件连接失败 (${response.status})`);
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true }).replace(/\r\n/g, "\n");
    let boundary = buffer.indexOf("\n\n");
    while (boundary >= 0) {
      const block = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const fields = block.split("\n");
      const id = fields.find(line => line.startsWith("id: "))?.slice(4);
      const event = fields.find(line => line.startsWith("event: "))?.slice(7);
      const data = fields.find(line => line.startsWith("data: "))?.slice(6);
      if (id && event && data) onEvent(event, JSON.parse(data), Number(id));
      boundary = buffer.indexOf("\n\n");
    }
  }
}
