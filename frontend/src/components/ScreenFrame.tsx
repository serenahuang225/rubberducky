/**
 * Shared frame for the full-screen Settings and Memory panels: a named heading that takes
 * focus when the panel opens (so keyboard and screen-reader users land inside it), a clearly
 * named close control, and a scrolling body.
 */

import React, { useEffect, useRef } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import type { BoardTheme } from "../board/palette";
import type { MotionMode } from "../feedback/preferences";
import { radius, space, type } from "../theme/tokens";
import { enterProps } from "../theme/webTheme";

export type ScreenFrameProps = {
  theme: BoardTheme;
  title: string;
  testID: string;
  closeLabel: string;
  onClose: () => void;
  /** Panel entrance runs only when motion is full. */
  motion?: MotionMode;
  children: React.ReactNode;
};

export function ScreenFrame({
  theme,
  title,
  testID,
  closeLabel,
  onClose,
  motion = "full",
  children,
}: ScreenFrameProps) {
  const headingRef = useRef<View>(null);

  useEffect(() => {
    // `focus` exists on web elements and is absent on native views, where the heading's
    // accessibility focus is announced instead.
    (headingRef.current as unknown as { focus?: () => void } | null)?.focus?.();
  }, []);

  return (
    <View
      testID={testID}
      {...enterProps(motion)}
      style={[styles.frame, { backgroundColor: theme.board }]}
    >
      <View
        style={[
          styles.header,
          { borderBottomColor: theme.surfaceEdge },
        ]}
      >
        <View
          ref={headingRef}
          focusable
          accessible
          accessibilityRole="header"
          accessibilityLabel={title}
          testID={`${testID}-heading`}
          style={styles.headingBox}
        >
          <Text style={[styles.title, { color: theme.labelText }]}>
            {title}
          </Text>
        </View>
        <Pressable
          testID={`${testID}-close`}
          accessibilityRole="button"
          accessibilityLabel={closeLabel}
          onPress={onClose}
          style={[
            styles.close,
            {
              backgroundColor: "transparent",
              borderColor: theme.controlEdge,
            },
          ]}
        >
          <Text style={[styles.closeText, { color: theme.labelText }]}>
            {closeLabel}
          </Text>
        </Pressable>
      </View>
      <ScrollView
        style={styles.body}
        contentContainerStyle={styles.bodyContent}
      >
        <View style={styles.column}>{children}</View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: {
    flex: 1,
    paddingTop: space.lg,
    gap: space.md,
  },
  header: {
    flexDirection: "row",
    alignItems: "center",
    gap: space.md,
    borderBottomWidth: StyleSheet.hairlineWidth,
    paddingBottom: space.lg,
    paddingHorizontal: space.xl,
  },
  headingBox: { flex: 1, minHeight: 44, justifyContent: "center" },
  title: type.title,
  close: {
    minHeight: 44,
    paddingHorizontal: space.lg,
    borderWidth: 2,
    borderRadius: radius.pill,
    alignItems: "center",
    justifyContent: "center",
  },
  closeText: type.control,
  body: { flex: 1, alignSelf: "stretch" },
  bodyContent: {
    width: "100%",
    flexGrow: 1,
    paddingTop: space.md,
    paddingBottom: space.xxl,
  },
  column: {
    gap: space.xl,
    paddingHorizontal: space.xl,
    maxWidth: 720,
    width: "100%",
    alignSelf: "center",
  },
});
