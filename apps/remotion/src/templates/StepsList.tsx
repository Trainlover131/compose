import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate, Easing } from "remotion";
import { FadeIn, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE } from "../design-system";

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
  const foreground = fgColor(bg);
  const frame = useCurrentFrame();
  const bgStyle = proBgStyle(bg, accentColor);

  const staggerDelay = 6;
  const baseDelay = 12;

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        <div style={{ padding: "0 160px", width: "100%" }}>
          <FadeIn durationFrames={10}>
            <h1
              style={{
                color: foreground,
                fontSize: TYPE_SCALE.title,
                fontWeight: 700,
                marginBottom: 40,
                textAlign: "center",
                fontFamily: FONTS.primary,
              }}
            >
              {title}
            </h1>
          </FadeIn>

          <div style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 1400, margin: "0 auto" }}>
            {steps.slice(0, 8).map((step, i) => {
              const delay = baseDelay + i * staggerDelay;
              const progress = interpolate(
                frame - delay,
                [0, 12],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
              );

              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 20,
                    opacity: progress,
                    transform: `translateX(${(1 - progress) * 24}px)`,
                  }}
                >
                  <div
                    style={{
                      width: 40,
                      height: 40,
                      borderRadius: 20,
                      backgroundColor: accentColor,
                      display: "flex",
                      alignItems: "center",
                      justifyContent: "center",
                      flexShrink: 0,
                      transform: `scale(${progress})`,
                      boxShadow: `0 0 16px ${accentColor}33`,
                    }}
                  >
                    <span
                      style={{
                        color: "#FFFFFF",
                        fontSize: TYPE_SCALE.caption,
                        fontWeight: 700,
                        fontFamily: FONTS.primary,
                      }}
                    >
                      {i + 1}
                    </span>
                  </div>
                  <p
                    style={{
                      color: foreground,
                      fontSize: TYPE_SCALE.subtitle,
                      fontWeight: 500,
                      lineHeight: 1.3,
                      fontFamily: FONTS.primary,
                    }}
                  >
                    {step}
                  </p>
                </div>
              );
            })}
          </div>
        </div>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
