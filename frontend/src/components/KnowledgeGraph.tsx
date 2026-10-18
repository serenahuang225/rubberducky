/**
 * The shared prerequisite graph, with this learner's estimate and memory labels on the nodes.
 *
 * Arrows always run from a prerequisite to the concept that comes after it. Nothing in this
 * view adds an arrow from a memory.
 */

import React, { useState } from "react";
import { ScrollView, StyleSheet, Text, View } from "react-native";
import Svg, { Line } from "react-native-svg";

import type { KnowledgeMap } from "../api/contracts";
import type { BoardTheme } from "../board/palette";

const NODE_W = 248;
const NODE_H = 120;
const GAP_X = 64;
const GAP_Y = 40;
const PAD = 24;

type Placed = {
  conceptId: string;
  name: string;
  readiness: string;
  memories: string[];
  x: number;
  y: number;
  height: number;
};

function place(map: KnowledgeMap, measured: Record<string, number>): { nodes: Placed[]; width: number; height: number } {
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
    let rowY = PAD;
    ids.forEach((id) => {
      const node = byId.get(id);
      if (node === undefined) return;
      const lines = (text: string) => Math.max(1, Math.ceil(text.length / 28));
      const height = Math.max(NODE_H, measured[id] ?? 0, 64 + lines(node.name) * 20 +
        lines(node.readiness_label) * 18 + node.memories.reduce((sum, text) => sum + lines(text) * 18 + 8, 0));
      placed.push({
        conceptId: id,
        name: node.name,
        readiness: node.readiness_label,
        memories: node.memories,
        x: PAD + column * (NODE_W + GAP_X),
        y: rowY,
        height,
      });
      rowY += height + GAP_Y;
    });
  }
  const width = Math.max(
    ...placed.map((node) => node.x + NODE_W + PAD),
    PAD * 2,
  );
  const height = Math.max(
    ...placed.map((node) => node.y + node.height + PAD),
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
  const [measured, setMeasured] = useState<Record<string, number>>({});
  const layout = place(map, measured);
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
                  y1={from.y + from.height / 2}
                  x2={to.x}
                  y2={to.y + to.height / 2}
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
              onLayout={(event) => {
                const height = event.nativeEvent.layout.height;
                setMeasured((previous) => Math.abs((previous[node.conceptId] ?? 0) - height) < 1
                  ? previous : { ...previous, [node.conceptId]: height });
              }}
              accessibilityLabel={`${node.name}. ${node.readiness}. ${node.memories.join(". ")}`}
              style={[
                styles.node,
                {
                  left: node.x,
                  top: node.y,
                  width: NODE_W,
                  minHeight: node.height,
                  backgroundColor: theme.surface,
                  borderColor: theme.surfaceEdge,
                },
              ]}
            >
              <Text style={[styles.name, { color: theme.labelText }]}>
                {node.name}
              </Text>
              <Text style={[styles.readiness, { color: theme.labelMuted }]}>
                {node.readiness}
              </Text>
              {node.memories.map((memory) => (
                <Text
                  key={memory}
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
    paddingHorizontal: 14,
    paddingVertical: 18,
    gap: 8,
  },
  name: { fontSize: 14, fontWeight: "700", lineHeight: 18 },
  readiness: { fontSize: 12, lineHeight: 16 },
  memory: { fontSize: 12, lineHeight: 16, fontWeight: "600" },
});
