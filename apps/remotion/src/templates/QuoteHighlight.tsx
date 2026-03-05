import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate } from "remotion";
import { FadeIn, SlideUp, MaskReveal, DrawLine, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE, OPACITY, TEXT_STYLES } from "../design-system";

export interface QuoteHighlightProps {
  quote: string;
  attribution?: string;
  accentColor?: string;
  bg?: "dark" | "light";
  serif?: boolean;
}

export const QuoteHighlight: React.FC<QuoteHighlightProps> = ({
  quote,
  attribution,
  accentColor = PALETTE.default_accent,
  bg = "dark",
  serif = false,
}) => {
  const foreground = fgColor(bg);
  const fontFamily = serif ? FONTS.serifEditorialOnly : FONTS.display;
  const bgStyle = proBgStyle(bg, accentColor);
  const frame = useCurrentFrame();

  const ghostOp = interpolate(frame, [3, 12], [0, OPACITY.ghost], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        {/* Ghost quote mark behind */}
        <div
          style={{
            position: "absolute",
            top: 400,
            left: 30,
            fontSize: 240,
            fontFamily: FONTS.display,
            fontWeight: 800,
            color: PALETTE.white,
            opacity: ghostOp,
            filter: "blur(1.5px)",
            lineHeight: 1,
            pointerEvents: "none",
          }}
        >
          &ldquo;
        </div>

        <div style={{ display: "flex", flexDirection: "column", alignItems: "flex-start", padding: "0 60px", width: "100%", position: "relative", zIndex: 1 }}>
          {/* Accent bar */}
          <SlideUp durationFrames={10} delay={3}>
            <div
              style={{
                width: 4,
                height: 60,
                backgroundColor: accentColor,
                borderRadius: 2,
                marginBottom: 24,
                boxShadow: `0 0 20px ${accentColor}44`,
              }}
            />
          </SlideUp>

          {/* Quote text */}
          <MaskReveal durationFrames={18} delay={6} direction="left">
            <p
              style={{
                color: foreground,
                fontSize: TYPE_SCALE.title - 4,
                fontWeight: serif ? 400 : 600,
                lineHeight: 1.35,
                fontFamily,
                fontStyle: serif ? "italic" : "normal",
                maxWidth: 960,
              }}
            >
              &ldquo;{quote}&rdquo;
            </p>
          </MaskReveal>

          {/* Accent underline */}
          <FadeIn durationFrames={8} delay={18}>
            <div style={{ marginTop: 18 }}>
              <DrawLine color={accentColor} width={70} thickness={3} durationFrames={12} delay={20} />
            </div>
          </FadeIn>

          {/* Attribution */}
          {attribution && (
            <FadeIn durationFrames={10} delay={22}>
              <p
                style={{
                  ...TEXT_STYLES.label,
                  fontSize: TYPE_SCALE.body - 2,
                  color: PALETTE.muted,
                  fontWeight: 500,
                  marginTop: 14,
                }}
              >
                &mdash; {attribution}
              </p>
            </FadeIn>
          )}
        </div>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
