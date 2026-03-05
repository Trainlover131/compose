/**
 * CustomRemotionScene: renders a CustomRemotionSceneSpec into a composition.
 *
 * V3 — uses Swishy display stack (ProSceneWrapper + typography tokens).
 * Portrait 1080x1920 layout.
 */
import React from "react";
import { AbsoluteFill } from "remotion";
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
  ProSceneWrapper,
} from "../components/AnimationPrimitives";
import { FONTS, PALETTE, BUDGET, proBgStyle, fgColor, TYPE_SCALE, TEXT_STYLES } from "../design-system";
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
  const delay = index * 5;
  switch (primitive) {
    case "FadeIn":
      return <FadeIn durationFrames={12} delay={delay}>{children}</FadeIn>;
    case "SlideUp":
      return <SlideUp durationFrames={14} delay={delay}>{children}</SlideUp>;
    case "SlideLeft":
      return <SlideLeft durationFrames={14} delay={delay}>{children}</SlideLeft>;
    case "ScaleSpring":
      return <ScaleSpring delay={delay}>{children}</ScaleSpring>;
    case "MaskReveal":
      return <MaskReveal durationFrames={16} delay={delay}>{children}</MaskReveal>;
    case "HighlightSweep":
      return <HighlightSweep durationFrames={16} delay={delay}>{children}</HighlightSweep>;
    case "SoftZoom":
      return <SoftZoom delay={delay}>{children}</SoftZoom>;
    case "SubtleRotate3D":
      return <SubtleRotate3D durationFrames={20} delay={delay}>{children}</SubtleRotate3D>;
    default:
      return <FadeIn durationFrames={12} delay={delay}>{children}</FadeIn>;
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
  const resolvedFont = fontFamily === "Georgia" || fontFamily === "Georgia, serif"
    ? FONTS.display
    : (fontFamily || FONTS.display);

  let content: React.ReactNode;

  switch (el.type) {
    case "text":
      content = (
        <p
          style={{
            color: foreground,
            fontSize: TYPE_SCALE.title - 8,
            fontWeight: 600,
            fontFamily: resolvedFont,
            textAlign: el.layout === "center" ? "center" : "left",
            maxWidth: 960,
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
          durationFrames={25}
          delay={index * 5}
          style={{
            ...TEXT_STYLES.heroNumber,
            fontSize: TYPE_SCALE.hero - 24,
            color: foreground,
          }}
        />
      );
      break;
    case "line":
      content = (
        <DrawLine
          color={accentColor}
          width={Number(el.data?.width ?? 100)}
          thickness={Number(el.data?.thickness ?? 3)}
          durationFrames={14}
          delay={index * 5}
        />
      );
      break;
    case "shape":
      content = (
        <div
          style={{
            width: Number(el.data?.width ?? 60),
            height: Number(el.data?.height ?? 60),
            backgroundColor: accentColor,
            borderRadius: Number(el.data?.borderRadius ?? 8),
            boxShadow: `0 0 20px ${accentColor}22`,
          }}
        />
      );
      break;
    default:
      content = (
        <p style={{ color: foreground, fontSize: TYPE_SCALE.subtitle - 2, fontFamily: resolvedFont }}>
          {el.text || ""}
        </p>
      );
  }

  return <>{wrapPrimitive(primitive, content, index)}</>;
};

// ── Main custom scene component ─────────────────────────────────────

export const CustomScene: React.FC<CustomSceneProps> = ({ spec }) => {
  const foreground = fgColor(spec.bg);
  const rawFont = spec.typography.primary_font || FONTS.display;
  const fontFamily = rawFont === "Georgia" || rawFont === "Georgia, serif"
    ? FONTS.display
    : rawFont;
  const accentColor = spec.accent_color || PALETTE.default_accent;
  const bgStyle = proBgStyle(spec.bg, accentColor);

  const maxEl = Math.min(
    spec.hard_limits?.max_elements ?? BUDGET.max_elements_per_scene,
    BUDGET.max_elements_per_scene,
  );
  const elements = spec.elements.slice(0, maxEl);

  return (
    <AbsoluteFill>
      <ProSceneWrapper bg={spec.bg} accentColor={accentColor} bgStyle={bgStyle}>
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 16,
            padding: "0 60px",
            fontFamily,
            width: "100%",
          }}
        >
          {elements.map((el, i) => (
            <ElementRenderer
              key={i}
              el={el}
              index={i}
              foreground={foreground}
              accentColor={accentColor}
              fontFamily={fontFamily}
            />
          ))}
        </div>
      </ProSceneWrapper>
    </AbsoluteFill>
  );
};
