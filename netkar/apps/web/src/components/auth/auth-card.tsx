import type { ReactNode } from 'react';

import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';

export function AuthCard({
  title,
  description,
  children,
  footer,
}: {
  title: string;
  description?: string;
  children: ReactNode;
  footer?: ReactNode;
}) {
  return (
    <Card>
      <CardHeader>
        <CardTitle as="h1" className="text-2xl">
          {title}
        </CardTitle>
        {description ? (
          <CardDescription className="text-base">{description}</CardDescription>
        ) : null}
      </CardHeader>
      <CardContent className="flex flex-col gap-6">
        {children}
        {footer ? <div className="text-center text-sm text-muted-foreground">{footer}</div> : null}
      </CardContent>
    </Card>
  );
}

// Sunucudan gelen genel hata: role="alert" ile hemen duyurulur, ikon + metin içerir.
export function FormError({ message }: { message: string | null }) {
  if (!message) return null;
  return (
    <p
      role="alert"
      className="flex items-start gap-2 rounded-md border border-loss bg-loss-soft p-3 text-sm font-medium text-loss"
    >
      <span aria-hidden="true" className="font-bold">
        !
      </span>
      <span>
        <span className="sr-only">Hata: </span>
        {message}
      </span>
    </p>
  );
}
