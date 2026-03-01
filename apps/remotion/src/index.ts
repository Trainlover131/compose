/**
 * SUPACUT Remotion Scene Pack — Composition Registry
 *
 * Each composition is registered with inputProps for type-safe rendering.
 * Render via: npx remotion render src/index.ts <composition-id> out.mp4 --props='...'
 * Or via Node API: bundle() + getCompositions() + renderMedia().
 */
import { registerRoot } from "remotion";
import { Root } from "./Root";

registerRoot(Root);
