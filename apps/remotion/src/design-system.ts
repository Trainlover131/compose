/**
 * SUPACUT REMOTION DESIGN SYSTEM (v2)
 *
 * Production-quality motion graphics. Polished, cinematic feel inspired by
 * Swishy.AI-style design: dark gradient backgrounds with radial accent glow,
 * subtle film grain, vignette, generous whitespace, spring-physics animations,
 * and sharp typographic hierarchy.
 *
 * Typography: Inter primary, SF Mono for code only, serif only for editorial.
 * Limit to 1 accent color per scene, restrained backgrounds.
 */

// ── Typography ──────────────────────────────────────────────────────
export const FONTS = {
  primary: "Inter",
  mono: "SF Mono, SFMono-Regular, ui-monospace, Menlo, monospace",
  serif: "Georgia, serif",
} as const;

export const MAX_FONT_FAMILIES_PER_SCENE = 2;

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
/** Returns a CSS background for a dark scene with a radial accent glow. */
export function proBgStyle(
  bg: "dark" | "light" | "subtle_gradient",
  accentColor: string = PALETTE.default_accent,
): React.CSSProperties {
  if (bg === "light") {
    return { backgroundColor: PALETTE.light_bg };
  }
  // Dark scenes get a radial glow behind the content
  const glowColor = accentColor + "18"; // ~9% opacity
  return {
    background: `radial-gradient(ellipse 70% 50% at 50% 50%, ${glowColor} 0%, ${PALETTE.dark_bg} 100%)`,
    backgroundColor: PALETTE.dark_bg,
  };
}

// We need React types for CSSProperties
import type React from "react";

// ── Rendering defaults ──────────────────────────────────────────────
export const DEFAULT_WIDTH = 1920;
export const DEFAULT_HEIGHT = 1080;
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
