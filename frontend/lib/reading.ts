import type { RenderedScene, TreeNode } from "./types";

export function ancestorIds(tree: Pick<TreeNode, "id" | "parent_id">[], currentId: string): string[] {
  const byId = new Map(tree.map(node => [node.id, node]));
  const path: string[] = [];
  let id: string | null = currentId;
  while (id) {
    const node = byId.get(id);
    if (!node || path.includes(id)) throw new Error("历史记录不完整，请重新连接后再试。");
    path.push(id);
    id = node.parent_id;
  }
  return path.reverse();
}

export function readingLines(scene: Pick<RenderedScene, "narration" | "dialogue">) {
  const paragraphs: { text: string; characterId?: string }[] = [
    { text: scene.narration },
    ...scene.dialogue.map(line => ({ text: line.text, characterId: line.character_id })),
  ];
  return paragraphs.flatMap(line => (line.text.match(/[^。！？!?]+[。！？!?]*|[。！？!?]+/g) || [])
    .map(text => ({ ...line, text })));
}

export function knownClues(flags: Record<string, boolean>) {
  // Legacy public flags are milestones, not a fabricated inventory of evidence objects.
  const labels: Record<string, string> = {
    clue_found: "已发现航海日志的线索",
    secret_shared: "已分享钟楼的记录",
    trust_broken: "这次选择打破了彼此的信任",
  };
  return Object.entries(labels).filter(([key]) => flags[key] === true).map(([id, text]) => ({ id, text }));
}
