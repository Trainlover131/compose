/**
 * Reusable animation primitives from the SUPACUT design system.
 * These are the ONLY motion effects allowed. Any custom scene must
 * compile down to compositions of these primitives.
 */
import React from "react";
import {
  useCurrentFrame,
  useVideoConfig,
  interpolate,
  spring,
  Easing,
} from "remotion";

// ── FadeIn ──────────────────────────────────────────────────────────
export const FadeIn: React.FC<{
  children: React.ReactNode;
  durationFrames?: number;
  delay?: number;
}> = ({ children, durationFrames = 15, delay = 0 }) => {
  const frame = useCurrentFrame();
  const opacity = interpolate(frame - delay, [0, durationFrames], [0, 1], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return <div style={{ opacity }}>{children}</div>;
};

// ── SlideUp ─────────────────────────────────────────────────────────
export const SlideUp: React.FC<{
  children: React.ReactNode;
  durationFrames?: number;
  delay?: number;
  distance?: number;
}> = ({ children, durationFrames = 20, delay = 0, distance = 40 }) => {
  const frame = useCurrentFrame();
  const progress = interpolate(
    frame - delay,
    [0, durationFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
  );
  return (
    <div
      style={{
        opacity: progress,
        transform: `translateY(${(1 - progress) * distance}px)`,
      }}
    >
      {children}
    </div>
  );
};

// ── SlideLeft ────────────────────────────────────────────────────────
export const SlideLeft: React.FC<{
  children: React.ReactNode;
  durationFrames?: number;
  delay?: number;
  distance?: number;
}> = ({ children, durationFrames = 20, delay = 0, distance = 60 }) => {
  const frame = useCurrentFrame();
  const progress = interpolate(
    frame - delay,
    [0, durationFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
  );
  return (
    <div
      style={{
        opacity: progress,
        transform: `translateX(${(1 - progress) * distance}px)`,
      }}
    >
      {children}
    </div>
  );
};

// ── ScaleSpring ─────────────────────────────────────────────────────
export const ScaleSpring: React.FC<{
  children: React.ReactNode;
  delay?: number;
}> = ({ children, delay = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();
  const scale = spring({
    frame: frame - delay,
    fps,
    config: { damping: 12, stiffness: 150, mass: 0.8 },
  });
  return (
    <div
      style={{
        transform: `scale(${scale})`,
        opacity: interpolate(scale, [0, 0.5], [0, 1], {
          extrapolateRight: "clamp",
        }),
      }}
    >
      {children}
    </div>
  );
};

// ── CountUpNumber ───────────────────────────────────────────────────
export const CountUpNumber: React.FC<{
  value: number;
  prefix?: string;
  suffix?: string;
  durationFrames?: number;
  delay?: number;
  style?: React.CSSProperties;
}> = ({ value, prefix = "", suffix = "", durationFrames = 45, delay = 0, style }) => {
  const frame = useCurrentFrame();
  const progress = interpolate(
    frame - delay,
    [0, durationFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
  );
  const current = Math.round(value * progress);
  const formatted = current.toLocaleString();
  return (
    <span style={style}>
      {prefix}
      {formatted}
      {suffix}
    </span>
  );
};

// ── DrawLine (horizontal rule / underline) ──────────────────────────
export const DrawLine: React.FC<{
  color?: string;
  width?: number;
  thickness?: number;
  durationFrames?: number;
  delay?: number;
}> = ({
  color = "#4F8CFF",
  width = 120,
  thickness = 3,
  durationFrames = 20,
  delay = 0,
}) => {
  const frame = useCurrentFrame();
  const progress = interpolate(
    frame - delay,
    [0, durationFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
  );
  return (
    <div
      style={{
        width: width * progress,
        height: thickness,
        backgroundColor: color,
        borderRadius: thickness / 2,
      }}
    />
  );
};

// ── MaskReveal ──────────────────────────────────────────────────────
export const MaskReveal: React.FC<{
  children: React.ReactNode;
  durationFrames?: number;
  delay?: number;
  direction?: "left" | "right" | "up" | "down";
}> = ({ children, durationFrames = 20, delay = 0, direction = "left" }) => {
  const frame = useCurrentFrame();
  const progress = interpolate(
    frame - delay,
    [0, durationFrames],
    [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
  );

  const clipMap = {
    left: `inset(0 ${(1 - progress) * 100}% 0 0)`,
    right: `inset(0 0 0 ${(1 - progress) * 100}%)`,
    up: `inset(0 0 ${(1 - progress) * 100}% 0)`,
    down: `inset(${(1 - progress) * 100}% 0 0 0)`,
  };

  return (
    <div style={{ clipPath: clipMap[direction] }}>
      {children}
    </div>
  );
};

// ── HighlightSweep ──────────────────────────────────────────────────
export const HighlightSweep: React.FC<{
  children: React.ReactNode;
  color?: string;
  durationFrames?: number;
  delay?: number;
}> = ({ children, color = "#4F8CFF33", durationFrames = 20, delay = 0 }) => {
  const frame = useCurrentFrame();
  const progress = interpolate(
    frame - delay,
    [0, durationFrames],
    [0, 100],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" }
  );
  return (
    <span
      style={{
        backgroundImage: `linear-gradient(90deg, ${color} ${progress}%, transparent ${progress}%)`,
        padding: "4px 8px",
      }}
    >
      {children}
    </span>
  );
};

// ── SoftZoom ────────────────────────────────────────────────────────
export const SoftZoom: React.FC<{
  children: React.ReactNode;
  from?: number;
  to?: number;
  durationFrames?: number;
  delay?: number;
}> = ({ children, from = 1.0, to = 1.03, durationFrames, delay = 0 }) => {
  const frame = useCurrentFrame();
  const { durationInFrames } = useVideoConfig();
  const dur = durationFrames ?? durationInFrames;
  const scale = interpolate(frame - delay, [0, dur], [from, to], {
    extrapolateLeft: "clamp",
    extrapolateRight: "clamp",
  });
  return (
    <div style={{ transform: `scale(${scale})` }}>{children}</div>
  );
};

// ── SubtleRotate3D (max 15°) ────────────────────────────────────────
export const SubtleRotate3D: React.FC<{
  children: React.ReactNode;
  maxDeg?: number;
  durationFrames?: number;
  delay?: number;
}> = ({ children, maxDeg = 8, durationFrames = 30, delay = 0 }) => {
  const frame = useCurrentFrame();
  const clamped = Math.min(maxDeg, 15); // hard cap at 15°
  const angle = interpolate(
    frame - delay,
    [0, durationFrames],
    [clamped, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) }
  );
  return (
    <div
      style={{
        transform: `perspective(800px) rotateY(${angle}deg)`,
      }}
    >
      {children}
    </div>
  );
};
