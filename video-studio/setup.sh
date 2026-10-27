#!/usr/bin/env bash
# Wan2.1 + OpenMontage kurulumu (NVIDIA GPU'lu Linux / WSL2 makine için).
#
# Kullanım:
#   bash setup.sh                 # OpenMontage + Wan2.1 (diffusers yolu), VRAM'e göre model seçer
#   bash setup.sh --native        # ek olarak resmi Wan2.1 generate.py ortamını da kurar (flash-attn derler)
#   STUDIO_DIR=/data/studio bash setup.sh
#
# Script hiçbir mevcut dosyayı silmez; klasör varsa sadece günceller.
set -euo pipefail

STUDIO_DIR="${STUDIO_DIR:-$HOME/hyt-video-studio}"
WAN_REPO="https://github.com/Wan-Video/Wan2.1.git"
OM_REPO="https://github.com/calesthio/OpenMontage.git"
# Kurulum paketinin doğrulandığı commit'ler. Yeni sürüm denemek için boş bırakın: WAN_REF= OM_REF= bash setup.sh
WAN_REF="${WAN_REF-9737cba9c1c3c4d04b33fcad41c111989865d315}"
OM_REF="${OM_REF-08e2151fa02de28a5d6a312b3d575692bf147ad7}"
NATIVE=0
[[ "${1:-}" == "--native" ]] && NATIVE=1

say()  { printf '\n==> %s\n' "$*"; }
warn() { printf '\n[uyarı] %s\n' "$*" >&2; }

# ---------------------------------------------------------------- ön koşullar
for bin in git python3 ffmpeg node npm; do
  command -v "$bin" >/dev/null || { warn "'$bin' bulunamadı. Ubuntu: sudo apt install git python3-venv ffmpeg nodejs npm"; exit 1; }
done

VRAM_GB=0
if command -v nvidia-smi >/dev/null; then
  VRAM_MB=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits | head -1 | tr -d ' ')
  VRAM_GB=$(( VRAM_MB / 1024 ))
  say "GPU: $(nvidia-smi --query-gpu=name --format=csv,noheader | head -1) (${VRAM_GB} GB VRAM)"
else
  warn "NVIDIA GPU bulunamadı. OpenMontage kurulur ama Wan yerel üretimi çalışmaz (CPU'da 5 sn video saatler sürer)."
fi

# VRAM'e göre varsayılan model (elle ezmek için: WAN_MODEL=wan2.1-14b bash setup.sh)
if [[ -z "${WAN_MODEL:-}" ]]; then
  if   (( VRAM_GB >= 40 )); then WAN_MODEL="wan2.1-14b"
  elif (( VRAM_GB >= 8  )); then WAN_MODEL="wan2.1-1.3b"
  else                           WAN_MODEL="wan2.1-1.3b"; warn "8 GB altı VRAM: 1.3B modeli bile offload ile çok yavaş olur."
  fi
fi
say "Seçilen model: $WAN_MODEL"

mkdir -p "$STUDIO_DIR"
cd "$STUDIO_DIR"

clone_or_update() {  # $1=url $2=dir $3=ref
  if [[ -d "$2/.git" ]]; then
    git -C "$2" fetch --quiet origin
  else
    git clone --quiet "$1" "$2"
  fi
  if [[ -n "$3" ]]; then git -C "$2" checkout --quiet "$3"; else git -C "$2" pull --quiet --ff-only; fi
  echo "    $2 @ $(git -C "$2" rev-parse --short HEAD)"
}

say "Depolar indiriliyor"
clone_or_update "$OM_REPO"  OpenMontage "$OM_REF"
clone_or_update "$WAN_REPO" Wan2.1      "$WAN_REF"

# ---------------------------------------------------------------- OpenMontage
say "OpenMontage bağımlılıkları (make setup + make install-gpu)"
cd "$STUDIO_DIR/OpenMontage"
make setup
make install-gpu
# 8-bit / 4-bit yükleme için (az VRAM'li kartlarda otomatik devreye girer)
.venv/bin/pip install --quiet "bitsandbytes>=0.43" "imageio[ffmpeg]" "huggingface_hub[cli]" || warn "bitsandbytes kurulamadı; sadece bf16 kullanılabilir."

say ".env ayarları"
[[ -f .env ]] || cp .env.example .env
set_env() {  # anahtar varsa değerini değiştirir, yoksa ekler; diğer satırlara dokunmaz
  if grep -qE "^#?\s*$1=" .env; then
    sed -i -E "s|^#?\s*$1=.*|$1=$2|" .env
  else
    printf '%s=%s\n' "$1" "$2" >> .env
  fi
}
set_env VIDEO_GEN_LOCAL_ENABLED true
set_env VIDEO_GEN_LOCAL_MODEL "$WAN_MODEL"
set_env HF_HOME "$STUDIO_DIR/hf-cache"
grep -E "^(VIDEO_GEN_LOCAL_ENABLED|VIDEO_GEN_LOCAL_MODEL|HF_HOME)=" .env | sed 's/^/    /'

# ---------------------------------------------------------------- resmi Wan2.1 (isteğe bağlı)
if (( NATIVE )); then
  say "Resmi Wan2.1 ortamı (ayrı venv; flash-attn derlemesi 10-40 dk sürebilir)"
  cd "$STUDIO_DIR/Wan2.1"
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip wheel packaging ninja
  .venv/bin/pip install --quiet "torch>=2.4.0" "torchvision>=0.19.0"
  grep -v '^flash_attn' requirements.txt > /tmp/wan-req-noflash.txt
  .venv/bin/pip install --quiet -r /tmp/wan-req-noflash.txt "huggingface_hub[cli]"
  # Wan2.1 kodu flash-attn'i zorunlu tutuyor (wan/modules/attention.py -> assert FLASH_ATTN_2_AVAILABLE)
  .venv/bin/pip install flash-attn --no-build-isolation || warn "flash-attn kurulamadı; resmi generate.py çalışmaz, OpenMontage yolu etkilenmez."
fi

say "Tamamlandı"
cat <<MSG
Sonraki adımlar:
  1) Modeli indir:          bash $(dirname "$(readlink -f "$0")")/download_models.sh $WAN_MODEL
  2) Test klibi üret:       $STUDIO_DIR/OpenMontage/.venv/bin/python $(dirname "$(readlink -f "$0")")/wan_openmontage.py --prompt "..."
  3) Tam prodüksiyon:       cd $STUDIO_DIR/OpenMontage && claude
                            "wan_video ile 30 saniyelik ürün tanıtım videosu yap"
MSG
