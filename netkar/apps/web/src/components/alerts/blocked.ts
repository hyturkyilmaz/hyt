/** Doğrulanmamış e-postada yazma düğmesi: gerçekten `disabled` olmaz (odaklanır, açıklaması okunur). */
export const VERIFY_NOTE_ID = 'eposta-dogrulama-notu';

export function blockedProps(blocked: boolean) {
  return {
    'aria-disabled': blocked ? (true as const) : undefined,
    'aria-describedby': blocked ? VERIFY_NOTE_ID : undefined,
  };
}

/** Görünüm: soluk ve imleç yasak; ikincil düğmenin üzerine gelince rengi değişmez. */
export function blockedClass(
  blocked: boolean,
  variant: 'secondary' | 'default' = 'secondary',
): string {
  if (!blocked) return '';
  return `cursor-not-allowed opacity-60 ${
    variant === 'default' ? 'aria-disabled:hover:bg-primary' : 'aria-disabled:hover:bg-surface'
  }`;
}
