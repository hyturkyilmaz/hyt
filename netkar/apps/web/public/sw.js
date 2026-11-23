// NetKâr servis çalışanı (ADR-0009 §7.2, D8). YALNIZ üç olay dinler: push, notificationclick, pushsubscriptionchange.
// - `fetch` dinleyicisi YOKTUR: hiçbir istek araya girmez, hiçbir yanıt önbelleğe alınmaz (docs/60 §7, ADR-0009 §12/30).
// - Başlık ve gövde yalnız push yükünden gelir; burada tutar ya da başka veri üretilmez (H3, kilit ekranı).
// - `notificationclick` YALNIZ aynı kökenli ve /panel/uyarilar önekli yolu açar; yükteki tam URL kullanılmaz.
// Not: bu dosya derlenmez ve modül değildir (importScripts yok); statik ve davranış testleri src/lib/push/sw.test.ts içindedir.
'use strict';

var PATH_PREFIX = '/panel/uyarilar';
var DEFAULT_TITLE = 'NetKâr';
var MAX_TITLE = 80;
var MAX_BODY = 160;

// Yükteki yolu doğrular: göreli, izin listeli önekte, aynı kökende. Geçersizse varsayılan yol.
function safePath(raw) {
  if (typeof raw !== 'string' || raw.length > 200) return PATH_PREFIX;
  if (/[\u0000- \u007f\\]/.test(raw) || raw.indexOf('//') !== -1 || raw.indexOf('..') !== -1) {
    return PATH_PREFIX;
  }
  if (raw !== PATH_PREFIX && raw.indexOf(PATH_PREFIX + '/') !== 0) return PATH_PREFIX;
  try {
    var url = new URL(raw, self.location.origin);
    if (url.origin !== self.location.origin || url.pathname !== raw) return PATH_PREFIX;
  } catch {
    return PATH_PREFIX;
  }
  return raw;
}

function cleanText(value, limit, fallback) {
  if (typeof value !== 'string') return fallback;
  var text = value.replace(/[\u0000-\u001f\u007f-\u009f\u2028\u2029]/g, ' ').trim();
  return text ? text.slice(0, limit) : fallback;
}

self.addEventListener('push', function (event) {
  var data = {};
  try {
    data = event.data ? event.data.json() : {};
  } catch {
    data = {};
  }
  if (!data || typeof data !== 'object') data = {};
  // Görünür bildirim zorunludur (userVisibleOnly); yük bozuksa bile genel bir başlıkla gösterilir.
  event.waitUntil(
    self.registration.showNotification(cleanText(data.title, MAX_TITLE, DEFAULT_TITLE), {
      body: cleanText(data.body, MAX_BODY, ''),
      data: { path: safePath(data.path) },
    }),
  );
});

self.addEventListener('notificationclick', function (event) {
  event.notification.close();
  var raw = event.notification.data && event.notification.data.path;
  var target = new URL(safePath(raw), self.location.origin).href;
  event.waitUntil(
    self.clients.matchAll({ type: 'window', includeUncontrolled: true }).then(function (windows) {
      for (var i = 0; i < windows.length; i += 1) {
        var client = windows[i];
        // Yalnız aynı kökenli açık sekme yeniden kullanılır; dışarıdaki bir sekmeye gidilmez.
        if (new URL(client.url).origin === self.location.origin && 'focus' in client) {
          return client.focus().then(function (focused) {
            return focused && 'navigate' in focused ? focused.navigate(target) : undefined;
          });
        }
      }
      return self.clients.openWindow(target);
    }),
  );
});

// Tarayıcı aboneliği yeniledi ya da düşürdü: eski seçeneklerle yeniden abone olunur ve sunucuya bildirilir.
// En iyi çaba: oturum yoksa (401) ya da ağ yoksa sessizce vazgeçilir; uç nokta ve anahtarlar loglanmaz.
self.addEventListener('pushsubscriptionchange', function (event) {
  event.waitUntil(resubscribe(event));
});

function toBase64Url(buffer) {
  var bytes = new Uint8Array(buffer);
  var binary = '';
  for (var i = 0; i < bytes.length; i += 1) binary += String.fromCharCode(bytes[i]);
  return btoa(binary).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '');
}

async function resubscribe(event) {
  try {
    var subscription = event.newSubscription;
    if (!subscription) {
      var options = event.oldSubscription && event.oldSubscription.options;
      var key = options && options.applicationServerKey;
      if (!key) {
        // Firefox eski seçenekleri vermeyebilir: güncel genel anahtar sunucudan alınır (oturum çerezi gider).
        var response = await fetch('/api/v1/push/vapid-public-key', { credentials: 'same-origin' });
        var info = response.ok ? await response.json() : null;
        if (!info || !info.enabled || typeof info.public_key !== 'string') return;
        key = Uint8Array.from(
          atob(info.public_key.replace(/-/g, '+').replace(/_/g, '/')),
          function (c) {
            return c.charCodeAt(0);
          },
        );
      }
      subscription = await self.registration.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: key,
      });
    }
    var p256dh = subscription.getKey('p256dh');
    var auth = subscription.getKey('auth');
    if (!p256dh || !auth) return;
    // CSRF çift gönderim: SW çerez okuyamaz; token uç noktasından alınır (çerezi de set eder).
    var csrf = await fetch('/api/v1/auth/csrf', { credentials: 'same-origin' });
    if (!csrf.ok) return;
    var token = (await csrf.json()).csrf_token;
    await fetch('/api/v1/me/push-subscriptions', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': token },
      body: JSON.stringify({
        endpoint: subscription.endpoint,
        keys: { p256dh: toBase64Url(p256dh), auth: toBase64Url(auth) },
      }),
    });
  } catch {
    // Sessiz: bir sonraki panel açılışında istemci `vapid_key_id` / abonelik farkını görüp yeniden abone olur.
  }
}
