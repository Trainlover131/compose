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

  // Ghost initials
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
            fontSize: 280,
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

        {/* Content — left aligned */}
        <div style={{ padding: "0 140px", width: "100%", alignSelf: "flex-start", marginTop: 200, position: "relative", zIndex: 1 }}>
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
                marginBottom: 24,
                boxShadow: `0 0 40px ${accentColor}33`,
              }}
            >
              <span style={{ color: "#FFFFFF", fontSize: 34, fontWeight: 700, fontFamily: FONTS.display }}>
                {name.charAt(0).toUpperCase()}
              </span>
            </div>
          </ScaleSpring>

          <SlideUp durationFrames={12} delay={7} distance={18}>
            <h1
              style={{
                color: foreground,
                fontSize: TYPE_SCALE.title + 8,
                fontWeight: 700,
                fontFamily: FONTS.display,
              }}
            >
              {name}
            </h1>
          </SlideUp>

          {role && (
            <FadeIn durationFrames={10} delay={12}>
              <p
                style={{
                  color: PALETTE.muted,
                  fontSize: TYPE_SCALE.body + 2,
                  fontWeight: 500,
                  marginTop: 4,
                  fontFamily: FONTS.ui,
                }}
              >
                {role}
              </p>
            </FadeIn>
          )}

          <FadeIn durationFrames={8} delay={15}>
            <div style={{ marginTop: 16 }}>
              <DrawLine
                color={accentColor}
                width={60}
                thickness={3}
                durationFrames={10}
                delay={17}
              />
            </div>
          </FadeIn>

          {bullets.length > 0 && (
            <div style={{ marginTop: 24, display: "flex", flexDirection: "column", gap: 10 }}>
              {bullets.slice(0, 4).map((b, i) => (
                <FadeIn key={i} durationFrames={8} delay={20 + i * 3}>
                  <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
                    <div
                      style={{
                        width: 6,
                        height: 6,
                        borderRadius: 3,
                        backgroundColor: accentColor,
                        flexShrink: 0,
                      }}
                    />
                    <p
                      style={{
                        color: foreground,
                        fontSize: TYPE_SCALE.body,
                        fontWeight: 400,
                        fontFamily: FONTS.ui,
                      }}
                    >
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
