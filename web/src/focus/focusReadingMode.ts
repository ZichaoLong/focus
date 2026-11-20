import { computed, nextTick, ref, watch } from 'vue';
import { rememberReadingMode, threadReading } from '../components/chat/readingBookmark';

interface ValueRef<T> {
  readonly value: T;
}

interface FocusReadingModeOptions {
  canEnter: ValueRef<boolean>;
  documentAccessAvailable: ValueRef<boolean>;
  initialized: ValueRef<boolean>;
  meta: ValueRef<unknown | null>;
  conversationLoading: ValueRef<boolean>;
  turns: ValueRef<readonly unknown[]>;
  confirmedThread?: ValueRef<string>;
  dismissChrome: () => void;
  dismissSwitcher: () => void;
}

type FocusPresentationMode = 'normal' | 'reading';

export function useFocusReadingMode(options: FocusReadingModeOptions) {
  const presentationMode = ref<FocusPresentationMode>('normal');
  const readingMode = computed(() => presentationMode.value === 'reading');
  const pendingReadingModeIntent = ref(false);
  let restoredThread = '';

  function focusReadingModeToggle(): void {
    if (typeof document === 'undefined') return;
    void nextTick(() => {
      Array.from(document.querySelectorAll<HTMLButtonElement>('[data-reading-mode-toggle]'))
        .find((button) => button.offsetParent !== null)
        ?.focus({ preventScroll: true });
    });
  }

  function enterReadingMode(): void {
    if (!options.canEnter.value || readingMode.value) return;
    pendingReadingModeIntent.value = false;
    options.dismissChrome();
    presentationMode.value = 'reading';
    if (options.confirmedThread?.value) rememberReadingMode(options.confirmedThread.value, true);
    focusReadingModeToggle();
  }

  function requestReadingMode(): void {
    if (!options.documentAccessAvailable.value) return;
    if (options.canEnter.value) {
      enterReadingMode();
      return;
    }
    pendingReadingModeIntent.value = true;
  }

  function exitReadingMode(): void {
    if (!readingMode.value) return;
    options.dismissSwitcher();
    presentationMode.value = 'normal';
    focusReadingModeToggle();
  }

  function chooseNormalMode(): void {
    pendingReadingModeIntent.value = false;
    if (options.confirmedThread?.value) rememberReadingMode(options.confirmedThread.value, false);
    exitReadingMode();
  }

  // Only a confirmed, readable destination can consume a cold bookmark.
  // An empty startup view or an authorization screen has no preference to save.
  watch([
    () => options.confirmedThread?.value ?? '',
    () => options.initialized.value,
    () => options.canEnter.value,
  ], ([thread, initialized, readable]) => {
    if (!thread) { restoredThread = ''; return; }
    if (!initialized || !readable || thread === restoredThread) return;
    restoredThread = thread;
    const saved = threadReading(thread);
    if (saved?.reading) enterReadingMode();
    else if (saved) exitReadingMode();
    rememberReadingMode(thread, readingMode.value);
  }, { flush: 'pre' });

  watch(
    [() => options.conversationLoading.value, () => options.turns.value.length],
    ([loading, turnCount]) => {
      if (readingMode.value && !loading && turnCount === 0) exitReadingMode();
    },
  );
  watch(
    [
      () => options.canEnter.value,
      () => options.initialized.value,
      () => options.meta.value,
      () => options.conversationLoading.value,
    ],
    ([canEnter, initialized, meta, conversationLoading]) => {
      if (!pendingReadingModeIntent.value) return;
      if (canEnter) {
        enterReadingMode();
        return;
      }
      if (initialized && meta && !conversationLoading) {
        pendingReadingModeIntent.value = false;
      }
    },
    { flush: 'sync' },
  );
  watch(
    () => options.documentAccessAvailable.value,
    (available) => {
      if (available) return;
      pendingReadingModeIntent.value = false;
      exitReadingMode();
    },
    { flush: 'sync' },
  );

  return {
    readingMode,
    pendingReadingModeIntent,
    requestReadingMode,
    chooseNormalMode,
    enterReadingMode,
    exitReadingMode,
  };
}
