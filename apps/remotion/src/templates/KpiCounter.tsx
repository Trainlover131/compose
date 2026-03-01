import React from "react";
import { AbsoluteFill } from "remotion";
import { FadeIn, SlideUp, CountUpNumber, DrawLine } from "../components/AnimationPrimitives";
import { FONTS, bgColor, fgColor, PALETTE } from "../design-system";

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
  const background = bgColor(bg);
  const foreground = fgColor(bg);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: background,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: FONTS.primary,
      }}
    >
      <FadeIn durationFrames={12}>
        <p
          style={{
            color: PALETTE.muted,
            fontSize: 36,
            fontWeight: 500,
            letterSpacing: 2,
            textTransform: "uppercase",
            marginBottom: 16,
          }}
        >
          {label}
        </p>
      </FadeIn>

      <SlideUp durationFrames={18} delay={6} distance={30}>
        <CountUpNumber
          value={value}
          prefix={prefix}
          suffix={suffix}
          durationFrames={50}
          delay={10}
          style={{
            color: foreground,
            fontSize: 128,
            fontWeight: 700,
            letterSpacing: -2,
          }}
        />
      </SlideUp>

      <SlideUp durationFrames={15} delay={14}>
        <DrawLine
          color={accentColor}
          width={160}
          thickness={4}
          durationFrames={25}
          delay={18}
        />
      </SlideUp>
    </AbsoluteFill>
  );
};
