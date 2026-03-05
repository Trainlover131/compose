import React from "react";
import { AbsoluteFill } from "remotion";
import {
  CountUpNumber,
  DrawLine,
  HeroStack,
  CornerBadge,
  ProSceneWrapper,
  FadeIn,
} from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE, TEXT_STYLES } from "../design-system";

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
  const formatted = `${prefix}${value.toLocaleString()}${suffix}`;

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        {/* Corner badge */}
        <CornerBadge label={label} value={formatted} />

        {/* Main content — centered vertically, left-padded */}
        <div style={{ padding: "0 60px", width: "100%" }}>
          <HeroStack
            label={label}
            value={formatted}
            ghostValue={formatted}
            accentColor={accentColor}
            align="center"
          />

          {/* Animated count-up overlaid on the hero position */}
          <div style={{ position: "relative", marginTop: -TYPE_SCALE.hero - 10, textAlign: "center" }}>
            <CountUpNumber
              value={value}
              prefix={prefix}
              suffix={suffix}
              durationFrames={25}
              delay={5}
              style={{
                ...TEXT_STYLES.heroNumber,
                fontSize: TYPE_SCALE.hero,
                color: foreground,
              }}
            />
          </div>

          {/* Accent underline */}
          <FadeIn durationFrames={8} delay={14}>
            <div style={{ marginTop: 16, display: "flex", justifyContent: "center" }}>
              <DrawLine
                color={accentColor}
                width={140}
                thickness={4}
                durationFrames={14}
                delay={16}
              />
            </div>
          </FadeIn>
        </div>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
