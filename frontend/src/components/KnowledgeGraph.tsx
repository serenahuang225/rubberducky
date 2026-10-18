/**
 * The shared prerequisite graph, with this learner's estimate and memory labels on the nodes.
 *
 * Arrows always run from a prerequisite to the concept that comes after it. Nothing in this
 * view adds an arrow from a memory.
 */

import React from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import Svg, { Line } from "react-native-svg";

import type { KnowledgeMap } from "../api/contracts";
import type { BoardTheme } from "../board/palette";

const NODE_W = 156;
const NODE_H = 96;
const GAP_X = 36;
const GAP_Y = 16;
const PAD = 8;

type Placed = {
  conceptId: string;
  name: string;
  readiness: string;
  memories: string[];
  x: number;
  y: number;
};

function place(map: KnowledgeMap): { nodes: Placed[]; width: number; height: number } {
  const byId = new Map(map.nodes.map((node) => [node.concept_id, node]));
  const incoming = new Map<string, string[]>();
  for (const node of map.nodes) incoming.set(node.concept_id, []);
  for (const edge of map.edges) {
    incoming.get(edge.concept_id)?.push(edge.prerequisite_id);
  }
  const depth = new Map<string, number>();
  const visit = (id: string, seen: Set<string>): number => {
    const known = depth.get(id);
    if (known !== undefined) return known;
    if (seen.has(id)) return 0;
    seen.add(id);
    const pres = incoming.get(id) ?? [];
    const value = pres.length === 0 ? 0 : 1 + Math.max(...pres.map((pre) => visit(pre, seen)));
    depth.set(id, value);
    return value;
  };
  for (const node of map.nodes) visit(node.concept_id, new Set());
  const columns = new Map<number, string[]>();
  for (const node of map.nodes) {
    const column = depth.get(node.concept_id) ?? 0;
    const ids = columns.get(column) ?? [];
    ids.push(node.concept_id);
    columns.set(column, ids);
  }
  const placed: Placed[] = [];
  for (const column of [...columns.keys()].sort((a, b) => a - b)) {
    const ids = (columns.get(column) ?? []).sort((a, b) =>
      (byId.get(a)?.name ?? a).localeCompare(byId.get(b)?.name ?? b),
    );
    ids.forEach((id, row) => {
      const node = byId.get(id);
      if (node === undefined) return;
      placed.push({
        conceptId: id,
        name: node.name,
        readiness: node.readiness_label,
        memories: node.memories,
        x: PAD + column * (NODE_W + GAP_X),
        y: PAD + row * (NODE_H + GAP_Y),
      });
    });
  }
  const width = Math.max(
    ...placed.map((node) => node.x + NODE_W + PAD),
    PAD * 2,
  );
  const height = Math.max(
    ...placed.map((node) => node.y + NODE_H + PAD),
    PAD * 2,
  );
  return { nodes: placed, width, height };
}

export function KnowledgeGraph({
  map,
  theme,
}: {
  map: KnowledgeMap;
  theme: BoardTheme;
}) {
  const layout = place(map);
  const at = new Map(layout.nodes.map((node) => [node.conceptId, node]));
  return (
    <View testID="knowledge-graph" style={styles.wrap}>
      <Text style={[styles.notice, { color: theme.labelMuted }]}>{map.notice}</Text>
      <ScrollView horizontal showsHorizontalScrollIndicator>
        <View style={{ width: layout.width, height: layout.height }}>
          <Svg width={layout.width} height={layout.height}>
            {map.edges.map((edge) => {
              const from = at.get(edge.prerequisite_id);
              const to = at.get(edge.concept_id);
              if (from === undefined || to === undefined) return null;
              return (
                <Line
                  key={`${edge.prerequisite_id}-${edge.concept_id}`}
                  x1={from.x + NODE_W}
                  y1={from.y + NODE_H / 2}
                  x2={to.x}
                  y2={to.y + NODE_H / 2}
                  stroke={theme.labelMuted}
                  strokeWidth={2}
                />
              );
            })}
          </Svg>
          {layout.nodes.map((node) => (
            <View
              key={node.conceptId}
              testID={`knowledge-node-${node.conceptId}`}
              accessibilityLabel={`${node.name}. ${node.readiness}. ${node.memories.join(". ")}`}
              style={[
                styles.node,
                {
                  left: node.x,
                  top: node.y,
                  width: NODE_W,
                  height: NODE_H,
                  backgroundColor: theme.surface,
                  borderColor: theme.surfaceEdge,
                },
              ]}
            >
              <Text numberOfLines={2} style={[styles.name, { color: theme.labelText }]}>
                {node.name}
              </Text>
              <Text numberOfLines={2} style={[styles.readiness, { color: theme.labelMuted }]}>
                {node.readiness}
              </Text>
              {node.memories.map((memory) => (
                <Text
                  key={memory}
                  numberOfLines={1}
                  style={[styles.memory, { color: theme.labelText }]}
                >
                  {memory}
                </Text>
              ))}
            </View>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { gap: 8 },
  notice: { fontSize: 14, lineHeight: 20 },
  node: {
    position: "absolute",
    borderWidth: 2,
    borderRadius: 16,
    paddingHorizontal: 8,
    paddingVertical: 6,
    gap: 2,
  },
  name: { fontSize: 14, fontWeight: "700", lineHeight: 18 },
  readiness: { fontSize: 12, lineHeight: 16 },
  memory: { fontSize: 12, lineHeight: 16, fontWeight: "600" },
});
