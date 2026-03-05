import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate, Easing } from "remotion";
import { FadeIn, SlideUp, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE } from "../design-system";

export interface CodeCardProps {
  title?: string;
  code: string;
  accentColor?: string;
  bg?: "dark" | "light";
}

export const CodeCard: React.FC<CodeCardProps> = ({
  title,
  code,
  accentColor = PALETTE.default_accent,
  bg = "dark",
}) => {
  const foreground = fgColor(bg);
  const frame = useCurrentFrame();
  const bgStyle = proBgStyle(bg, accentColor);

  const lines = code.split("\n");
  const totalChars = code.length;
  const revealedChars = Math.round(
    interpolate(frame, [8, Math.max(18, 8 + totalChars * 0.5)], [0, totalChars], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
      easing: Easing.out(Easing.cubic),
    })
  );

  let charCount = 0;
  const visibleLines = lines.map((line) => {
    const lineStart = charCount;
    charCount += line.length + 1;
    const visible = Math.max(0, Math.min(line.length, revealedChars - lineStart));
    return line.substring(0, visible);
  });

  const codeBgColor = bg === "dark" ? "#111118" : "#F0F0F5";
  const codeFrameColor = bg === "dark" ? "#222233" : "#E0E0E8";

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        {title && (
          <FadeIn durationFrames={10}>
            <h1
              style={{
                color: foreground,
                fontSize: TYPE_SCALE.title - 4,
                fontWeight: 700,
                marginBottom: 28,
                textAlign: "center",
                fontFamily: FONTS.primary,
              }}
            >
              {title}
            </h1>
          </FadeIn>
        )}

        <SlideUp durationFrames={12} delay={4}>
          <div
            style={{
              backgroundColor: codeBgColor,
              border: `1px solid ${codeFrameColor}`,
              borderRadius: 16,
              padding: "36px 44px",
              maxWidth: 1500,
              width: "100%",
              boxShadow: `0 8px 32px rgba(0,0,0,0.3)`,
            }}
          >
            <div style={{ display: "flex", gap: 8, marginBottom: 20 }}>
              <div style={{ width: 12, height: 12, borderRadius: 6, backgroundColor: "#FF5F57" }} />
              <div style={{ width: 12, height: 12, borderRadius: 6, backgroundColor: "#FEBC2E" }} />
              <div style={{ width: 12, height: 12, borderRadius: 6, backgroundColor: "#28C840" }} />
            </div>

            <pre
              style={{
                fontFamily: FONTS.mono,
                fontSize: TYPE_SCALE.body,
                lineHeight: 1.6,
                color: foreground,
                margin: 0,
                whiteSpace: "pre-wrap",
                wordBreak: "break-all",
              }}
            >
              {visibleLines.map((line, i) => (
                <React.Fragment key={i}>
                  <span style={{ color: PALETTE.muted_dim, fontSize: TYPE_SCALE.caption, marginRight: 16 }}>
                    {String(i + 1).padStart(2, " ")}
                  </span>
                  {line}
                  {"\n"}
                </React.Fragment>
              ))}
            </pre>
          </div>
        </SlideUp>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
