import { hasMobileFeature } from '../lib/mobileHost';
import { computed, shallowRef, type ComputedRef } from 'vue';
import type { FocusEventHandlers } from './api';
import type { FocusProjectionEvent } from './types';

const PROJECTION_REFRESH_DELAY_MS = 90;
const THREAD_LIST_REFRESH_DELAY_MS = 250;
const INITIAL_RECONNECT_DELAY_MS = 1_000;
const MAX_RECONNECT_DELAY_MS = 10_000;
const INITIAL_PROJECTION_RETRY_DELAY_MS = 250;
const MAX_PROJECTION_RETRY_DELAY_MS = 10_000;
const HANDSHAKE_TIMEOUT_MS = 15_000;
const ACCESS_PROBE_TIMEOUT_MS = 5_000;
const WAKE_CHECK_DELAY_MS = 200;
const WAKE_PONG_TIMEOUT_MS = 5_000;

export type FocusTransportConnectionState = 'connecting' | 'connected' | 'disconnected';
export type FocusHandshakeProbeDisposition = 'retry' | 'stop';

export interface FocusTransportSessionSnapshot {
  connection: FocusTransportConnectionState;
  hasOpenedEventSocket: boolean;
  reconnectScheduled: boolean;
  projectionReloadRetryScheduled: boolean;
  disposed: boolean;
}

export interface FocusTransportSessionCallbacks {
  mayConnect(): boolean;
  openEventSocket(handlers: FocusEventHandlers): WebSocket;
  probeEventAccess(signal: AbortSignal): Promise<void>;
  onHandshakeProbeError(error: unknown): FocusHandshakeProbeDisposition;
  onConnectionError(error: unknown): void;
  onSocketOpened(): void;
  onHandshakeReady(reconnected: boolean): void;
  onEvent(event: FocusProjectionEvent): void;
  onInvalidEvent(): void;
  refreshProjection(): Promise<void>;
  refreshThreadList(): Promise<void>;
  reloadProjection(): void | Promise<void>;
  mayRetryProjectionReload(): boolean;
  onScheduledTaskError(error: unknown): void;
}

export interface FocusTransportSession {
  readonly snapshot: ComputedRef<Readonly<FocusTransportSessionSnapshot>>;
  connect(): void;
  suspend(): void;
  requestProjectionReload(): void;
  scheduleProjectionRefresh(): void;
  scheduleThreadListRefresh(): void;
  scheduleProjectionReloadRetry(): void;
  cancelProjectionReloadRetry(): void;
  resetProjectionReloadBackoff(): void;
  dispose(): void;
}

/**
 * Owns the browser event transport and every timer created from that
 * transport. Domain projection installation remains with the caller and is
 * reached only through the command callbacks above.
 */
