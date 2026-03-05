/**
 * SUPACUT REMOTION DESIGN SYSTEM (v3) — "Swishy Display Stack"
 *
 * Production-quality motion graphics. Dark gradient backgrounds with
 * asymmetric accent glow, vertical grid, fog overlay, film grain, vignette.
 * Display-stack typography: Inter for both display + UI, SF Mono for code only.
 * Serif is editorial-only and never the default.
 */

import type React from "react";

// ── Typography ──────────────────────────────────────────────────────
export const FONTS = {
  display: "Inter",
  ui: "Inter",
  mono: "SF Mono, SFMono-Regular, ui-monospace, Menlo, monospace",
  serifEditorialOnly: "Georgia, serif",
} as const;

export const MAX_FONT_FAMILIES_PER_SCENE = 2;

// ── Tracking + Opacity tokens ───────────────────────────────────────
export const TRACKING = {
  label: 0.22,
  number: -0.02,
} as const;

export const OPACITY = {
  label: 0.55,
  grid: 0.10,
  ghost: 0.12,
} as const;

// ── Text styles (reusable across all templates) ─────────────────────
export const TEXT_STYLES = {
  label: {
    fontFamily: FONTS.ui,
    letterSpacing: `${TRACKING.label}em`,
    textTransform: "uppercase" as const,
    opacity: OPACITY.label,
  },
  heroNumber: {
    fontFamily: FONTS.display,
    fontWeight: 800,
    letterSpacing: `${TRACKING.number}em`,
  },
} as const;

// ── Type scale (for consistent hierarchy) ───────────────────────────
export const TYPE_SCALE = {
  hero: 128,       // primary number / headline
  title: 52,       // section title
  subtitle: 36,    // label, subtitle
  body: 28,        // body text, bullets
  caption: 22,     // muted captions, axis labels
  micro: 16,       // fine print
} as const;

// ── Colors ──────────────────────────────────────────────────────────
export const PALETTE = {
  dark_bg: "#0A0A0A",
  dark_bg_elevated: "#111114",
  dark_surface: "#1A1A2E",
  light_bg: "#FAFAFA",
  white: "#FFFFFF",
  black: "#000000",
  muted: "#888888",
  muted_dim: "#555555",
  default_accent: "#4F8CFF",
} as const;

export function bgColor(bg: "dark" | "light" | "subtle_gradient"): string {
  if (bg === "light") return PALETTE.light_bg;
  return PALETTE.dark_bg;
}

export function fgColor(bg: "dark" | "light" | "subtle_gradient"): string {
  if (bg === "light") return PALETTE.black;
  return PALETTE.white;
}

export function mutedColor(bg: "dark" | "light" | "subtle_gradient"): string {
  return PALETTE.muted;
}

// ── Pro background styles ───────────────────────────────────────────
export function proBgStyle(
  bg: "dark" | "light" | "subtle_gradient",
  accentColor: string = PALETTE.default_accent,
): React.CSSProperties {
  if (bg === "light") {
    return { backgroundColor: PALETTE.light_bg };
  }
  const glowColor = accentColor + "18";
  return {
    background: `radial-gradient(ellipse 70% 50% at 50% 50%, ${glowColor} 0%, ${PALETTE.dark_bg} 100%)`,
    backgroundColor: PALETTE.dark_bg,
  };
}

// ── Rendering defaults ──────────────────────────────────────────────
// Portrait 9:16 to match final short-form video output (1080x1920).
// The FFmpeg pipeline scales Remotion output to 1080x1920; rendering
// natively at that size avoids any lossy center-crop.
export const DEFAULT_WIDTH = 1080;
export const DEFAULT_HEIGHT = 1920;
export const DEFAULT_FPS = 30;

// ── Budget caps ─────────────────────────────────────────────────────
export const BUDGET = {
  max_inserts_per_video: 3,
  max_insert_duration_sec: 6,
  max_total_remotion_time_sec: 18,
  max_elements_per_scene: 12,
  max_simultaneous_animations: 3,
  max_font_families_per_scene: 2,
  forbid_heavy_3d: true,
  forbid_glitch_overload: true,
} as const;

// ── Allowed motion primitives ───────────────────────────────────────
export const ALLOWED_PRIMITIVES = [
  "FadeIn",
  "SlideUp",
  "SlideLeft",
  "ScaleSpring",
  "CountUpNumber",
  "DrawLine",
  "MaskReveal",
  "HighlightSweep",
  "BackgroundInterpolate",
  "SoftZoom",
  "SubtleRotate3D",
] as const;

export type MotionPrimitive = (typeof ALLOWED_PRIMITIVES)[number];
