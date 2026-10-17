/**
 * Original, lightweight companion artwork drawn with react-native-svg primitives.
 *
 * The three appearances are simple friendly figures bundled with the app (no network
 * assets, no generated art). Appearance is decorative: it never changes wording, hints or
 * pacing, and none of the figures is styled to imply competence.
 */

import React from 'react';
import { View } from 'react-native';
import Svg, { Circle, Ellipse, Path, Rect } from 'react-native-svg';

import type { Appearance } from '../api/contracts';

export type AvatarFigureProps = {
  appearance: Appearance;
  size?: number;
  /** Accessible name for the figure, e.g. "Sunny the duck, selected". */
  label: string;
};

const VIEWBOX = 96;

function DuckFigure() {
  return (
    <>
      {/* body */}
      <Ellipse cx={48} cy={62} rx={30} ry={24} fill="#F5C94C" />
      {/* head */}
      <Circle cx={56} cy={34} r={18} fill="#F7D774" />
      {/* beak */}
      <Path d="M 72 34 L 88 38 L 72 43 Z" fill="#E8892B" />
      {/* eye */}
      <Circle cx={60} cy={30} r={3} fill="#233038" />
      {/* wing */}
      <Path d="M 30 58 Q 48 50 58 62 Q 44 72 30 66 Z" fill="#EDB93E" />
      {/* water ripple */}
      <Path d="M 18 84 Q 30 80 42 84 T 66 84 T 90 84" stroke="#7FB6C9" strokeWidth={3} fill="none" strokeLinecap="round" />
    </>
  );
}

function OlderAdultFigure() {
  return (
    <>
      {/* hair bun */}
      <Circle cx={48} cy={16} r={9} fill="#B9C0C7" />
      {/* hair */}
      <Path d="M 20 44 Q 20 18 48 18 Q 76 18 76 44 L 70 44 Q 70 26 48 26 Q 26 26 26 44 Z" fill="#C7CDD4" />
      {/* face */}
      <Circle cx={48} cy={46} r={24} fill="#F2D3B3" />
      {/* glasses */}
      <Circle cx={39} cy={44} r={7} fill="none" stroke="#3E4C59" strokeWidth={2.4} />
      <Circle cx={57} cy={44} r={7} fill="none" stroke="#3E4C59" strokeWidth={2.4} />
      <Path d="M 46 44 L 50 44" stroke="#3E4C59" strokeWidth={2.4} />
      {/* eyes */}
      <Circle cx={39} cy={44} r={2.2} fill="#233038" />
      <Circle cx={57} cy={44} r={2.2} fill="#233038" />
      {/* warm smile */}
      <Path d="M 38 56 Q 48 64 58 56" stroke="#8C5B3F" strokeWidth={2.6} fill="none" strokeLinecap="round" />
      {/* shoulders */}
      <Path d="M 22 88 Q 48 66 74 88 Z" fill="#6B7F8C" />
    </>
  );
}

function YoungerAdultFigure() {
  return (
    <>
      {/* face */}
      <Circle cx={48} cy={46} r={24} fill="#E8B98F" />
      {/* hair cap */}
      <Path d="M 24 42 Q 22 18 48 18 Q 74 18 72 42 Q 62 28 48 30 Q 34 32 24 42 Z" fill="#4A3728" />
      {/* eyes */}
      <Circle cx={40} cy={46} r={2.6} fill="#233038" />
      <Circle cx={56} cy={46} r={2.6} fill="#233038" />
      {/* smile */}
      <Path d="M 40 58 Q 48 65 56 58" stroke="#8C5B3F" strokeWidth={2.6} fill="none" strokeLinecap="round" />
      {/* hoodie shoulders */}
      <Path d="M 20 90 Q 48 64 76 90 Z" fill="#3F7E8C" />
      <Rect x={44} y={74} width={8} height={10} rx={3} fill="#356874" />
    </>
  );
}

export function AvatarFigure({ appearance, size = 64, label }: AvatarFigureProps) {
  return (
    <View
      accessibilityLabel={label}
      accessibilityRole="image"
      style={{ width: size, height: size }}
    >
      <Svg width={size} height={size} viewBox={`0 0 ${VIEWBOX} ${VIEWBOX}`}>
        {appearance === 'animal' ? <DuckFigure /> : null}
        {appearance === 'older_adult' ? <OlderAdultFigure /> : null}
        {appearance === 'younger_adult' ? <YoungerAdultFigure /> : null}
      </Svg>
    </View>
  );
}
