import React from "react";
import { AbsoluteFill } from "remotion";
import { FadeIn, SlideUp, CountUpNumber, DrawLine, ProSceneWrapper } from "../components/AnimationPrimitives";
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

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        <FadeIn durationFrames={10}>
          <p
            style={{
              color: PALETTE.muted,
              fontSize: TYPE_SCALE.subtitle,
              fontWeight: 500,
              letterSpacing: 3,
              textTransform: "uppercase",
              marginBottom: 12,
              fontFamily: FONTS.primary,
            }}
          >
            {label}
          </p>
        </FadeIn>

        <SlideUp durationFrames={14} delay={4} distance={25}>
          <CountUpNumber
            value={value}
            prefix={prefix}
            suffix={suffix}
            durationFrames={40}
            delay={6}
            style={{
              color: foreground,
              fontSize: TYPE_SCALE.hero,
              fontWeight: 700,
              letterSpacing: -3,
              fontFamily: FONTS.primary,
            }}
          />
        </SlideUp>

        <SlideUp durationFrames={12} delay={10}>
          <DrawLine
            color={accentColor}
            width={140}
            thickness={4}
            durationFrames={18}
            delay={12}
          />
        </SlideUp>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
