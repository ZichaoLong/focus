// apps/kimi-web/src/composables/useNarrowViewport.ts
// Reactive viewport-width flag for the Focus shell's responsive branch.
//
// This deliberately describes layout space, not a phone, tablet, or desktop
// device. When window.matchMedia is unavailable, the wide layout is used.

import { onUnmounted, ref, type Ref } from 'vue';

/** Viewports at or below this width use the single-column narrow shell. */
export const NARROW_VIEWPORT_MAX_WIDTH = 640;
const NARROW_VIEWPORT_QUERY = `(max-width: ${NARROW_VIEWPORT_MAX_WIDTH}px)`;

/**
 * Returns a reactive ref that is `true` on narrow (≤640px) viewports and
 * `false` otherwise. Guarded for environments without matchMedia.
 */
export function useNarrowViewport(): Ref<boolean> {
  const narrowViewport = ref(false);

  // SSR / no-matchMedia guard: stay on the wide layout (false).
  if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') {
    return narrowViewport;
  }

  const mql = window.matchMedia(NARROW_VIEWPORT_QUERY);
  narrowViewport.value = mql.matches;

  const onChange = (e: MediaQueryListEvent | MediaQueryList): void => {
    narrowViewport.value = e.matches;
  };

  // addEventListener is the modern API; addListener is the deprecated fallback
  // for older Safari. Guard both so we never throw.
  if (typeof mql.addEventListener === 'function') {
    mql.addEventListener('change', onChange);
    onUnmounted(() => mql.removeEventListener('change', onChange));
  } else if (typeof mql.addListener === 'function') {
    // eslint-disable-next-line deprecation/deprecation
    mql.addListener(onChange);
    // eslint-disable-next-line deprecation/deprecation
    onUnmounted(() => mql.removeListener(onChange));
  }

  return narrowViewport;
}
