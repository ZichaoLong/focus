import type { ChatTurn } from '../types';
import type { Accent, ColorScheme } from '../composables/client/useAppearance';
import type { LocaleCode } from '../i18n';
import { hasMobileFeature, mobileRecords } from '../lib/mobileHost';
import { classifyRecordTurn, type RecordItem, type ToolCount } from './mobileRecordPage';

export interface SavedWindow {
  thread: string; title: string; rows: (RecordItem & {id?: string} | ToolCount)[];
  older: boolean; newer: boolean;
  anchor: { turn?: string; item?: string; chunk?: string; offset?: number; reading?: boolean };
  layout?: ConversationLayout;
}
export interface ConversationLayout {
  colorScheme: ColorScheme; accent: Accent; fontSize: number; locale: LocaleCode;
  workspace: string; model: string; timing: boolean; exports: boolean; reading: boolean;
  width: number; dock: number; sidebar: number;
}
let currentLayout: {thread: string; scope: string; layout: ConversationLayout} | undefined;
export function rememberConversationLayout(thread: string, scope: string, layout: ConversationLayout) {
  if (currentLayout?.thread === thread && currentLayout.scope === scope
    && JSON.stringify(currentLayout.layout) === JSON.stringify(layout)) return;
  currentLayout = {thread, scope, layout};
  mobileRecords('layout', currentLayout);
}
export type WindowRequest = { direction: 'older' | 'newer' | 'open'; turn?: string; item?: string };

export function savedTurns(page: SavedWindow): ChatTurn[] {
  return page.rows.flatMap((row): ChatTurn[] => {
    if (row.kind === 'tools') return [{ id: row.turn + ':item:' + row.first + ':0', rawTurnId: row.turn,
      itemId: row.first, role: 'assistant', no: 0, text: '', savedToolCount: row.count }];
    if (row.kind !== 'assistant' && row.kind !== 'user') return [];
    return [{ id: row.id ?? row.turn + ':item:' + row.item + ':0', rawTurnId: row.turn, itemId: row.item,
      role: row.kind, no: 0, text: row.text ?? '', ...(row.partial ? { reply: { state: 'generating' } } : {}) }];
  });
}

export function readSavedWindow(thread: string, scope: string | undefined, request: WindowRequest): SavedWindow | null {
  if (!thread || !scope || !hasMobileFeature('conversation-windows')) return null;
  try {
    const raw = mobileRecords('readwindow', { thread, scope, ...request });
    const page = raw && JSON.parse(raw) as SavedWindow;
    return page && page.thread === thread && page.rows?.length ? page : null;
  } catch { return null; }
}

export function saveConversationWindow(thread: string, title: string, scope: string | undefined, turns: readonly ChatTurn[],
  tail: boolean, older: boolean, newer: boolean, partial = false) {
  if (!scope || !turns.length || !hasMobileFeature('conversation-windows')) return;
  const rows = turns.flatMap(turn => {
    const item = classifyRecordTurn(turn);
    return item ? [{ ...item, id: turn.id }] : [];
  });
  const layout = currentLayout?.thread === thread && currentLayout.scope === scope ? currentLayout.layout : undefined;
  if (rows.length) mobileRecords('putwindow', { thread, title, scope, rows, tail, older, newer, partial, layout });
}
