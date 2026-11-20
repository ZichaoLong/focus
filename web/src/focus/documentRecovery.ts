import { recoveryStorage } from '../lib/mobileHost';
import { FocusApiError } from './types';

export function isFocusSessionRejection(error: unknown): boolean {
  return error instanceof FocusApiError && error.status === 401
    && ['unauthorized', 'authentication_required', 'invalid_bootstrap'].includes(error.code);
}

// Only a previously usable document may spend this allowance. Keep the stamp
// across reloads and fail closed if persistence is unavailable.
export function documentReloadDelay(now = Date.now()): number | null {
  try {
    const saved = recoveryStorage().getItem('focus-web.last-access-reload');
    if (saved === null) return 0;
    const stamp = Number(saved);
    return Number.isFinite(stamp) ? Math.min(60_000, Math.max(0, stamp + 60_000 - now)) : null;
  } catch { return null; }
}

export function reserveDocumentReload(now = Date.now()): boolean {
  try {
    const key = 'focus-web.last-access-reload';
    const storage = recoveryStorage();
    if (documentReloadDelay(now) !== 0) return false;
    storage.setItem(key, String(now));
    return storage.getItem(key) === String(now);
  } catch { return false; }
}
