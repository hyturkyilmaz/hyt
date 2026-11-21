import { appendFile, mkdir, readFile } from 'node:fs/promises';
import { dirname } from 'node:path';

import type { WaitlistEntry } from './schema';

/**
 * Bekleme listesi kayıt arayüzü. Gerçek kayıt uç noktası (API + veritabanı) sonraki turda gelir;
 * o zaman yalnız bu arayüzün yeni bir uygulaması yazılır, route handler değişmez.
 * Uygulamalar e-postayı yalnız küçük harfli, tekrarsız saklar ve IP gibi ek veri istemez.
 */
export interface WaitlistSink {
  add(entry: WaitlistEntry): Promise<'created' | 'duplicate'>;
}

/** Bellekte tutan uygulama (geliştirme ve test). Süreç kapanınca kayıtlar kaybolur. */
export class MemoryWaitlistSink implements WaitlistSink {
  private readonly items = new Map<string, WaitlistEntry>();

  async add(entry: WaitlistEntry): Promise<'created' | 'duplicate'> {
    if (this.items.has(entry.email)) return 'duplicate';
    this.items.set(entry.email, entry);
    return 'created';
  }

  entries(): WaitlistEntry[] {
    return [...this.items.values()];
  }

  clear(): void {
    this.items.clear();
  }
}

/** JSON Lines dosyasına ekleyen uygulama (yalnız geliştirme). Dosya yolu sunucu ortamından gelir. */
export class FileWaitlistSink implements WaitlistSink {
  private known: Set<string> | null = null;

  constructor(private readonly filePath: string) {}

  private async load(): Promise<Set<string>> {
    if (this.known) return this.known;
    const emails = new Set<string>();
    try {
      // eslint-disable-next-line security/detect-non-literal-fs-filename -- yol ortam değişkeninden, kullanıcı girdisinden değil
      const text = await readFile(this.filePath, 'utf8');
      for (const line of text.split('\n')) {
        if (!line.trim()) continue;
        try {
          const parsed = JSON.parse(line) as { email?: unknown };
          if (typeof parsed.email === 'string') emails.add(parsed.email);
        } catch {
          // Bozuk satır yok sayılır
        }
      }
    } catch {
      // Dosya henüz yok
    }
    this.known = emails;
    return emails;
  }

  async add(entry: WaitlistEntry): Promise<'created' | 'duplicate'> {
    const known = await this.load();
    if (known.has(entry.email)) return 'duplicate';
    // eslint-disable-next-line security/detect-non-literal-fs-filename -- yol ortam değişkeninden
    await mkdir(dirname(this.filePath), { recursive: true });
    // eslint-disable-next-line security/detect-non-literal-fs-filename -- yol ortam değişkeninden
    await appendFile(this.filePath, `${JSON.stringify(entry)}\n`, 'utf8');
    known.add(entry.email);
    return 'created';
  }
}

export type SinkKind = 'memory' | 'file' | 'none';

interface SinkEnv {
  NODE_ENV: string;
  WAITLIST_SINK?: SinkKind | undefined;
  WAITLIST_FILE?: string | undefined;
}

const globalForSink = globalThis as unknown as { __waitlistMemorySink?: MemoryWaitlistSink };

/**
 * Ortama göre kayıt hedefini seçer. Varsayılan: geliştirme ve testte bellek; üretimde hedef
 * yoktur (null) ve uç nokta 503 döner, yani gerçek bir hedef bağlanmadan kayıt sessizce kaybolmaz.
 */
export function resolveSink(env: SinkEnv): WaitlistSink | null {
  const kind: SinkKind = env.WAITLIST_SINK ?? (env.NODE_ENV === 'production' ? 'none' : 'memory');
  if (kind === 'none') return null;
  if (kind === 'file') return new FileWaitlistSink(env.WAITLIST_FILE ?? '.data/waitlist.jsonl');
  globalForSink.__waitlistMemorySink ??= new MemoryWaitlistSink();
  return globalForSink.__waitlistMemorySink;
}
