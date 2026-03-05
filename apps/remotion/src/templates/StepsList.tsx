import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";
import { FadeIn, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor } from "../design-system";

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

  const staggerDelay = 8;
  const baseDelay = 15;

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        <div style={{ padding: "0 80px", maxWidth: 960, width: "100%" }}>
          <FadeIn durationFrames={12}>
            <h1
              style={{
                color: foreground,
                fontSize: 44,
                fontWeight: 700,
                fontFamily: FONTS.display,
                marginBottom: 48,
                textAlign: "center",
              }}
            >
              {title}
            </h1>
          </FadeIn>

          <div style={{ display: "flex", flexDirection: "column", gap: 28, width: "100%" }}>
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
                    gap: 20,
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
                        fontSize: 20,
                        fontWeight: 700,
                        fontFamily: FONTS.ui,
                      }}
                    >
                      {i + 1}
                    </span>
                  </div>
                  <p
                    style={{
                      color: foreground,
                      fontSize: 32,
                      fontWeight: 500,
                      fontFamily: FONTS.ui,
                      lineHeight: 1.3,
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
