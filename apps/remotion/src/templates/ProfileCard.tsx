import React from "react";
import { AbsoluteFill } from "remotion";
import { FadeIn, SlideUp, ScaleSpring, DrawLine } from "../components/AnimationPrimitives";
import { FONTS, bgColor, fgColor, PALETTE } from "../design-system";

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
  const background = bgColor(bg);
  const foreground = fgColor(bg);

  return (
    <AbsoluteFill
      style={{
        backgroundColor: background,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        fontFamily: FONTS.primary,
      }}
    >
      {/* Avatar placeholder circle */}
      <ScaleSpring delay={0}>
        <div
          style={{
            width: 120,
            height: 120,
            borderRadius: 60,
            backgroundColor: accentColor,
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            marginBottom: 28,
          }}
        >
          <span style={{ color: "#FFFFFF", fontSize: 48, fontWeight: 700 }}>
            {name.charAt(0).toUpperCase()}
          </span>
        </div>
      </ScaleSpring>

      <SlideUp durationFrames={18} delay={8} distance={25}>
        <h1
          style={{
            color: foreground,
            fontSize: 56,
            fontWeight: 700,
            textAlign: "center",
          }}
        >
          {name}
        </h1>
      </SlideUp>

      {role && (
        <FadeIn durationFrames={12} delay={14}>
          <p
            style={{
              color: PALETTE.muted,
              fontSize: 30,
              fontWeight: 500,
              marginTop: 8,
              textAlign: "center",
            }}
          >
            {role}
          </p>
        </FadeIn>
      )}

      <FadeIn durationFrames={12} delay={18}>
        <DrawLine
          color={accentColor}
          width={80}
          thickness={3}
          durationFrames={15}
          delay={20}
        />
      </FadeIn>

      {bullets.length > 0 && (
        <div style={{ marginTop: 32, display: "flex", flexDirection: "column", gap: 12 }}>
          {bullets.slice(0, 4).map((b, i) => (
            <FadeIn key={i} durationFrames={12} delay={24 + i * 6}>
              <div style={{ display: "flex", alignItems: "center", gap: 16 }}>
                <div
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: 4,
                    backgroundColor: accentColor,
                    flexShrink: 0,
                  }}
                />
                <p
                  style={{
                    color: foreground,
                    fontSize: 28,
                    fontWeight: 400,
                  }}
                >
                  {b}
                </p>
              </div>
            </FadeIn>
          ))}
        </div>
      )}
    </AbsoluteFill>
  );
};