export function createFocusTransportSession(
  callbacks: FocusTransportSessionCallbacks,
): FocusTransportSession {
  const mutableSnapshot = shallowRef<FocusTransportSessionSnapshot>({
    connection: 'connecting',
    hasOpenedEventSocket: false,
    reconnectScheduled: false,
    projectionReloadRetryScheduled: false,
    disposed: false,
  });
  const snapshot = computed<Readonly<FocusTransportSessionSnapshot>>(
    () => mutableSnapshot.value,
  );

  let socket: WebSocket | null = null;
  let socketGeneration = 0;
  let reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  let projectionRefreshTimer: ReturnType<typeof setTimeout> | null = null;
  let threadListRefreshTimer: ReturnType<typeof setTimeout> | null = null;
  let projectionReloadRetryTimer: ReturnType<typeof setTimeout> | null = null;
  let reconnectAttempt = 0;
  let projectionReloadRetryAttempt = 0;
  let hasCompletedHandshake = false;
  let suspended = false;
  let handshakeTimer: ReturnType<typeof setTimeout> | null = null;
  let wakeTimer: ReturnType<typeof setTimeout> | null = null;
  let pongTimer: ReturnType<typeof setTimeout> | null = null;
  let accessProbe: { controller: AbortController; timer: ReturnType<typeof setTimeout> } | null = null;
  const browser = typeof window === 'undefined' ? null : window;
  const page = typeof document === 'undefined' ? null : document;

  function cancelAccessProbe(): void {
    const probe = accessProbe;
    accessProbe = null;
    if (!probe) return;
    clearTimeout(probe.timer);
    probe.controller.abort();
  }

  function clearSocketTimers(): void {
    if (handshakeTimer !== null) clearTimeout(handshakeTimer);
    handshakeTimer = null;
    if (pongTimer !== null) clearTimeout(pongTimer);
    pongTimer = null;
  }

  function retireSocket(expectedGeneration: number): boolean {
    if (expectedGeneration !== socketGeneration) return false;
    const previous = socket;
    socket = null;
    clearSocketTimers();
    cancelProjectionReadTimers();
    updateSnapshot({ connection: 'disconnected' });
    // Clear the owner before close: delayed callbacks cannot retire its successor.
    previous?.close();
    return true;
  }

  function updateSnapshot(changes: Partial<FocusTransportSessionSnapshot>): void {
    mutableSnapshot.value = { ...mutableSnapshot.value, ...changes };
  }

  function cancelReconnect(): void {
    if (reconnectTimer === null) return;
    clearTimeout(reconnectTimer);
    reconnectTimer = null;
    updateSnapshot({ reconnectScheduled: false });
  }

  function cancelProjectionReloadRetry(): void {
    if (projectionReloadRetryTimer === null) return;
    clearTimeout(projectionReloadRetryTimer);
    projectionReloadRetryTimer = null;
    updateSnapshot({ projectionReloadRetryScheduled: false });
  }

  function scheduleReconnect(expectedGeneration: number): void {
    if (
      mutableSnapshot.value.disposed
      || suspended
      || !callbacks.mayConnect()
      || socket !== null
      || expectedGeneration !== socketGeneration
    ) return;
    cancelReconnect();
    const delay = Math.min(
      INITIAL_RECONNECT_DELAY_MS * 2 ** reconnectAttempt,
      MAX_RECONNECT_DELAY_MS,
    );
    reconnectAttempt += 1;
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null;
      updateSnapshot({ reconnectScheduled: false });
      if (expectedGeneration !== socketGeneration) return;
      connect();
    }, delay);
    updateSnapshot({ reconnectScheduled: true });
  }

  function handleUnopenedSocketClose(expectedGeneration: number): void {
    cancelAccessProbe();
    const controller = new AbortController();
    const current = () => accessProbe?.controller === controller
      && !mutableSnapshot.value.disposed && !suspended && callbacks.mayConnect()
      && socket === null && expectedGeneration === socketGeneration;
    const finish = (error?: unknown) => {
      if (!current()) return;
      cancelAccessProbe();
      if (error !== undefined && callbacks.onHandshakeProbeError(error) === 'stop') {
        suspend();
        return;
      }
      scheduleReconnect(expectedGeneration);
    };
    accessProbe = { controller, timer: setTimeout(() => finish(), ACCESS_PROBE_TIMEOUT_MS) };
    try {
      // The deadline advances recovery even if a fetch implementation ignores abort.
      void callbacks.probeEventAccess(controller.signal).then(() => finish(), finish);
    } catch (error) { finish(error); }
  }

  function connect(): void {
    if (mutableSnapshot.value.disposed || !callbacks.mayConnect()) return;
    suspended = false;
    cancelReconnect();
    cancelAccessProbe();
    clearSocketTimers();
    socketGeneration += 1;
    const generation = socketGeneration;
    const previousSocket = socket;
    socket = null;
    previousSocket?.close();
    updateSnapshot({ connection: 'connecting' });
    try {
      let nextSocket: WebSocket;
      let socketHandshakeReady = false;
      nextSocket = callbacks.openEventSocket({
        open: () => {
          if (socket !== nextSocket || generation !== socketGeneration) return;
          updateSnapshot({
            hasOpenedEventSocket: true,
          });
          callbacks.onSocketOpened();
        },
        close: () => {
          if (socket !== nextSocket || generation !== socketGeneration) return;
          retireSocket(generation);
          if (mutableSnapshot.value.disposed || !callbacks.mayConnect()) return;
          if (socketHandshakeReady) scheduleReconnect(generation);
          else handleUnopenedSocketClose(generation);
        },
        invalid: () => {
          if (socket === nextSocket && generation === socketGeneration) {
            callbacks.onInvalidEvent();
          }
        },
        pong: () => {
          if (socket !== nextSocket || generation !== socketGeneration) return;
          if (pongTimer !== null) clearTimeout(pongTimer);
          pongTimer = null;
        },
        event: (event) => {
          if (socket === nextSocket && generation === socketGeneration) {
            if (event.type === 'hello' && !socketHandshakeReady) {
              socketHandshakeReady = true;
              if (handshakeTimer !== null) clearTimeout(handshakeTimer);
              handshakeTimer = null;
              reconnectAttempt = 0;
              updateSnapshot({ connection: 'connected' });
              const reconnected = hasCompletedHandshake;
              hasCompletedHandshake = true;
              // Gateway sends hello only after its document-connection
              // transaction. Notify composition before projection handling so
              // an authoritative hello reload can supersede a queued initial
              // lightweight refresh.
              callbacks.onHandshakeReady(reconnected);
            }
            callbacks.onEvent(event);
          }
        },
      });
      socket = nextSocket;
      handshakeTimer = setTimeout(() => {
        handshakeTimer = null;
        if (!retireSocket(generation)) return;
        handleUnopenedSocketClose(generation);
      }, HANDSHAKE_TIMEOUT_MS);
    } catch (error) {
      callbacks.onConnectionError(error);
      updateSnapshot({ connection: 'disconnected' });
      scheduleReconnect(generation);
    }
  }

  function checkAfterWake(): void {
    wakeTimer = null;
    if (mutableSnapshot.value.disposed || suspended || socketGeneration === 0
      || page?.visibilityState === 'hidden' || !callbacks.mayConnect()) return;
    if (mutableSnapshot.value.connection === 'connecting') return; // Already has a handshake deadline.
    if (!socket || socket.readyState !== 1) { connect(); return; }
    if (pongTimer !== null) return;
    const generation = socketGeneration;
    pongTimer = setTimeout(() => {
      pongTimer = null;
      if (retireSocket(generation)) connect();
    }, WAKE_PONG_TIMEOUT_MS);
    try { socket.send('ping'); }
    catch { if (retireSocket(generation)) connect(); }
  }

  function scheduleWakeCheck(): void {
    if (wakeTimer !== null || mutableSnapshot.value.disposed || suspended
      || socketGeneration === 0 || page?.visibilityState === 'hidden' || !callbacks.mayConnect()) return;
    wakeTimer = setTimeout(checkAfterWake, WAKE_CHECK_DELAY_MS);
  }

  function visibilityChanged(): void {
    if (page?.visibilityState !== 'hidden') { scheduleWakeCheck(); return; }
    if (wakeTimer !== null) clearTimeout(wakeTimer);
    wakeTimer = null;
    // A frozen background document cannot reliably observe a pong deadline.
    if (pongTimer !== null) clearTimeout(pongTimer);
    pongTimer = null;
  }

  function pageShown(event: PageTransitionEvent): void {
    if (event.persisted) scheduleWakeCheck();
  }

  if (hasMobileFeature('wake')) browser?.addEventListener?.('focus-host-resume', scheduleWakeCheck);
  browser?.addEventListener?.('online', scheduleWakeCheck);
  browser?.addEventListener?.('pageshow', pageShown);
  page?.addEventListener?.('visibilitychange', visibilityChanged);

  function cancelProjectionReadTimers(): void {
    if (projectionRefreshTimer !== null) {
      clearTimeout(projectionRefreshTimer);
      projectionRefreshTimer = null;
    }
    if (threadListRefreshTimer !== null) {
      clearTimeout(threadListRefreshTimer);
      threadListRefreshTimer = null;
    }
  }

  function suspend(): void {
    suspended = true;
    socketGeneration += 1;
    cancelReconnect();
    cancelProjectionReloadRetry();
    cancelAccessProbe();
    clearSocketTimers();
    if (wakeTimer !== null) clearTimeout(wakeTimer);
    wakeTimer = null;
    const currentSocket = socket;
    socket = null;
    currentSocket?.close();
    cancelProjectionReadTimers();
    updateSnapshot({ connection: 'disconnected' });
  }

  function runScheduledTask(task: () => Promise<void>): void {
    if (mutableSnapshot.value.disposed) return;
    void task().catch(callbacks.onScheduledTaskError);
  }

  function scheduleProjectionRefresh(): void {
    if (mutableSnapshot.value.disposed) return;
    if (projectionRefreshTimer !== null) clearTimeout(projectionRefreshTimer);
    projectionRefreshTimer = setTimeout(() => {
      projectionRefreshTimer = null;
      runScheduledTask(callbacks.refreshProjection);
    }, PROJECTION_REFRESH_DELAY_MS);
  }

  function scheduleThreadListRefresh(): void {
    if (mutableSnapshot.value.disposed) return;
    if (threadListRefreshTimer !== null) clearTimeout(threadListRefreshTimer);
    threadListRefreshTimer = setTimeout(() => {
      threadListRefreshTimer = null;
      runScheduledTask(callbacks.refreshThreadList);
    }, THREAD_LIST_REFRESH_DELAY_MS);
  }

  function requestProjectionReload(): void {
    if (mutableSnapshot.value.disposed) return;
    // A composite reload subsumes queued lightweight reads. Leaving either
    // timer armed would let older work advance request generations after the
    // authoritative reload has already started.
    cancelProjectionReadTimers();
    try {
      void Promise.resolve(callbacks.reloadProjection()).catch(callbacks.onScheduledTaskError);
    } catch (error) {
      callbacks.onScheduledTaskError(error);
    }
  }

  function scheduleProjectionReloadRetry(): void {
    if (
      projectionReloadRetryTimer !== null
      || mutableSnapshot.value.disposed
      || !callbacks.mayRetryProjectionReload()
    ) return;
    const delay = Math.min(
      INITIAL_PROJECTION_RETRY_DELAY_MS * 2 ** projectionReloadRetryAttempt,
      MAX_PROJECTION_RETRY_DELAY_MS,
    );
    projectionReloadRetryAttempt += 1;
    projectionReloadRetryTimer = setTimeout(() => {
      projectionReloadRetryTimer = null;
      updateSnapshot({ projectionReloadRetryScheduled: false });
      if (mutableSnapshot.value.disposed || !callbacks.mayRetryProjectionReload()) return;
      requestProjectionReload();
    }, delay);
    updateSnapshot({ projectionReloadRetryScheduled: true });
  }

  function resetProjectionReloadBackoff(): void {
    projectionReloadRetryAttempt = 0;
  }

  function dispose(): void {
    if (mutableSnapshot.value.disposed) return;
    updateSnapshot({ disposed: true });
    suspend();
    browser?.removeEventListener?.('focus-host-resume', scheduleWakeCheck);
    browser?.removeEventListener?.('online', scheduleWakeCheck);
    browser?.removeEventListener?.('pageshow', pageShown);
    page?.removeEventListener?.('visibilitychange', visibilityChanged);
  }

  return {
    snapshot,
    connect,
    suspend,
    requestProjectionReload,
    scheduleProjectionRefresh,
    scheduleThreadListRefresh,
    scheduleProjectionReloadRetry,
    cancelProjectionReloadRetry,
    resetProjectionReloadBackoff,
    dispose,
  };
}
