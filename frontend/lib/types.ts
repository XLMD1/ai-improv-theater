export type CharacterId = string;
export type Provider = "demo" | "openai" | "deepseek";
export type AiProvider = Exclude<Provider, "demo">;
export type KeyProvider = AiProvider | "cogview";
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
    flags?: Record<string, boolean>;
    relations?: Record<string, number>;
    turn?: number;
    engine_version?: string;
    location_id?: string;
    discovered_evidence?: string[];
    ending_id: string | null;
  };
  rendered_scene: RenderedScene;
  created_at: string;
  option_types?: Record<string,string>;
  option_targets?: Record<string,Partial<Record<"character_id"|"object_id"|"evidence_id"|"location_id",string>>>;
};

export type TreeNode = Pick<Node, "id" | "parent_id" | "depth" | "scene_id" | "created_at"> & { action_label: string };

export type World = {
  title: string;
  version: string;
  scenes: Record<string, { name: string; background: string }>;
  characters: Record<CharacterId, { name: string; role: string; goal: string; portrait: string }>;
  investigation?: boolean;
  setting?: string;
  era?: string;
  intro?: string;
  objects?: {id:string;name:string;description:string}[];
  evidence?: {id:string;description:string}[];
  disclosures?: {id:string;text:string}[];
  commitments?: {id:string;text:string}[];
  ending?: {id:string;title:string;consequence:string}|null;
};

export type PublicWorld = {
  story_id:string;story_version:string;title:string;setting:string;era:string;intro:string;
  location:{id:string;name:string;description:string};
  locations:{id:string;name:string;description:string}[];
  characters:{id:string;name:string;appearance:string}[];
  cast:{id:string;name:string;appearance:string}[];protagonist_id:string;
  objects:NonNullable<World['objects']>;evidence:NonNullable<World['evidence']>;
  disclosures:NonNullable<World['disclosures']>;commitments:NonNullable<World['commitments']>;ending:World['ending'];
};
export type SessionInfo = {provider:Provider;model_id:string;engine_version?:string;lifecycle?:string;root_node_id?:string|null;task_id?:string|null;requires_assets?:boolean;local_sample?:boolean};
export type AssetManifest = {task_id:string|null;ready:boolean;backgrounds:Record<string,string>;portraits:Record<string,string>};
export type CreationTask = {id:string;status:string;stage:string;error_code:string|null;recoverable:boolean;
  candidate_version_id?:string;content_hash?:string;title?:string;setting?:string;era?:string;public_intro?:string;
  protagonist?:{name:string;appearance:string};location?:{name:string;description:string}};
export type ImageTask = {id:string;status:string;error_code:string|null;total:number;completed:number;recoverable:boolean;needs_generation:boolean;
  requires_missing_output_confirmation:boolean;assets:{id:string;kind:string;entity_id:string;name:string;status:string;available:boolean;error_code:string|null}[]};

export type Run = { id: string; status: string; node_id: string | null; error_code: string | null };

export type LocalSettings = {
  providers: Record<KeyProvider, { model_id: string; configured: boolean; available: boolean }>;
  budget: { estimated_spend_cny: number; reserved_cny?:number;cost_unconfirmed?:boolean; warning_cny: number; limit_cny: number; status: "ok" | "warning" | "blocked" };
};

export type LocalSample = {id:"ancient"|"modern"|"future";title:string;era:"ancient"|"modern"|"future";intro:string};
