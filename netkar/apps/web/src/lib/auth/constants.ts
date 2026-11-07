// Backend (services/api/app/core/cookies.py) ile aynı çerez adları. `__Host-` öneki: Secure,
// Path=/ ve Domain yok zorunluluğu getirir; tarayıcı yalnız güvenli bağlamda (https veya
// localhost/127.0.0.1) kabul eder.
export const SESSION_COOKIE_NAME = '__Host-nk_session';
export const PENDING_COOKIE_NAME = '__Host-nk_pending';

export const LOGIN_PATH = '/giris';
export const DEFAULT_AFTER_LOGIN_PATH = '/panel';
export const NEXT_PARAM = 'sonra';

// Middleware'in istek yolunu sunucu bileşenine taşıdığı istek başlığı (giriş sonrası geri dönüş hedefi).
export const PATH_HEADER = 'x-nk-path';
