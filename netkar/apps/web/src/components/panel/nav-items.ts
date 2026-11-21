import { Bell, House, Package, Receipt, Settings, type LucideIcon } from 'lucide-react';

export interface NavItem {
  href: string;
  label: string;
  Icon: LucideIcon;
  /** Bu yollar da aynı menü öğesini etkin gösterir (ör. Ürünler altındaki maliyet ekranı) */
  alsoActiveFor?: readonly string[];
}

// Panel menüsü: tek kaynak. Hem kenar çubuğu hem alt gezinme çubuğu buradan beslenir.
export const NAV_ITEMS: readonly NavItem[] = [
  { href: '/panel', label: 'Özet', Icon: House },
  { href: '/panel/urunler', label: 'Ürünler', Icon: Package, alsoActiveFor: ['/panel/maliyetler'] },
  { href: '/panel/siparisler', label: 'Siparişler', Icon: Receipt },
  { href: '/panel/uyarilar', label: 'Uyarılar', Icon: Bell },
  { href: '/panel/ayarlar', label: 'Ayarlar', Icon: Settings },
];
