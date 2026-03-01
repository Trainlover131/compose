import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";
import { FadeIn, SlideUp, ScaleSpring } from "../components/AnimationPrimitives";
import { FONTS, bgColor, fgColor, PALETTE } from "../design-system";

export interface StepsListProps {
  title: string;
  steps: string[];
  accentColor?: string;
  bg?: "dark" | "light";
}

export const StepsList: React.FC<StepsListProps> = ({
  title,
  steps,
  accentColor = PALETTE.default_accent,
  bg = "dark",
}) => {
  const background = bgColor(bg);
  const foreground = fgColor(bg);
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();

  // Stagger step reveals: each step appears ~8 frames apart
  const staggerDelay = 8;
  const baseDelay = 15; // after title

  return (
    <AbsoluteFill
      style={{
        backgroundColor: background,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 160px",
        fontFamily: FONTS.primary,
      }}
    >
      <FadeIn durationFrames={12}>
        <h1
          style={{
            color: foreground,
            fontSize: 52,
            fontWeight: 700,
            marginBottom: 48,
            textAlign: "center",
          }}
        >
          {title}
        </h1>
      </FadeIn>

      <div style={{ display: "flex", flexDirection: "column", gap: 28, width: "100%", maxWidth: 1400 }}>
        {steps.slice(0, 8).map((step, i) => {
          const delay = baseDelay + i * staggerDelay;
          const progress = interpolate(
            frame - delay,
            [0, 15],
            [0, 1],
            { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
          );

          return (
            <div
              key={i}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 24,
                opacity: progress,
                transform: `translateX(${(1 - progress) * 30}px)`,
              }}
            >
              <div
                style={{
                  width: 44,
                  height: 44,
                  borderRadius: 22,
                  backgroundColor: accentColor,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  flexShrink: 0,
                  transform: `scale(${progress})`,
                }}
              >
                <span
                  style={{
                    color: "#FFFFFF",
                    fontSize: 22,
                    fontWeight: 700,
                  }}
                >
                  {i + 1}
                </span>
              </div>
              <p
                style={{
                  color: foreground,
                  fontSize: 36,
                  fontWeight: 500,
                  lineHeight: 1.3,
                }}
              >
                {step}
              </p>
            </div>
          );
        })}
      </div>
    </AbsoluteFill>
  );
};
