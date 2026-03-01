import React from "react";
import { AbsoluteFill } from "remotion";
import { FadeIn, SlideUp, DrawLine, MaskReveal } from "../components/AnimationPrimitives";
import { FONTS, bgColor, fgColor, PALETTE } from "../design-system";

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
  const background = bgColor(bg);
  const foreground = fgColor(bg);
  const fontFamily = serif ? FONTS.serif : FONTS.primary;

  return (
    <AbsoluteFill
      style={{
        backgroundColor: background,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        padding: "0 120px",
        fontFamily: FONTS.primary,
      }}
    >
      {/* Accent bar on left */}
      <div style={{ display: "flex", alignItems: "flex-start", gap: 40 }}>
        <SlideUp durationFrames={15} delay={0}>
          <div
            style={{
              width: 5,
              height: 120,
              backgroundColor: accentColor,
              borderRadius: 3,
              flexShrink: 0,
            }}
          />
        </SlideUp>

        <div>
          <MaskReveal durationFrames={25} delay={6} direction="left">
            <p
              style={{
                color: foreground,
                fontSize: 56,
                fontWeight: serif ? 400 : 600,
                lineHeight: 1.4,
                fontFamily,
                fontStyle: serif ? "italic" : "normal",
                maxWidth: 1400,
              }}
            >
              &ldquo;{quote}&rdquo;
            </p>
          </MaskReveal>

          {attribution && (
            <FadeIn durationFrames={15} delay={25}>
              <p
                style={{
                  color: PALETTE.muted,
                  fontSize: 28,
                  fontWeight: 500,
                  marginTop: 24,
                }}
              >
                &mdash; {attribution}
              </p>
            </FadeIn>
          )}
        </div>
      </div>
    </AbsoluteFill>
  );
};
