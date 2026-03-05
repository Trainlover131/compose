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
import { FONTS, TEXT_STYLES, OPACITY } from "../design-system";

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
  const clamped = Math.min(maxDeg, 15);
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

// ═══════════════════════════════════════════════════════════════════
// HERO STACK — safe, overlap-free hero text + ghost layout
// ═══════════════════════════════════════════════════════════════════

export const HeroStack: React.FC<{
  label?: string;
  hero: React.ReactNode;
  ghost?: string;
  color?: string;
  accentColor?: string;
  anchor?: "left" | "center";
  heroFontSize?: number;
  ghostScale?: number;
  ghostOffsetX?: string;
  ghostOffsetY?: string;
}> = ({
  label,
  hero,
  ghost,
  color = "#FFFFFF",
  accentColor = "#4F8CFF",
  anchor = "left",
  heroFontSize = 120,
  ghostScale = 2.2,
  ghostOffsetX = "-4%",
  ghostOffsetY = "15%",
}) => {
  const isCenter = anchor === "center";
  return (
    <div
      style={{
        position: "relative",
        maxWidth: "92%",
        width: "100%",
        overflow: "hidden",
        display: "flex",
        flexDirection: "column",
        alignItems: isCenter ? "center" : "flex-start",
      }}
    >
      {/* Ghost — zIndex 0, blurred, low opacity, non-interactive */}
      {ghost && (
        <div
          style={{
            position: "absolute",
            left: ghostOffsetX,
            top: ghostOffsetY,
            zIndex: 0,
            pointerEvents: "none",
            fontFamily: FONTS.display,
            fontSize: heroFontSize * ghostScale,
            fontWeight: 700,
            lineHeight: 0.85,
            color,
            opacity: OPACITY.ghost,
            filter: "blur(2px)",
            whiteSpace: "nowrap",
            userSelect: "none",
          }}
        >
          {ghost}
        </div>
      )}

      {/* Label badge — zIndex 3 */}
      {label && (
        <div
          style={{
            position: "relative",
            zIndex: 3,
            ...TEXT_STYLES.label,
            color,
            marginBottom: 16,
          }}
        >
          {label}
        </div>
      )}

      {/* Main hero — zIndex 2 */}
      <div
        style={{
          position: "relative",
          zIndex: 2,
          ...TEXT_STYLES.heroNumber,
          fontSize: heroFontSize,
          color,
          textAlign: isCenter ? "center" : "left",
        }}
      >
        {hero}
      </div>
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// PRO OVERLAYS — layered on top of every scene for production feel
// ═══════════════════════════════════════════════════════════════════

export const FilmGrain: React.FC<{
  opacity?: number;
}> = ({ opacity = 0.04 }) => {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        opacity,
        backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)' opacity='1'/%3E%3C/svg%3E")`,
        backgroundRepeat: "repeat",
        backgroundSize: "256px 256px",
        mixBlendMode: "overlay",
      }}
    />
  );
};

export const Vignette: React.FC<{
  intensity?: number;
}> = ({ intensity = 0.55 }) => {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        background: `radial-gradient(ellipse 80% 80% at 50% 50%, transparent 50%, rgba(0,0,0,${intensity}) 100%)`,
      }}
    />
  );
};

export const AmbientGlow: React.FC<{
  color?: string;
  size?: number;
  x?: string;
  y?: string;
  opacity?: number;
}> = ({ color = "#4F8CFF", size = 500, x = "50%", y = "50%", opacity = 0.1 }) => {
  return (
    <div
      style={{
        position: "absolute",
        left: x,
        top: y,
        transform: "translate(-50%, -50%)",
        width: size,
        height: size,
        borderRadius: "50%",
        background: color,
        filter: `blur(${Math.round(size * 0.6)}px)`,
        opacity,
        pointerEvents: "none",
      }}
    />
  );
};

export const GridOverlay: React.FC<{
  columns?: number;
  color?: string;
  opacity?: number;
}> = ({ columns = 8, color = "#FFFFFF", opacity = 0.03 }) => {
  const cols = [];
  for (let i = 1; i < columns; i++) {
    const pct = (i / columns) * 100;
    cols.push(
      <div
        key={i}
        style={{
          position: "absolute",
          left: `${pct}%`,
          top: 0,
          bottom: 0,
          width: 1,
          backgroundColor: color,
          opacity,
        }}
      />
    );
  }
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        mixBlendMode: "overlay",
      }}
    >
      {cols}
    </div>
  );
};

export const FogOverlay: React.FC<{
  color?: string;
  x?: string;
  y?: string;
  opacity?: number;
}> = ({ color = "#4F8CFF", x = "70%", y = "75%", opacity = 0.06 }) => {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        background: `radial-gradient(ellipse 60% 50% at ${x} ${y}, ${color} 0%, transparent 70%)`,
        opacity,
        mixBlendMode: "screen",
      }}
    />
  );
};

// Layer order: bg → grid → glow → fog → content → grain → vignette
export const ProSceneWrapper: React.FC<{
  children: React.ReactNode;
  bg?: "dark" | "light" | "subtle_gradient";
  accentColor?: string;
  bgStyle?: React.CSSProperties;
}> = ({ children, bg = "dark", accentColor = "#4F8CFF", bgStyle }) => {
  const isDark = bg !== "light";
  return (
    <div style={{ position: "absolute", inset: 0, ...bgStyle }}>
      {isDark && <GridOverlay columns={8} opacity={0.03} />}
      {isDark && <AmbientGlow color={accentColor} size={600} x="35%" y="40%" opacity={0.1} />}
      {isDark && <FogOverlay color={accentColor} x="70%" y="75%" opacity={0.06} />}
      <div style={{ position: "relative", zIndex: 1, width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
        {children}
      </div>
      {isDark && <FilmGrain opacity={0.035} />}
      {isDark && <Vignette intensity={0.5} />}
    </div>
  );
};
