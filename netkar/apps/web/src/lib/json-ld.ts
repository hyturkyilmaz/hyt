// JSON-LD betiğine güvenle gömülecek metni üretir. Girdi yalnız koddaki sabit nesnelerdir
// (kullanıcı girdisi değil); yine de </script> kaçışı ve satır ayırıcıları etkisizleştirilir.
export function serializeJsonLd(data: Record<string, unknown>): string {
  return JSON.stringify(data)
    .replace(/</g, '\\u003c')
    .replace(/>/g, '\\u003e')
    .replace(/&/g, '\\u0026')
    .replace(/\u2028/g, '\\u2028')
    .replace(/\u2029/g, '\\u2029');
}
