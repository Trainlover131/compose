/**
 * Reusable animation primitives from the SUPACUT design system (v3).
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
import { FONTS, PALETTE, OPACITY, TEXT_STYLES, TYPE_SCALE, TRACKING } from "../design-system";

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
// SWISHY DISPLAY STACK — background depth + overlays + layout prims
// ═══════════════════════════════════════════════════════════════════

// ── GridOverlay (vertical lines for Swishy grid feel) ───────────────
export const GridOverlay: React.FC<{ opacity?: number }> = ({ opacity = 0.10 }) => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      pointerEvents: "none",
      opacity,
      backgroundImage: `linear-gradient(to right, rgba(255,255,255,0.10) 1px, transparent 1px)`,
      backgroundSize: "108px 100%",
      mixBlendMode: "overlay",
    }}
  />
);

// ── FilmGrain (SVG noise overlay for texture) ───────────────────────
export const FilmGrain: React.FC<{
  opacity?: number;
}> = ({ opacity = 0.04 }) => (
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

// ── Vignette (edge darkening for focus) ─────────────────────────────
export const Vignette: React.FC<{
  intensity?: number;
}> = ({ intensity = 0.55 }) => (
  <div
    style={{
      position: "absolute",
      inset: 0,
      pointerEvents: "none",
      background: `radial-gradient(ellipse 80% 80% at 50% 50%, transparent 50%, rgba(0,0,0,${intensity}) 100%)`,
    }}
  />
);

// ── AmbientGlow (positionable soft colored glow) ────────────────────
export const AmbientGlow: React.FC<{
  color?: string;
  size?: number;
  x?: string;
  y?: string;
  opacity?: number;
}> = ({ color = "#FF4444", size = 700, x = "70%", y = "70%", opacity: op = 0.14 }) => (
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
      filter: `blur(${Math.round(size * 0.55)}px)`,
      opacity: op,
      pointerEvents: "none",
    }}
  />
);

// ── FogOverlay (radial screen-blend fog) ────────────────────────────
export const FogOverlay: React.FC<{
  color?: string;
  opacity?: number;
}> = ({ color = "#FF4444", opacity: op = 0.22 }) => {
  const hex = Math.round(op * 255).toString(16).padStart(2, "0");
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        background: `radial-gradient(ellipse 80% 55% at 70% 75%, ${color}${hex} 0%, transparent 60%)`,
        mixBlendMode: "screen",
      }}
    />
  );
};

// ── ProSceneWrapper (full Swishy depth stack) ───────────────────────
export const ProSceneWrapper: React.FC<{
  children: React.ReactNode;
  bg?: "dark" | "light" | "subtle_gradient";
  accentColor?: string;
  bgStyle?: React.CSSProperties;
}> = ({ children, bg = "dark", accentColor = "#4F8CFF", bgStyle }) => {
  const isDark = bg !== "light";
  return (
    <div style={{ position: "absolute", inset: 0, ...bgStyle }}>
      {/* Layer 1: Grid */}
      {isDark && <GridOverlay opacity={OPACITY.grid} />}
      {/* Layer 2: Asymmetric ambient glow (bottom-right) */}
      {isDark && <AmbientGlow color={accentColor} size={600} x="60%" y="70%" opacity={0.16} />}
      {/* Layer 3: Fog overlay */}
      {isDark && <FogOverlay color={accentColor} opacity={0.20} />}
      {/* Layer 4: Main content */}
      <div style={{ position: "relative", zIndex: 1, width: "100%", height: "100%", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center" }}>
        {children}
      </div>
      {/* Layer 5: Film grain */}
      {isDark && <FilmGrain opacity={0.03} />}
      {/* Layer 6: Vignette */}
      {isDark && <Vignette intensity={0.5} />}
    </div>
  );
};

// ═══════════════════════════════════════════════════════════════════
// SWISHY LAYOUT PRIMITIVES
// ═══════════════════════════════════════════════════════════════════

