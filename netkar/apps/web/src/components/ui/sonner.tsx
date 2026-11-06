'use client';

import { Toaster as Sonner } from 'sonner';

// Bildirimler tema değişkenlerinden renk alır. Sonner kendi aria-live bölgesini yönetir.
function Toaster() {
  return (
    <Sonner
      position="top-center"
      closeButton
      toastOptions={{
        style: {
          background: 'var(--surface)',
          color: 'var(--foreground)',
          border: '1px solid var(--border)',
          fontFamily: 'var(--font-sans), system-ui, sans-serif',
        },
      }}
    />
  );
}

export { Toaster };
