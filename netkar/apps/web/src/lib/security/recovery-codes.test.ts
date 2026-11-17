import { describe, expect, it } from 'vitest';

import { formatRecoveryCodesFile } from '@/lib/security/recovery-codes';

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
