import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate, Easing } from "remotion";
import { FadeIn, SlideUp, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE, TEXT_STYLES } from "../design-system";

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

  const staggerDelay = 5;
  const baseDelay = 12;

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        <div style={{ padding: "0 140px", width: "100%", alignSelf: "flex-start", marginTop: 140 }}>
          {/* Small label */}
          <FadeIn durationFrames={8} delay={3}>
            <p style={{ ...TEXT_STYLES.label, fontSize: TYPE_SCALE.caption, color: PALETTE.white, marginBottom: 8 }}>
              {title}
            </p>
          </FadeIn>

          {/* Larger heading */}
          <SlideUp durationFrames={12} delay={5} distance={20}>
            <h1
              style={{
                color: foreground,
                fontSize: TYPE_SCALE.title,
                fontWeight: 700,
                fontFamily: FONTS.display,
                marginBottom: 40,
              }}
            >
              {title}
            </h1>
          </SlideUp>

          <div style={{ display: "flex", flexDirection: "column", gap: 22, maxWidth: 1400 }}>
            {steps.slice(0, 8).map((step, i) => {
              const delay = baseDelay + i * staggerDelay;
              const progress = interpolate(
                frame - delay,
                [0, 10],
                [0, 1],
                { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
              );

              return (
                <div
                  key={i}
                  style={{
                    display: "flex",
                    alignItems: "center",
                    gap: 18,
                    opacity: progress,
                    transform: `translateY(${(1 - progress) * 16}px)`,
                  }}
                >
                  <div
                    style={{
                      width: 36,
                      height: 36,
                      borderRadius: 18,
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
                        fontSize: TYPE_SCALE.micro + 2,
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
                      fontSize: TYPE_SCALE.subtitle - 2,
                      fontWeight: 500,
                      lineHeight: 1.3,
                      fontFamily: FONTS.ui,
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
