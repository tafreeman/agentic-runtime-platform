/**
 * Platform detection for keyboard-shortcut hints.
 *
 * The command palette opens on ⌘K (Apple) or Ctrl+K (everything else); the
 * visible hint must name the modifier the viewer actually has.
 */

/** The subset of `Navigator` this module reads (User-Agent Client Hints + legacy). */
export interface PlatformNavigator {
  readonly platform?: string;
  readonly userAgentData?: { readonly platform?: string };
}

const APPLE_PLATFORM = /mac|iphone|ipad|ipod|ios/i;

function currentNavigator(): PlatformNavigator | undefined {
  // SSR / non-browser test environments have no `navigator` global.
  return typeof navigator === "undefined"
    ? undefined
    : (navigator as unknown as PlatformNavigator);
}

/**
 * True on macOS / iOS / iPadOS. Prefers User-Agent Client Hints
 * (`navigator.userAgentData.platform`, e.g. "macOS") and falls back to the
 * legacy `navigator.platform` (e.g. "MacIntel", "iPhone"). Returns false when
 * neither is available (SSR, jsdom), so the default hint is "Ctrl K".
 */
export function isApplePlatform(
  nav: PlatformNavigator | undefined = currentNavigator(),
): boolean {
  if (!nav) return false;
  // `||` rather than `??`: some browsers report an empty-string platform.
  const platform = nav.userAgentData?.platform || nav.platform || "";
  return APPLE_PLATFORM.test(platform);
}

/** The keys of the command-palette shortcut, e.g. `["⌘", "K"]` or `["Ctrl", "K"]`. */
export function paletteShortcutKeys(
  nav: PlatformNavigator | undefined = currentNavigator(),
): readonly [string, string] {
  return isApplePlatform(nav) ? ["⌘", "K"] : ["Ctrl", "K"];
}
