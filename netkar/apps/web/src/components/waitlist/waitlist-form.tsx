'use client';

import { CheckCircle2, Loader2 } from 'lucide-react';
import Link from 'next/link';
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';

import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { ORDER_RANGES, STORE_CATEGORIES } from '@/lib/waitlist/options';
import {
  validateWaitlistForm,
  type WaitlistField,
  type WaitlistFormValues,
} from '@/lib/waitlist/validate';

import { TurnstileSlot } from './turnstile-slot';

type Status = 'idle' | 'submitting' | 'success';

const SELECT_CLASS =
  'min-h-touch w-full rounded-md border border-input-border bg-surface px-3 py-2 text-base text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background aria-[invalid=true]:border-2 aria-[invalid=true]:border-loss';

function FieldError({ id, message }: { id: string; message: string | undefined }) {
  if (!message) return null;
  return (
    <p id={id} className="flex items-start gap-1 text-sm font-medium text-loss">
      <span aria-hidden="true">!</span>
      <span>
        <span className="sr-only">Hata: </span>
        {message}
      </span>
    </p>
  );
}

function serverMessage(status: number): string {
  if (status === 422) return 'Bilgilerinizi kontrol edip yeniden deneyin.';
  if (status === 429) return 'Kısa sürede çok fazla deneme yapıldı. Biraz sonra yeniden deneyin.';
  if (status === 403) return 'İstek doğrulanamadı. Sayfayı yenileyip yeniden deneyin.';
  return 'Kaydınız şu an alınamıyor. Lütfen biraz sonra yeniden deneyin.';
}

