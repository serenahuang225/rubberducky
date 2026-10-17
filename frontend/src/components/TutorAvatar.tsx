/**
 * The tiny tutor avatar with its real status in words. The figure never animates to imply
 * activity; the state comes from application facts (see deriveAvatarStatus) and is exposed as
 * text and as part of the accessible name, so nothing is conveyed by motion or color alone.
 */

import React from "react";
import { StyleSheet, Text, View } from "react-native";

import type { Appearance } from "../api/contracts";
import type { BoardTheme } from "../board/palette";
import type { AvatarStatus } from "../state/avatarStatus";

import { AvatarFigure } from "./AvatarFigure";

export type TutorAvatarProps = {
  appearance: Appearance;
  theme: BoardTheme;
  tutorName: string;
  status: AvatarStatus;
};

export function TutorAvatar({
  appearance,
  theme,
  tutorName,
  status,
}: TutorAvatarProps) {
  return (
    <View style={styles.row}>
      <AvatarFigure
        appearance={appearance}
        size={44}
        label={`${tutorName} avatar: ${status.label}. ${status.description}`}
      />
      <Text
        testID="avatar-status"
        accessibilityLiveRegion="polite"
        style={[styles.status, { color: theme.labelMuted }]}
      >
        {status.label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { alignItems: "center", gap: 2, minWidth: 64 },
  status: { fontSize: 12, fontWeight: "600", textAlign: "center" },
});
