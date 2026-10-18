/**
 * A button that explains itself when held.
 * A short press runs the action. A press-and-hold does not: it only shows what the button does.
 */

import React, { useRef, useState } from "react";
import {
  Pressable,
  StyleSheet,
  Text,
  View,
  type PressableProps,
  type StyleProp,
  type ViewStyle,
} from "react-native";

import type { BoardTheme } from "../board/palette";
import { radius, type } from "../theme/tokens";

type Props = Omit<PressableProps, "onPress" | "style"> & {
  overview: string;
  theme: BoardTheme;
  onPress: () => void;
  style?: StyleProp<ViewStyle> | PressableProps["style"];
};

export function HoldPressable({
  overview,
  theme,
  onPress,
  style,
  disabled,
  children,
  ...rest
}: Props) {
  const held = useRef(false);
  const [open, setOpen] = useState(false);
  return (
    <View style={styles.wrap}>
      <Pressable
        {...rest}
        disabled={disabled}
        delayLongPress={420}
        onLongPress={() => {
          held.current = true;
          setOpen(true);
        }}
        onPressOut={() => setOpen(false)}
        onPress={() => {
          if (held.current) {
            held.current = false;
            return;
          }
          onPress();
        }}
        style={style}
      >
        {children}
      </Pressable>
      {open ? (
        <View
          pointerEvents="none"
          accessibilityLiveRegion="polite"
          style={[
            styles.tip,
            { backgroundColor: theme.surface, borderColor: theme.surfaceEdge },
          ]}
        >
          <Text style={[styles.tipText, { color: theme.labelText }]}>{overview}</Text>
        </View>
      ) : null}
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { position: "relative", zIndex: 5 },
  tip: {
    position: "absolute",
    bottom: "100%",
    right: 0,
    marginBottom: 8,
    width: 220,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderWidth: 2,
    borderRadius: radius.md,
    zIndex: 20,
  },
  tipText: type.small,
});
