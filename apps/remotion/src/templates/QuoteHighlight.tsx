import React from "react";
import { AbsoluteFill } from "remotion";
import { FadeIn, SlideUp, MaskReveal, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor } from "../design-system";

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
  const fontFamily = serif ? FONTS.serif : FONTS.ui;
  const bgStyle = proBgStyle(bg, accentColor);

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        <div style={{ display: "flex", alignItems: "flex-start", gap: 32, padding: "0 60px", maxWidth: 960 }}>
          <SlideUp durationFrames={15} delay={0}>
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
            <MaskReveal durationFrames={25} delay={6} direction="left">
              <p
                style={{
                  color: foreground,
                  fontSize: 44,
                  fontWeight: serif ? 400 : 600,
                  lineHeight: 1.4,
                  fontFamily,
                  fontStyle: serif ? "italic" : "normal",
                  maxWidth: 800,
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
                    fontSize: 24,
                    fontWeight: 500,
                    fontFamily: FONTS.ui,
                    marginTop: 20,
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
