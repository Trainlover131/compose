import React from "react";
import { AbsoluteFill } from "remotion";
import { FadeIn, SlideUp, ScaleSpring, DrawLine, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE } from "../design-system";

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

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        <ScaleSpring delay={0}>
          <div
            style={{
              width: 110,
              height: 110,
              borderRadius: 55,
              backgroundColor: accentColor,
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
              marginBottom: 24,
              boxShadow: `0 0 40px ${accentColor}33`,
            }}
          >
            <span style={{ color: "#FFFFFF", fontSize: 44, fontWeight: 700, fontFamily: FONTS.primary }}>
              {name.charAt(0).toUpperCase()}
            </span>
          </div>
        </ScaleSpring>

        <SlideUp durationFrames={14} delay={6} distance={20}>
          <h1
            style={{
              color: foreground,
              fontSize: TYPE_SCALE.title + 4,
              fontWeight: 700,
              textAlign: "center",
              fontFamily: FONTS.primary,
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
                marginTop: 6,
                textAlign: "center",
                fontFamily: FONTS.primary,
              }}
            >
              {role}
            </p>
          </FadeIn>
        )}

        <FadeIn durationFrames={10} delay={14}>
          <DrawLine
            color={accentColor}
            width={70}
            thickness={3}
            durationFrames={12}
            delay={16}
          />
        </FadeIn>

        {bullets.length > 0 && (
          <div style={{ marginTop: 28, display: "flex", flexDirection: "column", gap: 10 }}>
            {bullets.slice(0, 4).map((b, i) => (
              <FadeIn key={i} durationFrames={10} delay={18 + i * 4}>
                <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
                  <div
                    style={{
                      width: 7,
                      height: 7,
                      borderRadius: 4,
                      backgroundColor: accentColor,
                      flexShrink: 0,
                    }}
                  />
                  <p
                    style={{
                      color: foreground,
                      fontSize: TYPE_SCALE.body,
                      fontWeight: 400,
                      fontFamily: FONTS.primary,
                    }}
                  >
                    {b}
                  </p>
                </div>
              </FadeIn>
            ))}
          </div>
        )}
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
