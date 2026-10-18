/**
 * The five rubber-duck portraits. Decorative inside a labeled choice; named when
 * the portrait itself is the tutor avatar.
 */

import React from "react";
import { Image, type ImageSourcePropType } from "react-native";

import type { Personality } from "../api/contracts";

const PORTRAITS: Record<Personality, ImageSourcePropType> = {
  vincent: require("../../assets/ducks/vincent.png"),
  zeeshan: require("../../assets/ducks/zeeshan.png"),
  tony: require("../../assets/ducks/tony.png"),
  janelle: require("../../assets/ducks/janelle.png"),
  mary: require("../../assets/ducks/mary.png"),
};

export type DuckPortraitProps = {
  personality: Personality;
  size: number;
  /** Set when this image is the accessible avatar. Omit inside an already-labeled card. */
  label?: string;
};

export function DuckPortrait({ personality, size, label }: DuckPortraitProps) {
  const named = label !== undefined;
  return (
    <Image
      accessible={named}
      accessibilityRole={named ? "image" : undefined}
      accessibilityLabel={label}
      accessibilityElementsHidden={!named}
      importantForAccessibility={named ? "yes" : "no-hide-descendants"}
      source={PORTRAITS[personality]}
      resizeMode="contain"
      style={{ width: size, height: size }}
    />
  );
}
