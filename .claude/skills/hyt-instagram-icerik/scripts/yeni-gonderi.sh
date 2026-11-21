#!/usr/bin/env bash
# Kullanım: bash .claude/skills/hyt-instagram-icerik/scripts/yeni-gonderi.sh 2026-10-15 amazon-claude ecom
# sütun: seo | ads | ecom | ai  → vurgu rengini ayarlar
set -euo pipefail
TARIH=$1; SLUG=$2; SUTUN=${3:-ai}
KOK=$(git rev-parse --show-toplevel)
HEDEF="$KOK/icerik/gonderiler/$TARIH-$SLUG"
[ -e "$HEDEF" ] && { echo "Zaten var: $HEDEF (üzerine yazılmaz)"; exit 1; }
mkdir -p "$HEDEF/medya"
sed "s/--accent: var(--ecom);/--accent: var(--$SUTUN);/" \
  "$KOK/.claude/skills/hyt-instagram-icerik/sablonlar/carousel-7.html" > "$HEDEF/slaytlar.html"
cat > "$HEDEF/aciklama.md" <<MD
# $TARIH — $SLUG

| Alan | Değer |
|---|---|
| Sütun | $SUTUN |
| Yayın | $TARIH 20:50 TRT |
| Anahtar kelime | |
| Lead magnet | |

## Açıklama metni

\`\`\`
\`\`\`

## Üretim notu
- Yazım hatası: (kelime → doğrusu, paragraf)
- Doğrulama: (kaynak 1, kaynak 2)

## Kaynakça
MD
cat > "$HEDEF/senaryo.json" <<JS
{ "id": "$TARIH-$SLUG", "dil": "tr", "bolumler": [
  { "id": "01", "slayt": "slayt-01", "tts": "", "altyazi": "" }
] }
JS
echo "$HEDEF"
