import type { Action, KeyProvider, LocalSettings, Node, Provider, Run, TreeNode, World,PublicWorld,SessionInfo,AssetManifest,CreationTask,ImageTask,LocalSample } from "./types";
import type {CreationRequest} from './library';

const BASE = process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000";

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

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
    throw new ApiError(detail, response.status);
  }
  return response.json() as Promise<T>;
}

export const api = {
  localSamples: () => request<{samples:LocalSample[]}>('/local-samples'),
  openLocalSample: (id:LocalSample['id'],clientToken:string) => request<{root:Node;session_id:string;provider:Provider;model_id:string}>('/local-samples/sessions',undefined,
    {method:'POST',body:JSON.stringify({sample_id:id,client_token:clientToken})}),
  world: () => request<World>("/world"),
  settings: () => request<LocalSettings>("/local-settings"),
  saveKey: (provider: KeyProvider, apiKey: string) => request<{ configured: boolean }>(`/local-settings/keys/${provider}`, undefined, {
    method: "PUT", body: JSON.stringify({ api_key: apiKey }),
  }),
  clearKey: (provider: KeyProvider) => request<{ configured: boolean }>(`/local-settings/keys/${provider}`, undefined, { method: "DELETE" }),
  createSession: (provider: Provider = "demo", modelId = "demo") => request<{ token: string; root: Node; provider: Provider; model_id: string }>("/sessions", undefined, {
    method: "POST",
    ...(provider === "demo" ? {} : { body: JSON.stringify({ provider, model_id: modelId }) }),
  }),
  currentSession: (token: string) => request<SessionInfo>("/session", token),
  createCustomSession: (clientToken:string) => request<{token:string;session_id:string;provider:Provider;model_id:string}>('/story-sessions',undefined,
    {method:'POST',body:JSON.stringify({provider:'deepseek',flow:'illustrated-3',client_token:clientToken})}),
  createTask: (token:string,body:CreationRequest,key:string) => request<{task_id:string;status:string}>('/story-tasks',token,
    {method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify(body)}),
  creationTask: (token:string,id:string) => request<CreationTask>(`/story-tasks/${id}`,token),
  rejectTask: (token:string,id:string) => request<{status:string}>(`/story-tasks/${id}/reject`,token,{method:'POST'}),
  confirmTask: (token:string,id:string,candidateVersion:string,hash:string) => request<{root:Node}>(`/story-tasks/${id}/confirm`,token,
    {method:'POST',body:JSON.stringify({candidate_version_id:candidateVersion,content_hash:hash})}),
  resumeCreation: (token:string,id:string,key:string) => request<{task_id:string;status:string}>(`/story-tasks/${id}/resume`,token,
    {method:'POST',headers:{'Idempotency-Key':key}}),
  startImages: (token:string,key:string) => request<{task_id:string;status:string}>('/image-tasks',token,
    {method:'POST',headers:{'Idempotency-Key':key}}),
  imageTask: (token:string,id:string) => request<ImageTask>(`/image-tasks/${id}`,token),
  resumeImages: (token:string,id:string,key:string,confirm=false) => request<{task_id:string;status:string}>(`/image-tasks/${id}/resume`,token,
    {method:'POST',headers:{'Idempotency-Key':key},body:JSON.stringify({confirm_missing_output:confirm})}),
  sessionWorld: (token:string,nodeId:string) => request<PublicWorld>(`/session/world?node_id=${encodeURIComponent(nodeId)}`,token),
  assets: (token:string) => request<AssetManifest>('/session/assets',token),
  asset: async (token:string,id:string) => {
    const response=await fetch(`${BASE}/assets/${encodeURIComponent(id)}`,{headers:{Authorization:`Bearer ${token}`}});
    if (!response.ok) throw new ApiError('图片暂时无法读取，请恢复素材后重试。',response.status);
    return response.blob();
  },
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
