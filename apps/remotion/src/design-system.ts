/**
 * SUPACUT REMOTION DESIGN SYSTEM (v1)
 *
 * Minimal, intentional motion. No chaos. No heavy 3D. No glitch overload.
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

// ── Colors ──────────────────────────────────────────────────────────
export const PALETTE = {
  dark_bg: "#0A0A0A",
  light_bg: "#FAFAFA",
  white: "#FFFFFF",
  black: "#000000",
  muted: "#888888",
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
