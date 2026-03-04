import React from "react";
import { AbsoluteFill } from "remotion";
import { FadeIn, SlideUp, MaskReveal, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE } from "../design-system";

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
  const fontFamily = serif ? FONTS.serif : FONTS.primary;
  const bgStyle = proBgStyle(bg, accentColor);

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 40, padding: "0 120px" }}>
          <SlideUp durationFrames={12} delay={0}>
            <div
              style={{
                width: 5,
                height: 100,
                backgroundColor: accentColor,
                borderRadius: 3,
                flexShrink: 0,
                boxShadow: `0 0 20px ${accentColor}44`,
              }}
            />
          </SlideUp>

          <div>
            <MaskReveal durationFrames={20} delay={4} direction="left">
              <p
                style={{
                  color: foreground,
                  fontSize: TYPE_SCALE.title + 4,
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
              <FadeIn durationFrames={12} delay={18}>
                <p
                  style={{
                    color: PALETTE.muted,
                    fontSize: TYPE_SCALE.body,
                    fontWeight: 500,
                    marginTop: 20,
                    fontFamily: FONTS.primary,
                  }}
                >
                  &mdash; {attribution}
                </p>
              </FadeIn>
            )}
          </div>
        </div>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
