/**
 * Shared frame for the full-screen Settings and Memory panels: a named heading that takes
 * focus when the panel opens (so keyboard and screen-reader users land inside it), a clearly
 * named close control, and a scrolling body.
 */

import React, { useEffect, useRef } from "react";
import { Pressable, ScrollView, StyleSheet, Text, View } from "react-native";

import type { BoardTheme } from "../board/palette";

export type ScreenFrameProps = {
  theme: BoardTheme;
  title: string;
  testID: string;
  closeLabel: string;
  onClose: () => void;
  children: React.ReactNode;
};

export function ScreenFrame({
  theme,
  title,
  testID,
  closeLabel,
  onClose,
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
      style={[styles.frame, { backgroundColor: theme.boardGrain }]}
    >
      <View style={styles.header}>
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
          style={[styles.close, { backgroundColor: theme.controlBackground }]}
        >
          <Text style={[styles.closeText, { color: theme.controlText }]}>
            {closeLabel}
          </Text>
        </Pressable>
      </View>
      <ScrollView
        style={styles.body}
        contentContainerStyle={styles.bodyContent}
      >
        {children}
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  frame: { flex: 1, padding: 12, gap: 10 },
  header: { flexDirection: "row", alignItems: "center", gap: 12 },
  headingBox: { flex: 1, minHeight: 44, justifyContent: "center" },
  title: { fontSize: 24, fontWeight: "700" },
  close: {
    minHeight: 44,
    paddingHorizontal: 18,
    borderRadius: 10,
    alignItems: "center",
    justifyContent: "center",
  },
  closeText: { fontSize: 16, fontWeight: "600" },
  body: { flex: 1 },
  bodyContent: {
    gap: 18,
    paddingBottom: 32,
    maxWidth: 900,
    width: "100%",
    alignSelf: "center",
  },
});
