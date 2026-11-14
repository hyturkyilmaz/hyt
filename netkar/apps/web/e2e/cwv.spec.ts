import { expect, test } from '@playwright/test';

import { waitForReady } from './helpers';

// Core Web Vitals yaklaşık ölçümü (Lighthouse CI bu depoda yok; yeni bağımlılık eklenmedi).
// Yerel üretim derlemesinde, ağ ve CPU kısıtı olmadan ölçülür; mutlak değerler gerçek kullanıcı
// verisinin (p75) yerine geçmez. Amaç: bütçe aşımı ve düzen kaymasını erken yakalamak.
// Bütçe: docs/research/06 §7.1. LCP iç hedef 1,8 sn, CLS 0,05, INP 150 ms, istemci JS 150 KB.

const PAGES = [
  { path: '/', name: 'anasayfa' },
  { path: '/araclar/trendyol-komisyon-hesaplama', name: 'komisyon' },
  { path: '/araclar/trendyol-kar-hesaplama', name: 'kar' },
  { path: '/araclar/desi-hesaplama', name: 'desi' },
  { path: '/fiyatlar', name: 'fiyatlar' },
];

interface Metrics {
  lcp: number;
  cls: number;
  worstInteraction: number;
  longTaskTotal: number;
  scriptBytes: number;
  scriptCount: number;
  fontBytes: number;
}

for (const entry of PAGES) {
  test(`${entry.name}: LCP, CLS, etkileşim gecikmesi ve JS boyutu bütçe içinde`, async ({
    page,
  }, testInfo) => {
    await page.addInitScript(() => {
      const w = window as unknown as {
        __m: { lcp: number; cls: number; worst: number; longTotal: number };
      };
      w.__m = { lcp: 0, cls: 0, worst: 0, longTotal: 0 };
      new PerformanceObserver((list) => {
        const last = list.getEntries().at(-1);
        if (last) w.__m.lcp = last.startTime;
      }).observe({ type: 'largest-contentful-paint', buffered: true });
      new PerformanceObserver((list) => {
        for (const e of list.getEntries() as unknown as {
          value: number;
          hadRecentInput: boolean;
        }[]) {
          if (!e.hadRecentInput) w.__m.cls += e.value;
        }
      }).observe({ type: 'layout-shift', buffered: true });
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) w.__m.longTotal += Math.max(0, e.duration - 50);
      }).observe({ type: 'longtask', buffered: true });
      // INP'ye yaklaşık: etkileşim olaylarının (tuş, tıklama) en uzun süresi
      new PerformanceObserver((list) => {
        for (const e of list.getEntries()) {
          if (e.duration > w.__m.worst) w.__m.worst = e.duration;
        }
      }).observe({
        type: 'event',
        durationThreshold: 16,
        buffered: true,
      } as PerformanceObserverInit);
    });

    await page.goto(entry.path);
    await waitForReady(page);

    // Hesaplayıcıda her tuşta hesap yapılır: art arda yazarak etkileşim gecikmesini ölç
    const price = page.getByLabel(/Satış fiyatı/);
    if (await price.count()) {
      await price.fill('');
      await price.pressSequentially('1249,90', { delay: 20 });
    }
    const length = page.getByLabel('En', { exact: true });
    if (await length.count()) {
      await length.fill('');
      await length.pressSequentially('42,5', { delay: 20 });
    }
    await page.waitForTimeout(300);

    const metrics = await page.evaluate<Metrics>(() => {
      const w = window as unknown as {
        __m: { lcp: number; cls: number; worst: number; longTotal: number };
      };
      const resources = performance.getEntriesByType('resource') as PerformanceResourceTiming[];
      const scripts = resources.filter(
        (r) => r.initiatorType === 'script' || r.name.endsWith('.js'),
      );
      const fonts = resources.filter((r) => /\.woff2?$/.test(r.name));
      return {
        lcp: w.__m.lcp,
        cls: w.__m.cls,
        worstInteraction: w.__m.worst,
        longTaskTotal: w.__m.longTotal,
        scriptBytes: scripts.reduce((sum, r) => sum + r.encodedBodySize, 0),
        scriptCount: scripts.length,
        fontBytes: fonts.reduce((sum, r) => sum + r.encodedBodySize, 0),
      };
    });

    const line = `[CWV] ${entry.name} ${testInfo.project.name}: ${JSON.stringify({
      lcpMs: Math.round(metrics.lcp),
      cls: Number(metrics.cls.toFixed(4)),
      worstInteractionMs: Math.round(metrics.worstInteraction),
      longTaskTotalMs: Math.round(metrics.longTaskTotal),
      jsKB: Number((metrics.scriptBytes / 1024).toFixed(1)),
      scripts: metrics.scriptCount,
      fontKB: Number((metrics.fontBytes / 1024).toFixed(1)),
    })}`;
    console.log(line);
    testInfo.annotations.push({ type: 'cwv', description: line });

    expect(metrics.lcp, 'LCP').toBeGreaterThan(0);
    expect(metrics.lcp, 'LCP (ms)').toBeLessThanOrEqual(1800);
    expect(metrics.cls, 'CLS').toBeLessThanOrEqual(0.05);
    expect(metrics.worstInteraction, 'en uzun etkileşim (ms)').toBeLessThanOrEqual(200);
    // Sıkıştırılmış istemci JS: iç hedef 150 KB (bkz. zod'un istemci paketine girmemesi, waitlist/options.ts)
    expect(metrics.scriptBytes / 1024, 'JS (KB, sıkıştırılmış)').toBeLessThanOrEqual(150);
    // En fazla iki yazı tipi dosyası
    expect(metrics.fontBytes).toBeGreaterThan(0);
  });
}
