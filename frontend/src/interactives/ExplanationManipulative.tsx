/**
 * Native manipulatives for a released explanation: equal groups, and a(b + c) = ab + ac.
 *
 * The component draws only from validated numbers and plain text with its own views, so a
 * generated spec can change *what* is shown (ranges, wording) but never *how* it renders.
 * The source label always says whether the explanation was generated or is the app's own
 * pre-vetted fallback. Controls are plain steppers: no gesture is required.
 */

import React, { useState } from "react";
import { Pressable, StyleSheet, Text, View } from "react-native";

import type { BoardTheme } from "../board/palette";
import { type } from "../theme/tokens";

import {
  clampToRange,
  distributionAreas,
  groupingTotal,
  pluralize,
  type DistributionSpec,
  type GroupingSpec,
  type IntRange,
  type ReleasedExplanation,
} from "./explanationSpec";

export type ManipulativeTheme = Pick<
  BoardTheme,
  | "board"
  | "surfaceEdge"
  | "labelText"
  | "labelMuted"
  | "controlBackground"
  | "controlEdge"
  | "controlText"
  | "controlDisabled"
  | "studentInk"
  | "tutorInk"
>;

export type ExplanationManipulativeProps = {
  released: ReleasedExplanation;
  theme: ManipulativeTheme;
};

const CELL = 12;
const CELL_GAP = 1;
const GROUP_COLUMNS = 6;

function fallbackNote(reason: string | null): string | null {
  if (reason === null) {
    return null;
  }
  return reason === "integration_disabled" || reason === "not_configured"
    ? "Generated explanations are not turned on, so this one comes with the app."
    : "A generated explanation could not be released, so this one comes with the app.";
}

type StepperProps = {
  id: string;
  name: string;
  unit: string;
  range: IntRange;
  value: number;
  theme: ManipulativeTheme;
  onChange: (next: number) => void;
};

function Stepper({ id, name, unit, range, value, theme, onChange }: StepperProps) {
  const atMin = value <= range.min;
  const atMax = value >= range.max;
  const button = (
    suffix: "less" | "more",
    symbol: string,
    disabled: boolean,
    delta: number,
  ) => (
    <Pressable
      testID={`${id}-${suffix}`}
      accessibilityRole="button"
      accessibilityLabel={`${suffix === "less" ? "Decrease" : "Increase"} ${name}`}
      accessibilityState={{ disabled }}
      disabled={disabled}
      onPress={() => onChange(clampToRange(value + delta, range))}
      style={[
        styles.stepButton,
        { backgroundColor: theme.controlBackground, borderColor: theme.controlEdge },
        disabled ? styles.stepButtonDisabled : null,
      ]}
    >
      <Text style={[styles.stepSymbol, { color: disabled ? theme.controlDisabled : theme.controlText }]}>
        {symbol}
      </Text>
    </Pressable>
  );
  return (
    <View style={styles.stepperRow}>
      <Text style={[styles.stepperName, { color: theme.labelText }]}>{name}</Text>
      {button("less", "\u2212", atMin, -1)}
      <Text
        testID={`${id}-value`}
        accessibilityLabel={`${name}: ${value} ${unit}`}
        style={[styles.stepperValue, { color: theme.labelText }]}
      >
        {value}
      </Text>
      {button("more", "+", atMax, 1)}
    </View>
  );
}

function Cells({
  count,
  columns,
  color,
  testID,
}: {
  count: number;
  columns: number;
  color: string;
  testID: string;
}) {
  const width = columns * (CELL + CELL_GAP * 2);
  return (
    <View testID={testID} style={{ width, flexDirection: "row", flexWrap: "wrap" }}>
      {Array.from({ length: count }, (_, index) => (
        <View
          key={index}
          testID={`${testID}-cell`}
          style={{
            width: CELL,
            height: CELL,
            margin: CELL_GAP,
            backgroundColor: color,
          }}
        />
      ))}
    </View>
  );
}

function GroupingManipulative({
  spec,
  theme,
}: {
  spec: GroupingSpec;
  theme: ManipulativeTheme;
}) {
  const [groups, setGroups] = useState(spec.groups.initial);
  const [perGroup, setPerGroup] = useState(spec.per_group.initial);
  const total = groupingTotal(groups, perGroup);
  const item = spec.item_label;
  const readout = `${groups} ${pluralize(groups, "group")} \u00d7 ${perGroup} ${pluralize(perGroup, item)} each = ${total} ${pluralize(total, item)}`;
  return (
    <View>
      <Stepper
        id="groups"
        name="Groups"
        unit={pluralize(groups, "group")}
        range={spec.groups}
        value={groups}
        theme={theme}
        onChange={setGroups}
      />
      <Stepper
        id="per-group"
        name={`${pluralize(2, item)} in each group`.replace(/^./, (c) => c.toUpperCase())}
        unit={pluralize(perGroup, item)}
        range={spec.per_group}
        value={perGroup}
        theme={theme}
        onChange={setPerGroup}
      />
      <View
        testID="grouping-figure"
        accessible
        accessibilityLabel={readout}
        style={styles.figure}
      >
        {Array.from({ length: groups }, (_, index) => (
          <View
            key={index}
            testID="grouping-group"
            style={[styles.groupBox, { borderColor: theme.surfaceEdge }]}
          >
            <Cells
              testID={`grouping-group-${index}`}
              count={perGroup}
              columns={Math.min(perGroup, GROUP_COLUMNS)}
              color={theme.studentInk}
            />
          </View>
        ))}
      </View>
      <Text
        testID="manipulative-readout"
        accessibilityLiveRegion="polite"
        style={[styles.readout, { color: theme.labelText }]}
      >
        {readout}
      </Text>
    </View>
  );
}

