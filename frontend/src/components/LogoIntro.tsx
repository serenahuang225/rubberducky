/**
 * Covers the first paint with the mark, then fades it away so the screen that was
 * already underneath is what remains. Reduced motion cuts straight across.
 */

import React, { useEffect, useRef, useState } from "react";
import { Animated, Image, Platform, StyleSheet } from "react-native";

import { BRAND } from "../board/palette";
import type { MotionMode } from "../feedback/preferences";

const logo = require("../../assets/logo.jpeg");

const HOLD_MS = 700;
const FADE_MS = 650;

export function LogoIntro({
  ready,
  motion,
}: {
  ready: boolean;
  motion: MotionMode;
}) {
  const opacity = useRef(new Animated.Value(1)).current;
  const [gone, setGone] = useState(false);

  useEffect(() => {
    if (!ready || gone) return;
    const reduced = motion !== "full";
    const hold = setTimeout(() => {
      if (reduced) {
        setGone(true);
        return;
      }
      Animated.timing(opacity, {
        toValue: 0,
        duration: FADE_MS,
        useNativeDriver: Platform.OS !== "web",
      }).start(({ finished }) => {
        if (finished) setGone(true);
      });
    }, HOLD_MS);
    return () => clearTimeout(hold);
  }, [gone, motion, opacity, ready]);

  if (gone) return null;

  return (
    <Animated.View
      testID="logo-intro"
      pointerEvents="auto"
      accessibilityElementsHidden
      importantForAccessibility="no-hide-descendants"
      style={[styles.cover, { opacity, backgroundColor: BRAND.white }]}
    >
      <Image
        source={logo}
        accessibilityLabel="Rubberducky"
        resizeMode="contain"
        style={styles.logo}
      />
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  cover: {
    position: "absolute",
    top: 0,
    right: 0,
    bottom: 0,
    left: 0,
    zIndex: 40,
    alignItems: "center",
    justifyContent: "center",
  },
  logo: {
    width: "86%",
    maxWidth: 520,
    aspectRatio: 1,
  },
});
