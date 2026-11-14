'use client';

import { useCallback, useState } from 'react';

/** Metin alanlarının değerlerini tutar; kullanıcı bir alanı değiştirince `dirty` olur. */
export function useFormValues<T extends { [K in keyof T]: string }>(initial: T) {
  const [values, setValues] = useState<T>(initial);
  const [dirty, setDirty] = useState(false);
  const set = useCallback(<K extends keyof T>(key: K, value: string) => {
    setValues((current) => ({ ...current, [key]: value }));
    setDirty(true);
  }, []);
  return { values, set, dirty };
}
