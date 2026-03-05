/**
 * Font loading for Remotion render environment.
 * Uses @remotion/google-fonts to guarantee fonts are available before rendering.
 *
 * Import this file at the top of Root.tsx so fonts load before any composition.
 */
import { loadFont as loadInter } from "@remotion/google-fonts/Inter";
import { loadFont as loadSpaceGrotesk } from "@remotion/google-fonts/SpaceGrotesk";

const interResult = loadInter();
const spaceGroteskResult = loadSpaceGrotesk();

export const interFamily = interResult.fontFamily;
export const spaceGroteskFamily = spaceGroteskResult.fontFamily;
