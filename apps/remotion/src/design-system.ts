/**
 * SUPACUT REMOTION DESIGN SYSTEM (v2 — portrait-native)
 *
 * All templates render natively at 1080x1920 (9:16 portrait).
 * Typography: Inter primary, Space Grotesk display, SF Mono for code.
 * Serif is NEVER a default — only used if explicitly requested.
 */

import type React from "react";
import { interFamily, spaceGroteskFamily } from "./fonts";

// ── Sans fallback stack (never serif) ────────────────────────────────
const SANS_FALLBACK = ", system-ui, -apple-system, Segoe UI, Roboto, Arial, sans-serif";

// ── Typography ──────────────────────────────────────────────────────
export const FONTS = {
  /** UI / body text — Inter loaded via @remotion/google-fonts */
  ui: interFamily + SANS_FALLBACK,
  /** Display / headline — Space Grotesk */
  display: spaceGroteskFamily + SANS_FALLBACK,
  /** Code — system monospace stack */
  mono: "SF Mono, SFMono-Regular, ui-monospace, Menlo, monospace",
  /** Legacy alias — resolves to Inter (sans). Never serif by default. */
  primary: interFamily + SANS_FALLBACK,
  /** Serif — ONLY for explicit opt-in (e.g. QuoteHighlight serif=true) */
  serif: "Georgia, serif",
} as const;

export const MAX_FONT_FAMILIES_PER_SCENE = 2;

// ── Type scale (portrait-optimized) ─────────────────────────────────
export const TYPE_SCALE = {
  hero: 120,       // primary number / headline (fits 1080 width)
  title: 48,       // section title
  subtitle: 32,    // label, subtitle
  body: 26,        // body text, bullets
  caption: 20,     // muted captions, axis labels
  micro: 14,       // fine print
} as const;

// ── Tracking (letter-spacing tokens) ────────────────────────────────
export const TRACKING = {
  label: "0.14em",
  number: "-0.03em",
} as const;

// ── Opacity tokens ──────────────────────────────────────────────────
export const OPACITY = {
  label: 0.6,
  ghost: 0.07,
} as const;

// ── Reusable text style objects ─────────────────────────────────────
export const TEXT_STYLES = {
  label: {
    fontFamily: FONTS.ui,
    fontSize: TYPE_SCALE.subtitle,
    fontWeight: 600,
    letterSpacing: TRACKING.label,
    textTransform: "uppercase" as const,
    opacity: OPACITY.label,
    lineHeight: 1.2,
  } satisfies React.CSSProperties,
  heroNumber: {
    fontFamily: FONTS.display,
    fontSize: TYPE_SCALE.hero,
    fontWeight: 700,
    letterSpacing: TRACKING.number,
    lineHeight: 0.95,
  } satisfies React.CSSProperties,
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

// ── Pro background style ────────────────────────────────────────────
export function proBgStyle(
  bg: "dark" | "light" | "subtle_gradient",
  accentColor: string = PALETTE.default_accent,
): React.CSSProperties {
  if (bg === "light") {
    return { backgroundColor: PALETTE.light_bg };
  }
  const glowColor = accentColor + "18";
  return {
    background: `radial-gradient(ellipse 80% 40% at 50% 45%, ${glowColor} 0%, ${PALETTE.dark_bg} 100%)`,
    backgroundColor: PALETTE.dark_bg,
  };
}

// ── Rendering defaults (PORTRAIT: 1080x1920) ────────────────────────
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
