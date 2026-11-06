import { CSRF_HEADER_NAME, readCsrfToken } from '@/lib/api/csrf';

// Tarayıcı her zaman aynı kökene gider; Next.js rewrites /api/v1/* isteklerini backend'in
// /v1/* yoluna (API_BASE_URL) yönlendirir. Böylece çerezler aynı kökende kalır ve CORS gerekmez.
export const API_PREFIX = '/api/v1';

// Backend hata türleri `urn:netkar:problem:<slug>` biçimindedir (services/api/app/core/errors.py).
const PROBLEM_TYPE_PREFIX = 'urn:netkar:problem:';

const SAFE_METHODS = new Set(['GET', 'HEAD', 'OPTIONS']);

/** Doğrulama hatasında alan yolu ve kural kodu (backend girdi değerini yansıtmaz) */
export interface ApiFieldError {
  field: string;
  code: string;
}

/** RFC 9457 problem yanıtından yalnız güvenle gösterilebilen alanlar */
export interface ApiProblem {
  status: number;
  /** `type` alanındaki slug, ör. "invalid-credentials", "weak-password", "csrf-failed" */
  code?: string;
  /** 422 "validation-error" yanıtındaki alan hataları */
  errors?: ApiFieldError[];
}

export class ApiError extends Error {
  readonly status: number;
  readonly code?: string;
  readonly errors?: ApiFieldError[];

  constructor(problem: ApiProblem) {
    super(`API hatası (${problem.status})`);
    this.name = 'ApiError';
    this.status = problem.status;
    this.code = problem.code;
    this.errors = problem.errors;
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

function parseFieldErrors(value: unknown): ApiFieldError[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const result: ApiFieldError[] = [];
  for (const item of value) {
    if (
      item &&
      typeof item === 'object' &&
      'field' in item &&
      'code' in item &&
      typeof item.field === 'string' &&
      typeof item.code === 'string'
    ) {
      result.push({ field: item.field, code: item.code });
    }
  }
  return result;
}

async function readProblem(response: Response): Promise<ApiProblem> {
  let code: string | undefined;
  let errors: ApiFieldError[] | undefined;
  try {
    const data: unknown = await response.json();
    if (data && typeof data === 'object') {
      if (
        'type' in data &&
        typeof data.type === 'string' &&
        data.type.startsWith(PROBLEM_TYPE_PREFIX)
      ) {
        code = data.type.slice(PROBLEM_TYPE_PREFIX.length) || undefined;
      }
      if ('errors' in data) errors = parseFieldErrors(data.errors);
    }
  } catch {
    // Gövde yoksa veya JSON değilse yalnız durum kodu kullanılır.
  }
  return { status: response.status, code, errors };
}

/**
 * CSRF token'ını döndürür. Çerez okunabiliyorsa onu kullanır; yoksa `GET /v1/auth/csrf` çağırır
 * (backend çerezi set eder ve değeri gövdede döndürür; geçerli çerez varsa onu korur).
 */
export async function ensureCsrfToken(signal?: AbortSignal): Promise<string> {
  const existing = readCsrfToken();
  if (existing) return existing;
  let response: Response;
  try {
    response = await fetch(`${API_PREFIX}/auth/csrf`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === 'AbortError') throw error;
    throw new NetworkError();
  }
  if (!response.ok) throw new ApiError(await readProblem(response));
  let token: unknown;
  try {
    const data: unknown = await response.json();
    token = data && typeof data === 'object' && 'csrf_token' in data ? data.csrf_token : undefined;
  } catch {
    token = undefined;
  }
  if (typeof token !== 'string' || token.length === 0) {
    throw new ApiError({ status: response.status });
  }
  return token;
}

async function send(path: string, init: ApiRequestInit): Promise<Response> {
  const method = init.method ?? 'GET';
  const headers = new Headers({ Accept: 'application/json' });

  if (init.body !== undefined) headers.set('Content-Type', 'application/json');
  if (!SAFE_METHODS.has(method)) {
    headers.set(CSRF_HEADER_NAME, await ensureCsrfToken(init.signal));
  }

  try {
    return await fetch(`${API_PREFIX}${path}`, {
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
}

/**
 * /api/v1 altına istek atar. Güvenli olmayan yöntemlerde `__Host-nk_csrf` çerezini (yoksa
 * `GET /auth/csrf` ile alınan değeri) X-CSRF-Token başlığına koyar. Sunucunun hata ayrıntısı arayüze taşınmaz: yalnız
 * durum kodu, `type` slug'ı ve alan hataları okunur; mesajı arayüz Türkçe olarak üretir.
 */
export async function apiFetch<T = unknown>(path: string, init: ApiRequestInit = {}): Promise<T> {
  const response = await send(path, init);

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
