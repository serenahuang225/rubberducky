/**
 * The tiny tutor avatar with its real status in words. The figure never bounces or
 * implies competence; the state comes from application facts (see deriveAvatarStatus)
 * and is exposed as text and as part of the accessible name.
 */

import React from "react";
import { StyleSheet, Text, View } from "react-native";

import type { Personality } from "../api/contracts";
import type { BoardTheme } from "../board/palette";
import type { AvatarStatus } from "../state/avatarStatus";
import { type } from "../theme/tokens";

import { DuckPortrait } from "./DuckPortrait";

export type TutorAvatarProps = {
  personality: Personality;
  theme: BoardTheme;
  tutorName: string;
  status: AvatarStatus;
};

export function TutorAvatar({
  personality,
  theme,
  tutorName,
  status,
}: TutorAvatarProps) {
  return (
    <View style={styles.row}>
      <DuckPortrait
        personality={personality}
        size={84}
        label={`${tutorName} avatar: ${status.label}. ${status.description}`}
      />
      <Text
        testID="avatar-status"
        accessibilityLiveRegion="polite"
        style={[styles.status, { color: theme.labelText }]}
      >
        {status.label}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: "column", alignItems: "flex-start", gap: 4 },
  status: type.meta,
});