// ── HeroStack (label + hero value + ghost value behind) ─────────────
export const HeroStack: React.FC<{
  label: string;
  value: string;
  accentColor?: string;
  ghostValue?: string;
  align?: "left" | "center";
  top?: number;
}> = ({ label, value, accentColor = PALETTE.default_accent, ghostValue, align = "left", top = 0 }) => {
  const frame = useCurrentFrame();
  const { fps } = useVideoConfig();

  // Label fades in frames 5-12
  const labelOp = interpolate(frame, [5, 12], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });

  // Hero springs in frames 5-18
  const heroScale = spring({
    frame: Math.max(0, frame - 5),
    fps,
    config: { damping: 14, stiffness: 120, mass: 0.9 },
  });

  const ghost = ghostValue ?? value;
  const textAlign = align === "center" ? ("center" as const) : ("left" as const);
  const alignItems = align === "center" ? "center" : "flex-start";

  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        alignItems,
        position: "relative",
        paddingTop: top,
      }}
    >
      {/* Label */}
      <div
        style={{
          ...TEXT_STYLES.label,
          fontSize: TYPE_SCALE.subtitle,
          color: PALETTE.white,
          marginBottom: 8,
          opacity: labelOp * OPACITY.label,
          textAlign,
        }}
      >
        {label}
      </div>

      {/* Ghost value behind */}
      <div
        style={{
          position: "absolute",
          top: top + TYPE_SCALE.subtitle + 8 - 20,
          left: align === "center" ? "50%" : 0,
          transform: align === "center" ? "translateX(-50%)" : "none",
          ...TEXT_STYLES.heroNumber,
          fontSize: TYPE_SCALE.hero + 20,
          color: PALETTE.white,
          opacity: OPACITY.ghost,
          filter: "blur(2px)",
          pointerEvents: "none",
          whiteSpace: "nowrap",
          textAlign,
        }}
      >
        {ghost}
      </div>

      {/* Hero value */}
      <div
        style={{
          ...TEXT_STYLES.heroNumber,
          fontSize: TYPE_SCALE.hero,
          color: PALETTE.white,
          transform: `scale(${heroScale})`,
          opacity: interpolate(heroScale, [0, 0.5], [0, 1], { extrapolateRight: "clamp" }),
          position: "relative",
          zIndex: 1,
          whiteSpace: "nowrap",
          textAlign,
        }}
      >
        {value}
      </div>
    </div>
  );
};

// ── CornerBadge (small rounded pill, top-right) ─────────────────────
export const CornerBadge: React.FC<{
  label: string;
  value: string;
}> = ({ label, value }) => {
  const frame = useCurrentFrame();
  const op = interpolate(frame, [18, 28], [0, 1], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
  });
  const slide = interpolate(frame, [18, 28], [12, 0], {
    extrapolateLeft: "clamp", extrapolateRight: "clamp",
    easing: Easing.out(Easing.cubic),
  });

  return (
    <div
      style={{
        position: "absolute",
        top: 40,
        right: 36,
        zIndex: 2,
        opacity: op,
        transform: `translateY(${slide}px)`,
        display: "flex",
        alignItems: "center",
        gap: 10,
        backgroundColor: "rgba(255,255,255,0.08)",
        border: "1px solid rgba(255,255,255,0.12)",
        borderRadius: 16,
        padding: "10px 18px",
      }}
    >
      <span
        style={{
          ...TEXT_STYLES.label,
          fontSize: TYPE_SCALE.micro,
          color: PALETTE.white,
          opacity: 0.6,
        }}
      >
        {label}
      </span>
      <span
        style={{
          fontFamily: FONTS.display,
          fontWeight: 700,
          fontSize: TYPE_SCALE.caption,
          color: PALETTE.white,
        }}
      >
        {value}
      </span>
    </div>
  );
};
