import type { ReactNode } from 'react';

export function PageHeader({
  title,
  description,
  children,
}: {
  title: string;
  description?: string;
  children?: ReactNode;
}) {
  return (
    <header className="flex flex-col gap-1">
      <h1 className="text-3xl font-bold">{title}</h1>
      {description ? <p className="text-base text-muted-foreground">{description}</p> : null}
      {children}
    </header>
  );
}
