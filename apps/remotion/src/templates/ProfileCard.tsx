import React from "react";
import { AbsoluteFill, useCurrentFrame, interpolate } from "remotion";
import { FadeIn, SlideUp, ScaleSpring, DrawLine, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE, OPACITY, TEXT_STYLES } from "../design-system";

export interface ProfileCardProps {
  name: string;
  title?: string;
  bullets?: string[];
  accentColor?: string;
  bg?: "dark" | "light";
}

export const ProfileCard: React.FC<ProfileCardProps> = ({
  name,
  title: role,
  bullets = [],
  accentColor = PALETTE.default_accent,
  bg = "dark",
}) => {
  const foreground = fgColor(bg);
  const bgStyle = proBgStyle(bg, accentColor);
  const frame = useCurrentFrame();

  const initials = name.split(" ").map(w => w.charAt(0)).join("").toUpperCase();
  const ghostOp = interpolate(frame, [3, 12], [0, OPACITY.ghost], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        {/* Ghost initials behind */}
        <div
          style={{
            position: "absolute",
            top: "50%",
            left: "50%",
            transform: "translate(-50%, -55%)",
            fontSize: 220,
            fontFamily: FONTS.display,
            fontWeight: 800,
            color: PALETTE.white,
            opacity: ghostOp,
            filter: "blur(2px)",
            pointerEvents: "none",
            lineHeight: 1,
          }}
        >
          {initials}
        </div>

        {/* Content — centered for portrait */}
        <div style={{ padding: "0 60px", width: "100%", textAlign: "center", position: "relative", zIndex: 1 }}>
          <div style={{ display: "flex", justifyContent: "center" }}>
            <ScaleSpring delay={3}>
              <div
                style={{
                  width: 80,
                  height: 80,
                  borderRadius: 40,
                  backgroundColor: accentColor,
                  display: "flex",
                  alignItems: "center",
                  justifyContent: "center",
                  marginBottom: 20,
                  boxShadow: `0 0 40px ${accentColor}33`,
                }}
              >
                <span style={{ color: "#FFFFFF", fontSize: 32, fontWeight: 700, fontFamily: FONTS.display }}>
                  {name.charAt(0).toUpperCase()}
                </span>
              </div>
            </ScaleSpring>
          </div>

          <SlideUp durationFrames={12} delay={7} distance={18}>
            <h1
              style={{
                color: foreground,
                fontSize: TYPE_SCALE.title + 4,
                fontWeight: 700,
                fontFamily: FONTS.display,
              }}
            >
              {name}
            </h1>
          </SlideUp>

          {role && (
            <FadeIn durationFrames={10} delay={12}>
              <p style={{ color: PALETTE.muted, fontSize: TYPE_SCALE.body, fontWeight: 500, marginTop: 4, fontFamily: FONTS.ui }}>
                {role}
              </p>
            </FadeIn>
          )}

          <FadeIn durationFrames={8} delay={15}>
            <div style={{ marginTop: 14, display: "flex", justifyContent: "center" }}>
              <DrawLine color={accentColor} width={50} thickness={3} durationFrames={10} delay={17} />
            </div>
          </FadeIn>

          {bullets.length > 0 && (
            <div style={{ marginTop: 22, display: "flex", flexDirection: "column", gap: 10, alignItems: "center" }}>
              {bullets.slice(0, 4).map((b, i) => (
                <FadeIn key={i} durationFrames={8} delay={20 + i * 3}>
                  <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
                    <div style={{ width: 5, height: 5, borderRadius: 3, backgroundColor: accentColor, flexShrink: 0 }} />
                    <p style={{ color: foreground, fontSize: TYPE_SCALE.body - 2, fontWeight: 400, fontFamily: FONTS.ui }}>
                      {b}
                    </p>
                  </div>
                </FadeIn>
              ))}
            </div>
          )}
        </div>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
