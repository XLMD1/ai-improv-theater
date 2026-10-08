export type CharacterId = "c1" | "c2" | "c3";
export type Action = { type: "option" | "text"; value: string };
export type Option = { id: string; label: string };

export type RenderedScene = {
  scene_id: string;
  narration: string;
  dialogue: { character_id: CharacterId; text: string; emotion: string }[];
  options: Option[];
  fallback: boolean;
};

export type Node = {
  id: string;
  parent_id: string | null;
  depth: number;
  scene_id: string;
  state_snapshot: {
    flags: Record<string, boolean>;
    relations: Record<string, number>;
    turn: number;
    ending_id: string | null;
  };
  rendered_scene: RenderedScene;
  created_at: string;
};

export type TreeNode = Pick<Node, "id" | "parent_id" | "depth" | "scene_id" | "created_at"> & { action_label: string };

export type World = {
  title: string;
  version: string;
  scenes: Record<string, { name: string; background: string }>;
  characters: Record<CharacterId, { name: string; role: string; goal: string; portrait: string }>;
};

export type Run = { id: string; status: string; node_id: string | null; error_code: string | null };
