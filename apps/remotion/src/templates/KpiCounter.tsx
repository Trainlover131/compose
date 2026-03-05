import React from "react";
import { AbsoluteFill } from "remotion";
import {
  FadeIn,
  ScaleSpring,
  CountUpNumber,
  DrawLine,
  HeroStack,
  ProSceneWrapper,
} from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE } from "../design-system";

export interface KpiCounterProps {
  label: string;
  value: number;
  prefix?: string;
  suffix?: string;
  accentColor?: string;
  bg?: "dark" | "light";
}

export const KpiCounter: React.FC<KpiCounterProps> = ({
  label,
  value,
  prefix = "",
  suffix = "",
  accentColor = PALETTE.default_accent,
  bg = "dark",
}) => {
  const foreground = fgColor(bg);
  const bgStyle = proBgStyle(bg, accentColor);
  const ghostText = prefix + value.toLocaleString() + suffix;

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        <ScaleSpring delay={5}>
          <HeroStack
            label={label}
            hero={
              <CountUpNumber
                value={value}
                prefix={prefix}
                suffix={suffix}
                durationFrames={50}
                delay={8}
                style={{
                  color: foreground,
                  fontSize: TYPE_SCALE.hero,
                  fontWeight: 700,
                  letterSpacing: -2,
                  fontFamily: FONTS.display,
                }}
              />
            }
            ghost={ghostText}
            color={foreground}
            accentColor={accentColor}
            anchor="center"
          />
        </ScaleSpring>

        <FadeIn durationFrames={12} delay={18}>
          <DrawLine
            color={accentColor}
            width={140}
            thickness={4}
            durationFrames={20}
            delay={20}
          />
        </FadeIn>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
