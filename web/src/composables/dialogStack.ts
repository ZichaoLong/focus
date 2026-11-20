// Opening order also applies to teleported viewers and dialogs whose iframe has focus.
const openDialogs = new Set<() => void>();

export function trackDialog(back: () => void, open: boolean): void {
  if (open) openDialogs.add(back);
  else openDialogs.delete(back);
}

export function backFromDialog(): boolean {
  const top = Array.from(openDialogs).at(-1);
  if (!top) return false;
  top();
  return true;
}