function DistributionManipulative({
  spec,
  theme,
}: {
  spec: DistributionSpec;
  theme: ManipulativeTheme;
}) {
  const [outer, setOuter] = useState(spec.outer.initial);
  const [left, setLeft] = useState(spec.left.initial);
  const [right, setRight] = useState(spec.right.initial);
  const areas = distributionAreas(outer, left, right);
  const product = `${outer} \u00d7 (${left} + ${right}) = ${areas.whole}`;
  const split = `${outer} \u00d7 ${left} + ${outer} \u00d7 ${right} = ${areas.left} + ${areas.right} = ${areas.left + areas.right}`;
  return (
    <View>
      <Stepper
        id="outer"
        name="Outside number"
        unit={pluralize(outer, "row")}
        range={spec.outer}
        value={outer}
        theme={theme}
        onChange={setOuter}
      />
      <Stepper
        id="left"
        name="First part"
        unit={pluralize(left, "column")}
        range={spec.left}
        value={left}
        theme={theme}
        onChange={setLeft}
      />
      <Stepper
        id="right"
        name="Second part"
        unit={pluralize(right, "column")}
        range={spec.right}
        value={right}
        theme={theme}
        onChange={setRight}
      />
      <View
        testID="distribution-figure"
        accessible
        accessibilityLabel={`${product}. ${split}`}
        style={styles.figureRow}
      >
        <Cells testID="distribution-left" count={areas.left} columns={left} color={theme.studentInk} />
        <View style={styles.partGap} />
        <Cells testID="distribution-right" count={areas.right} columns={right} color={theme.tutorInk} />
      </View>
      <Text
        testID="manipulative-readout"
        accessibilityLiveRegion="polite"
        style={[styles.readout, { color: theme.labelText }]}
      >
        {`${product}\n${split}`}
      </Text>
    </View>
  );
}

export function ExplanationManipulative({ released, theme }: ExplanationManipulativeProps) {
  const { spec } = released;
  const note = fallbackNote(released.fallback_reason);
  // Re-key on the spec so a different explanation starts from its own initial values.
  const key = JSON.stringify(spec);
  return (
    <View
      testID="explanation-manipulative"
      style={[styles.card, { backgroundColor: theme.board, borderColor: theme.surfaceEdge }]}
    >
      <Text
        testID="explanation-source-label"
        accessibilityRole="text"
        style={[styles.sourceLabel, { color: theme.labelMuted }]}
      >
        {released.label}
      </Text>
      {note ? (
        <Text testID="explanation-fallback-note" style={[styles.note, { color: theme.labelMuted }]}>
          {note}
        </Text>
      ) : null}
      <Text accessibilityRole="header" style={[styles.title, { color: theme.labelText }]}>
        {spec.title}
      </Text>
      <Text style={[styles.prompt, { color: theme.labelText }]}>{spec.prompt}</Text>
      {spec.manipulative.component === "grouping" ? (
        <GroupingManipulative key={key} spec={spec.manipulative} theme={theme} />
      ) : (
        <DistributionManipulative key={key} spec={spec.manipulative} theme={theme} />
      )}
      <Text style={[styles.caption, { color: theme.labelMuted }]}>{spec.caption}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: { borderWidth: 2, borderRadius: 28, padding: 16, gap: 8 },
  sourceLabel: { ...type.meta },
  note: { ...type.small },
  title: { ...type.heading },
  prompt: { ...type.body },
  caption: { ...type.small },
  stepperRow: { flexDirection: "row", alignItems: "center", gap: 8, marginVertical: 4 },
  stepperName: { ...type.control, flexGrow: 1, flexShrink: 1 },
  stepButton: {
    minWidth: 44,
    minHeight: 44,
    borderWidth: 2,
    borderRadius: 999,
    alignItems: "center",
    justifyContent: "center",
  },
  stepButtonDisabled: { opacity: 0.45 },
  stepSymbol: { ...type.heading },
  stepperValue: { ...type.math, minWidth: 28, textAlign: "center" },
  figure: { flexDirection: "row", flexWrap: "wrap", gap: 8, marginVertical: 8 },
  figureRow: { flexDirection: "row", alignItems: "flex-start", marginVertical: 8 },
  groupBox: { borderWidth: 2, borderRadius: 20, padding: 4 },
  partGap: { width: 12 },
  readout: { ...type.math },
});
