import { CSRF_HEADER_NAME, readCsrfToken } from '@/lib/api/csrf';

// Tarayıcı her zaman aynı kökene gider; Next.js rewrites /api/v1 isteklerini API_BASE_URL'e
// yönlendirir. Böylece çerezler aynı kökende kalır ve CORS gerekmez.
export const API_PREFIX = '/api/v1';

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

/** RFC 9457 problem yanıtından yalnız güvenle gösterilebilen alanlar */
export interface ApiProblem {
  status: number;
  /** Makine tarafından okunur hata kodu (varsa), ör. "two_factor_required" */
  code?: string;
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;

  constructor(problem: ApiProblem) {
    super(`API hatası (${problem.status})`);
    this.name = 'ApiError';
    this.status = problem.status;
    this.code = problem.code;
  }
}

export class NetworkError extends Error {
  constructor() {
    super('Ağ hatası');
    this.name = 'NetworkError';
  }
}

export interface ApiRequestInit {
  method?: 'GET' | 'POST' | 'PUT' | 'PATCH' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
}

async function readProblem(response: Response): Promise<ApiProblem> {
  let code: string | undefined;
  try {
    const data: unknown = await response.json();
    if (data && typeof data === 'object' && 'code' in data && typeof data.code === 'string') {
      code = data.code;
    }
  } catch {
    // Gövde yoksa veya JSON değilse yalnız durum kodu kullanılır.
  }
  return { status: response.status, code };
}

/**
 * /api/v1 altına istek atar. Güvenli olmayan yöntemlerde csrf_token çerezini
 * X-CSRF-Token başlığına koyar. Sunucunun hata ayrıntısı arayüze taşınmaz:
 * yalnız durum kodu ve makine kodu okunur, mesajı arayüz Türkçe olarak üretir.
 */
export async function apiFetch<T = unknown>(path: string, init: ApiRequestInit = {}): Promise<T> {
  const method = init.method ?? 'GET';
  const headers = new Headers({ Accept: 'application/json' });

  if (init.body !== undefined) headers.set('Content-Type', 'application/json');
  if (!SAFE_METHODS.has(method)) {
    const token = readCsrfToken();
    if (token) headers.set(CSRF_HEADER_NAME, token);
  }

  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}${path}`, {
      method,
      headers,
      body: init.body === undefined ? undefined : JSON.stringify(init.body),
      credentials: 'same-origin',
      signal: init.signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new NetworkError();
  }

  if (!response.ok) throw new ApiError(await readProblem(response));
  if (response.status === 204) return undefined as T;

  try {
    return (await response.json()) as T;
  } catch {
    return undefined as T;
  }
}

/** Hata nesnesini kullanıcıya gösterilecek Türkçe cümleye çevirir. */
export function describeApiError(error: unknown, fallback: string): string {
  if (error instanceof NetworkError) {
    return 'Sunucuya ulaşılamadı. İnternet bağlantınızı kontrol edip tekrar deneyin.';
  }
  if (error instanceof ApiError) {
    if (error.status === 429) {
      return 'Çok fazla deneme yaptınız. Birkaç dakika sonra tekrar deneyin.';
    }
    if (error.status === 403) {
      return 'İstek doğrulanamadı. Sayfayı yenileyip tekrar deneyin.';
    }
    if (error.status >= 500) {
      return 'Bir sorun oluştu, biz de görüyoruz. Lütfen biraz sonra tekrar deneyin.';
    }
  }
  return fallback;
}
