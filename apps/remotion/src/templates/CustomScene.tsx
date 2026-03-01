/**
 * CustomRemotionScene: renders a CustomRemotionSceneSpec into a composition.
 *
 * This is the V2 path. The spec is a strict JSON contract — NOT a freeform
 * prompt. Every element compiles down to the allowed animation primitives
 * from the SUPACUT design system.
 */
import React from "react";
import { AbsoluteFill, useCurrentFrame, useVideoConfig, interpolate, Easing } from "remotion";
import {
  FadeIn,
  SlideUp,
  SlideLeft,
  ScaleSpring,
  CountUpNumber,
  DrawLine,
  MaskReveal,
  HighlightSweep,
  SoftZoom,
  SubtleRotate3D,
} from "../components/AnimationPrimitives";
import { FONTS, bgColor, fgColor, PALETTE, BUDGET } from "../design-system";
import type { MotionPrimitive } from "../design-system";

// ── CustomRemotionSceneSpec types ───────────────────────────────────

export type SceneKind =
  | "headline_highlight"
  | "travel_route"
  | "profile_intro"
  | "kpi"
  | "chart"
  | "steps"
  | "quote"
  | "code"
  | "other_restrained";

export interface ElementSpec {
  type: "text" | "number" | "image" | "line" | "shape";
  layout: "center" | "left" | "right" | "top" | "bottom" | "stack";
  text?: string;
  image_asset_id?: string;
  data?: Record<string, unknown>;
  animation_primitives: MotionPrimitive[];
}

export interface TypographySpec {
  primary_font: string;
  mono_font: string;
  serif_font?: string;
  max_families: number;
}

export interface CustomRemotionSceneSpec {
  scene_kind: SceneKind;
  duration_sec: number;
  bg: "dark" | "light" | "subtle_gradient";
  accent_color: string;
  typography: TypographySpec;
  elements: ElementSpec[];
  allowed_primitives: MotionPrimitive[];
  hard_limits: {
    max_elements: number;
    max_simultaneous_animations: number;
    max_accent_colors: number;
  };
}

export interface CustomSceneProps {
  spec: CustomRemotionSceneSpec;
}

// ── Wrapper for each animation primitive ────────────────────────────

function wrapPrimitive(
  primitive: MotionPrimitive,
  children: React.ReactNode,
  index: number,
): React.ReactNode {
  const delay = index * 6;
  switch (primitive) {
    case "FadeIn":
      return <FadeIn durationFrames={15} delay={delay}>{children}</FadeIn>;
    case "SlideUp":
      return <SlideUp durationFrames={18} delay={delay}>{children}</SlideUp>;
    case "SlideLeft":
      return <SlideLeft durationFrames={18} delay={delay}>{children}</SlideLeft>;
    case "ScaleSpring":
      return <ScaleSpring delay={delay}>{children}</ScaleSpring>;
    case "MaskReveal":
      return <MaskReveal durationFrames={20} delay={delay}>{children}</MaskReveal>;
    case "HighlightSweep":
      return <HighlightSweep durationFrames={20} delay={delay}>{children}</HighlightSweep>;
    case "SoftZoom":
      return <SoftZoom delay={delay}>{children}</SoftZoom>;
    case "SubtleRotate3D":
      return <SubtleRotate3D durationFrames={25} delay={delay}>{children}</SubtleRotate3D>;
    default:
      return <FadeIn durationFrames={15} delay={delay}>{children}</FadeIn>;
  }
}

// ── Element renderer ────────────────────────────────────────────────

const ElementRenderer: React.FC<{
  el: ElementSpec;
  index: number;
  foreground: string;
  accentColor: string;
  fontFamily: string;
}> = ({ el, index, foreground, accentColor, fontFamily }) => {
  const primitive = el.animation_primitives[0] || "FadeIn";

  let content: React.ReactNode;

  switch (el.type) {
    case "text":
      content = (
        <p
          style={{
            color: foreground,
            fontSize: 44,
            fontWeight: 600,
            fontFamily,
            textAlign: el.layout === "center" ? "center" : "left",
            maxWidth: 1400,
            lineHeight: 1.4,
          }}
        >
          {el.text || ""}
        </p>
      );
      break;
    case "number":
      content = (
        <CountUpNumber
          value={Number(el.data?.value ?? 0)}
          prefix={String(el.data?.prefix ?? "")}
          suffix={String(el.data?.suffix ?? "")}
          durationFrames={45}
          delay={index * 6}
          style={{
            color: foreground,
            fontSize: 96,
            fontWeight: 700,
            fontFamily,
          }}
        />
      );
      break;
    case "line":
      content = (
        <DrawLine
          color={accentColor}
          width={Number(el.data?.width ?? 120)}
          thickness={Number(el.data?.thickness ?? 3)}
          durationFrames={20}
          delay={index * 6}
        />
      );
      break;
    case "shape":
      content = (
        <div
          style={{
            width: Number(el.data?.width ?? 80),
            height: Number(el.data?.height ?? 80),
            backgroundColor: accentColor,
            borderRadius: Number(el.data?.borderRadius ?? 8),
          }}
        />
      );
      break;
    default:
      content = (
        <p style={{ color: foreground, fontSize: 36, fontFamily }}>
          {el.text || ""}
        </p>
      );
  }

  return <>{wrapPrimitive(primitive, content, index)}</>;
};

// ── Main custom scene component ─────────────────────────────────────

export const CustomScene: React.FC<CustomSceneProps> = ({ spec }) => {
  const background = bgColor(spec.bg);
  const foreground = fgColor(spec.bg);
  const fontFamily = spec.typography.primary_font || FONTS.primary;

  // Enforce hard limits: cap elements
  const maxEl = Math.min(
    spec.hard_limits?.max_elements ?? BUDGET.max_elements_per_scene,
    BUDGET.max_elements_per_scene,
  );
  const elements = spec.elements.slice(0, maxEl);

  const bgStyle: React.CSSProperties =
    spec.bg === "subtle_gradient"
      ? {
          background: `linear-gradient(160deg, ${PALETTE.dark_bg} 0%, #1A1A2E 100%)`,
        }
      : { backgroundColor: background };

  return (
    <AbsoluteFill
      style={{
        ...bgStyle,
        display: "flex",
        flexDirection: "column",
        alignItems: "center",
        justifyContent: "center",
        gap: 24,
        padding: "0 120px",
        fontFamily,
      }}
    >
      {elements.map((el, i) => (
        <ElementRenderer
          key={i}
          el={el}
          index={i}
          foreground={foreground}
          accentColor={spec.accent_color || PALETTE.default_accent}
          fontFamily={fontFamily}
        />
      ))}
    </AbsoluteFill>
  );
};
