import { computed, nextTick, ref, watch } from 'vue';
import { mobileReadingThread, rememberMobileReadingThread } from '../lib/mobileHost';

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
  let savedThread = mobileReadingThread();

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
    savedThread = '';
    pendingReadingModeIntent.value = false;
    options.dismissChrome();
    presentationMode.value = 'reading';
    if (options.confirmedThread?.value) rememberMobileReadingThread(options.confirmedThread.value);
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
    savedThread = '';
    pendingReadingModeIntent.value = false;
    rememberMobileReadingThread('');
    exitReadingMode();
  }

  // Only a confirmed, readable destination can consume a cold bookmark.
  // An empty startup view or an authorization screen has no preference to save.
  watch([
    () => options.confirmedThread?.value ?? '',
    () => options.initialized.value,
    () => options.canEnter.value,
    readingMode,
  ], ([thread, initialized, readable, reading]) => {
    if (!initialized || !readable || !thread) return;
    if (reading) rememberMobileReadingThread(thread);
    else if (savedThread === thread) enterReadingMode();
    savedThread = '';
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
