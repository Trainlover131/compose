import React from "react";
import { AbsoluteFill } from "remotion";
import { FadeIn, SlideUp, ScaleSpring, CountUpNumber, DrawLine, HeroStack, ProSceneWrapper } from "../components/AnimationPrimitives";
import { FONTS, PALETTE, proBgStyle, fgColor, TYPE_SCALE } from "../design-system";

export interface KpiCounterProps {
  label: string;
  value: number;
  prefix?: string;
  suffix?: string;
  accentColor?: string;
  bg?: "dark" | "light";
}

export const KpiCounter: React.FC<KpiCounterProps> = ({
  label,
  value,
  prefix = "",
  suffix = "",
  accentColor = PALETTE.default_accent,
  bg = "dark",
}) => {
  const foreground = fgColor(bg);
  const bgStyle = proBgStyle(bg, accentColor);

  // Format value for ghost display
  const ghostText = prefix + value.toLocaleString() + suffix;

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={bg} accentColor={accentColor} bgStyle={bgStyle}>
        {/* Phase 4: staged reveal — bg visible 0-5, hero 5-18, details 18-36 */}
        <ScaleSpring delay={5}>
          <HeroStack
            label={label}
            hero={
              <CountUpNumber
                value={value}
                prefix={prefix}
                suffix={suffix}
                durationFrames={40}
                delay={6}
                style={{
                  color: foreground,
                  fontSize: TYPE_SCALE.hero,
                  fontWeight: 700,
                  letterSpacing: -3,
                  fontFamily: FONTS.display,
                }}
              />
            }
            ghost={ghostText}
            color={foreground}
            accentColor={accentColor}
            anchor="left"
          />
        </ScaleSpring>

        <FadeIn durationFrames={12} delay={18}>
          <DrawLine
            color={accentColor}
            width={140}
            thickness={4}
            durationFrames={18}
            delay={20}
          />
        </FadeIn>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
