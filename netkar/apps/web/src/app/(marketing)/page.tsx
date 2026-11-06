import { Package, ReceiptText, ShieldCheck } from 'lucide-react';
import Link from 'next/link';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { ProfitValue } from '@/components/profit-value';
import { brand } from '@/config/brand';

// Yalnız arayüzü göstermek için uydurma örnek veri; sayfada "örnek veri" etiketiyle işaretlidir.
const SAMPLE_PRODUCTS = [
  { name: 'Pamuklu nevresim takımı', profit: '1842.30' },
  { name: 'Bambu kesme tahtası', profit: '96.75' },
  { name: 'Seramik kupa, 6 lı set', profit: '-212.40' },
] as const;

const POINTS = [
  {
    Icon: Package,
    title: 'Ürün bazında net kâr',
    text: 'Komisyon, komisyon KDV’si, kargo, iade ve reklam düşüldükten sonra her ürünün size ne bıraktığını görün.',
  },
  {
    Icon: ReceiptText,
    title: 'Sipariş anında tahmin, ekstre gelince kesin',
    text: 'Tahmini kâr siparişle birlikte görünür. Hakediş ekstresi geldikçe rakamlar kesinleşir.',
  },
  {
    Icon: ShieldCheck,
    title: 'Yalnız okuma bağlantısı',
    text: 'Mağazanızdaki verileri okuruz, değişiklik yapmayız. Bağlantıyı istediğiniz an kesebilirsiniz.',
  },
] as const;

export default function HomePage() {
  return (
    <>
      <section className="mx-auto grid max-w-content gap-10 px-gutter py-10 sm:py-14 lg:grid-cols-2 lg:items-center lg:gap-16 lg:px-8 lg:py-20">
        <div className="flex flex-col items-start gap-5">
          <Badge variant="info">Trendyol satıcıları için</Badge>
          <h1 className="text-4xl font-bold sm:text-5xl">{brand.tagline}</h1>
          <p className="max-w-xl text-lg text-muted-foreground">
            Trendyol mağazanızı salt okuma bağlantısıyla bağlayın. Her ürünün komisyon, KDV, kargo,
            iade ve reklam sonrası net kârını, hakediş ekstrenizle eşleşmiş olarak görün.
          </p>
          <div className="flex flex-col items-start gap-3 sm:flex-row sm:items-center">
            <Button asChild size="default">
              <Link href="#bekleme-listesi">Bekleme listesine katıl</Link>
            </Button>
            <Button asChild variant="ghost">
              <Link href="/giris">Hesabım var, giriş yap</Link>
            </Button>
          </div>
          <p className="text-sm text-muted-foreground">
            Bağlantıyı istediğiniz an kesersiniz. Kart bilgisi istemiyoruz.
          </p>
        </div>

        <Card aria-labelledby="ornek-baslik">
          <CardHeader>
            <div className="flex items-center justify-between gap-3">
              <CardTitle id="ornek-baslik" className="text-lg">
                Bu ayın ürünleri
              </CardTitle>
              <Badge variant="warning">Örnek veri</Badge>
            </div>
            <CardDescription>Net kâr, tüm kesintilerden sonra.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="divide-y divide-border">
              {SAMPLE_PRODUCTS.map((product) => (
                <li key={product.name} className="flex items-center justify-between gap-4 py-3">
                  <span className="text-base">{product.name}</span>
                  <ProfitValue value={product.profit} />
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </section>

      <section aria-labelledby="neler-baslik" className="border-t border-border bg-surface">
        <div className="mx-auto max-w-content px-gutter py-12 lg:px-8 lg:py-16">
          <h2 id="neler-baslik" className="text-2xl font-bold sm:text-3xl">
            Satış arttı ama hesaba yatan aynı mı kaldı?
          </h2>
          <ul className="mt-8 grid gap-6 md:grid-cols-3">
            {POINTS.map(({ Icon, title, text }) => (
              <li key={title} className="flex flex-col gap-3">
                <span
                  aria-hidden="true"
                  className="flex size-11 items-center justify-center rounded-md bg-info-soft text-primary"
                >
                  <Icon className="size-6" />
                </span>
                <h3 className="text-lg font-semibold">{title}</h3>
                <p className="text-base text-muted-foreground">{text}</p>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section
        id="bekleme-listesi"
        aria-labelledby="bekleme-baslik"
        className="mx-auto max-w-content scroll-mt-6 px-gutter py-12 lg:px-8 lg:py-16"
      >
        <h2 id="bekleme-baslik" className="text-2xl font-bold sm:text-3xl">
          Bekleme listesi yakında açılıyor
        </h2>
        <p className="mt-3 max-w-xl text-base text-muted-foreground">
          {brand.name} henüz herkese açık değil. Kayıt formu hazır olduğunda buradan
          katılabileceksiniz.
        </p>
      </section>
    </>
  );
}
