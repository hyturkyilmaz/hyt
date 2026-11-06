// Sahte API (yalnız e2e, bileşen düzeyi testler için). Gerçek backend DEĞİLDİR.
// Next.js sunucu bileşenleri (panel layout'u) `GET /v1/me` çağırır; bu çağrı tarayıcıdan
// gelmediği için Playwright route ile yakalanamaz, bu yüzden küçük bir HTTP sunucusu gerekir.
// Sözleşme services/api ile aynı: yollar /v1/..., hatalar application/problem+json,
// oturum çerezi `__Host-nk_session`. Çerez değeri "gecersiz" ise 401, başka dolu değer geçerlidir.
import { createServer } from 'node:http';

const PORT = Number(process.env.FAKE_API_PORT ?? 9101);

const ME = {
  user_id: '00000000-0000-4000-8000-000000000001',
  email: 'ad@ornek.com',
  role: 'owner',
  totp_enabled: false,
  tenant: {
    id: '00000000-0000-4000-8000-000000000002',
    name: 'Örnek Mağaza',
    plan: 'trial',
    status: 'trialing',
    trial_ends_at: null,
    currency: 'TRY',
    locale: 'tr-TR',
  },
};

function cookies(header = '') {
  return Object.fromEntries(
    header
      .split(';')
      .map((part) => part.trim().split('='))
      .filter(([name]) => name),
  );
}

function send(res, status, body, extra = {}) {
  const isProblem = status >= 400;
  res.writeHead(status, {
    'Content-Type': isProblem ? 'application/problem+json' : 'application/json',
    'Cache-Control': 'no-store',
    ...extra,
  });
  res.end(body === undefined ? undefined : JSON.stringify(body));
}

createServer((req, res) => {
  const url = new URL(req.url ?? '/', 'http://localhost');
  if (req.method === 'GET' && url.pathname === '/v1/health') {
    return send(res, 200, { status: 'ok' });
  }
  if (req.method === 'GET' && url.pathname === '/v1/me') {
    const session = cookies(req.headers.cookie)['__Host-nk_session'];
    if (!session || session === 'gecersiz') {
      return send(res, 401, {
        type: 'urn:netkar:problem:unauthorized',
        title: 'Kimlik doğrulama gerekli',
        status: 401,
      });
    }
    return send(res, 200, ME);
  }
  if (req.method === 'GET' && url.pathname === '/v1/auth/csrf') {
    const token = 'sahte-csrf-token-0123456789abcdef0123456789';
    return send(
      res,
      200,
      { csrf_token: token },
      { 'Set-Cookie': `__Host-nk_csrf=${token}; Max-Age=3600; Path=/; SameSite=Lax; Secure` },
    );
  }
  return send(res, 404, { type: 'urn:netkar:problem:not-found', title: 'Bulunamadı', status: 404 });
}).listen(PORT, '127.0.0.1', () => {
  console.log(`sahte API hazir: http://127.0.0.1:${PORT}`);
});