export function WaitlistForm() {
  const uid = useId();
  const ids = {
    email: `${uid}-email`,
    category: `${uid}-kategori`,
    orders: `${uid}-siparis`,
    consent: `${uid}-onay`,
  };
  const [values, setValues] = useState<WaitlistFormValues>({
    email: '',
    storeCategory: '',
    monthlyOrders: '',
    // Ticari ileti onayı varsayılan olarak işaretsizdir.
    marketingConsent: false,
  });
  const [honeypot, setHoneypot] = useState('');
  const [turnstileToken, setTurnstileToken] = useState<string | undefined>(undefined);
  const [errors, setErrors] = useState<Partial<Record<WaitlistField, string>>>({});
  const [failure, setFailure] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>('idle');
  const successRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (status === 'success') successRef.current?.focus();
  }, [status]);

  function update<K extends keyof WaitlistFormValues>(key: K, value: WaitlistFormValues[K]) {
    setValues((current) => ({ ...current, [key]: value }));
    // Düzeltilen alanın hatasını hemen kaldır
    if (key === 'email' || key === 'monthlyOrders') {
      setErrors((current) => ({ ...current, [key]: undefined }));
    }
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (status === 'submitting') return;
    const found = validateWaitlistForm(values);
    setErrors(found);
    setFailure(null);
    if (Object.keys(found).length > 0) {
      // İlk hatalı alana odaklan (WCAG 3.3.1)
      document.getElementById(found.email ? ids.email : ids.orders)?.focus();
      return;
    }
    setStatus('submitting');
    try {
      const response = await fetch('/api/bekleme-listesi', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          email: values.email.trim(),
          ...(values.storeCategory ? { storeCategory: values.storeCategory } : {}),
          monthlyOrders: values.monthlyOrders,
          marketingConsent: values.marketingConsent,
          website: honeypot,
          ...(turnstileToken ? { turnstileToken } : {}),
        }),
      });
      if (response.ok) {
        setStatus('success');
        return;
      }
      setFailure(serverMessage(response.status));
    } catch {
      setFailure('Bağlantı kurulamadı. İnternet bağlantınızı kontrol edip yeniden deneyin.');
    }
    setStatus('idle');
  }

  if (status === 'success') {
    return (
      <div
        ref={successRef}
        tabIndex={-1}
        role="status"
        className="flex items-start gap-3 rounded-lg border border-border bg-profit-soft p-5 focus:outline-none"
      >
        <CheckCircle2 className="mt-0.5 size-6 shrink-0 text-profit" aria-hidden="true" />
        <div>
          <p className="text-lg font-semibold">Kaydınız alındı.</p>
          <p className="mt-1 text-base">
            Uygulama açılışa hazır olduğunda bu adrese haber vereceğiz. Bu arada ücretsiz{' '}
            <Link href="/araclar" className="underline underline-offset-4">
              hesaplayıcıları
            </Link>{' '}
            kullanabilirsiniz.
          </p>
        </div>
      </div>
    );
  }

  return (
    <form
      onSubmit={onSubmit}
      noValidate
      className="flex flex-col gap-4"
      aria-label="Bekleme listesi formu"
    >
      <div className="flex flex-col gap-1.5">
        <Label htmlFor={ids.email}>E-posta</Label>
        <Input
          id={ids.email}
          name="email"
          type="email"
          autoComplete="email"
          inputMode="email"
          value={values.email}
          onChange={(event) => update('email', event.target.value)}
          aria-invalid={errors.email ? true : undefined}
          aria-describedby={errors.email ? `${ids.email}-hata` : undefined}
        />
        <FieldError id={`${ids.email}-hata`} message={errors.email} />
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={ids.category}>
          Mağaza kategoriniz{' '}
          <span className="font-normal text-muted-foreground">(isteğe bağlı)</span>
        </Label>
        <select
          id={ids.category}
          name="storeCategory"
          value={values.storeCategory}
          onChange={(event) => update('storeCategory', event.target.value)}
          className={SELECT_CLASS}
        >
          <option value="">Belirtmek istemiyorum</option>
          {STORE_CATEGORIES.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
      </div>

      <div className="flex flex-col gap-1.5">
        <Label htmlFor={ids.orders}>Aylık sipariş sayınız</Label>
        <select
          id={ids.orders}
          name="monthlyOrders"
          value={values.monthlyOrders}
          onChange={(event) => update('monthlyOrders', event.target.value)}
          aria-invalid={errors.monthlyOrders ? true : undefined}
          aria-describedby={errors.monthlyOrders ? `${ids.orders}-hata` : undefined}
          className={SELECT_CLASS}
        >
          <option value="">Seçin</option>
          {ORDER_RANGES.map((item) => (
            <option key={item.id} value={item.id}>
              {item.label}
            </option>
          ))}
        </select>
        <FieldError id={`${ids.orders}-hata`} message={errors.monthlyOrders} />
      </div>

      {/* Bot tuzağı: gerçek kullanıcı görmez (display: none), botlar doldurur */}
      <div hidden>
        <label htmlFor={`${uid}-website`}>Web sitesi</label>
        <input
          id={`${uid}-website`}
          name="website"
          type="text"
          tabIndex={-1}
          autoComplete="off"
          value={honeypot}
          onChange={(event) => setHoneypot(event.target.value)}
        />
      </div>

      <TurnstileSlot onToken={setTurnstileToken} />

      <div className="flex items-start gap-3">
        <input
          id={ids.consent}
          name="marketingConsent"
          type="checkbox"
          checked={values.marketingConsent}
          onChange={(event) => update('marketingConsent', event.target.checked)}
          className="mt-0.5 size-6 shrink-0 accent-primary"
        />
        <Label htmlFor={ids.consent} className="text-base font-normal">
          Lansman, fiyat ve ürün duyuruları için ticari elektronik ileti almak istiyorum. Bu onay
          isteğe bağlıdır; vermezseniz yalnız açılış bildirimi için e-posta kullanırız ve
          istediğiniz an geri alabilirsiniz.
        </Label>
      </div>

      <p className="text-sm text-muted-foreground">
        Kişisel verileriniz{' '}
        <Link href="/kvkk-aydinlatma-metni" className="underline underline-offset-4">
          KVKK aydınlatma metninde
        </Link>{' '}
        anlatıldığı şekilde işlenir. Aydınlatma metni taslaktır ve hukuki inceleme bekliyor.
      </p>

      {failure ? (
        <p role="alert" className="flex items-start gap-1 text-base font-medium text-loss">
          <span aria-hidden="true">!</span>
          <span>
            <span className="sr-only">Hata: </span>
            {failure}
          </span>
        </p>
      ) : null}

      <div>
        <Button type="submit" disabled={status === 'submitting'}>
          {status === 'submitting' ? (
            <>
              <Loader2 className="animate-spin" aria-hidden="true" />
              Gönderiliyor
            </>
          ) : (
            'Bekleme listesine katıl'
          )}
        </Button>
      </div>
    </form>
  );
}
