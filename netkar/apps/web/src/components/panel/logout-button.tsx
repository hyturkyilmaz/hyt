'use client';

import { Loader2, LogOut } from 'lucide-react';
import { useRouter } from 'next/navigation';
import { useState } from 'react';
import { toast } from 'sonner';

import { Button } from '@/components/ui/button';
import { describeApiError } from '@/lib/api/client';
import { authApi } from '@/lib/api/endpoints';
import { cn } from '@/lib/utils';

/**
 * Çıkış: POST /v1/auth/logout (CSRF başlığıyla; çerez ve token yönetimi apiFetch'te).
 * Backend oturumu iptal eder ve çerezleri siler (204, idempotent). Ardından girişe gidilir.
 */
export function LogoutButton({
  variant = 'full',
  className,
}: {
  /** "icon": yalnız simge (mobil üst çubuk), "full": simge + metin (kenar çubuğu) */
  variant?: 'icon' | 'full';
  className?: string;
}) {
  const router = useRouter();
  const [pending, setPending] = useState(false);

  async function onClick() {
    setPending(true);
    try {
      await authApi.logout();
      router.replace('/giris');
      router.refresh();
    } catch (error) {
      toast.error(describeApiError(error, 'Çıkış yapılamadı. Lütfen tekrar deneyin.'));
      setPending(false);
    }
  }

  const Icon = pending ? Loader2 : LogOut;
  return (
    <Button
      variant={variant === 'icon' ? 'ghost' : 'secondary'}
      size={variant === 'icon' ? 'icon' : 'default'}
      onClick={onClick}
      disabled={pending}
      aria-label={variant === 'icon' ? 'Çıkış yap' : undefined}
      className={cn(variant === 'full' && 'w-full', className)}
    >
      <Icon className={pending ? 'animate-spin' : undefined} aria-hidden="true" />
      {variant === 'full' ? 'Çıkış yap' : null}
    </Button>
  );
}
