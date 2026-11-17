import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';

import { QrCode, buildQrPath } from '@/components/security/qr-code';

describe('QrCode', () => {
  it('aynı girdiden aynı yolu üretir; farklı girdiden farklı yol üretir', () => {
    const a = buildQrPath('otpauth://totp/Ornek:a@b.c?secret=AAAA');
    expect(buildQrPath('otpauth://totp/Ornek:a@b.c?secret=AAAA')).toEqual(a);
    expect(buildQrPath('otpauth://totp/Ornek:a@b.c?secret=BBBB').path).not.toEqual(a.path);
    expect(a.size).toBeGreaterThanOrEqual(21 + 8); // en küçük QR (21 modül) + 4'er modül sessiz bölge
  });

  it('erişilebilir SVG olarak çizilir; görsel/dış adres ve script içermez', () => {
    const { container } = render(<QrCode value="otpauth://totp/x?secret=AAAA" label="Örnek QR" />);
    const svg = screen.getByRole('img', { name: 'Örnek QR' });
    expect(svg.tagName.toLowerCase()).toBe('svg');
    expect(container.querySelector('img, image, script, foreignObject, a')).toBeNull();
    expect(container.innerHTML).not.toMatch(/https?:/);
    expect(svg.getAttribute('viewBox')).toMatch(/^0 0 \d+ \d+$/);
  });
});
