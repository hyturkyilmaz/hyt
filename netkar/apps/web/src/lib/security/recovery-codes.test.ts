import { afterEach, describe, expect, it, vi } from 'vitest';

import { downloadTextFile, formatRecoveryCodesFile } from '@/lib/security/recovery-codes';

describe('formatRecoveryCodesFile', () => {
  it('kodları numaralı listeler, tarih ve kullanım notu ekler; kişisel veri yazmaz', () => {
    const text = formatRecoveryCodesFile(
      ['AAAA-BBBB-CCCC', 'DDDD-EEEE-FFFF'],
      new Date('2026-11-17T10:00:00Z'),
    );
    expect(text).toContain('Oluşturulma: 2026-11-17');
    expect(text).toContain('01. AAAA-BBBB-CCCC');
    expect(text).toContain('02. DDDD-EEEE-FFFF');
    expect(text).toContain('yalnız BİR kez');
    expect(text).not.toContain('@');
    expect(text).not.toContain(String.fromCharCode(0x2014));
    expect(text).not.toContain(String.fromCharCode(0x2015));
  });
});

describe('downloadTextFile', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.restoreAllMocks();
  });

  it('nesne adresini indirme tıklamasından SONRA, zamanlayıcıyla serbest bırakır', () => {
    vi.useFakeTimers();
    const revoke = vi.fn();
    URL.createObjectURL = () => 'blob:test';
    URL.revokeObjectURL = revoke;
    const click = vi
      .spyOn(HTMLAnchorElement.prototype, 'click')
      .mockImplementation(() => undefined);
    downloadTextFile('a.txt', 'x');
    expect(click).toHaveBeenCalledTimes(1);
    expect(revoke).not.toHaveBeenCalled();
    vi.advanceTimersByTime(1000);
    expect(revoke).toHaveBeenCalledWith('blob:test');
  });
});

describe('kurtarma kodu biçim kuralı (backend ile aynı)', () => {
  it('yalnız boşluk ve tire ayracını kabul eder; sekme ve satır sonunu reddeder', async () => {
    const { recoveryCodeSchema } = await import('@/lib/validation/auth');
    expect(recoveryCodeSchema.safeParse({ code: 'abcd-efgh jk2m' }).success).toBe(true);
    expect(recoveryCodeSchema.safeParse({ code: 'abcd\tefgh\njk2m' }).success).toBe(false);
  });
});
