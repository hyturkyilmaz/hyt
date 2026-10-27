#!/usr/bin/env bash
# Wan2.1 ağırlıklarını indirir.
#   bash download_models.sh wan2.1-1.3b            # OpenMontage (diffusers) için   ~29 GB
#   bash download_models.sh wan2.1-1.3b --native   # + resmi generate.py için       ~17.5 GB ek
#   bash download_models.sh wan2.1-14b             # 14B, çok daha büyük; 40 GB+ VRAM önerilir
# Yarıda kesilirse aynı komutu tekrar çalıştırın, kaldığı yerden devam eder.
set -euo pipefail

STUDIO_DIR="${STUDIO_DIR:-$HOME/hyt-video-studio}"
MODEL="${1:-wan2.1-1.3b}"
NATIVE=0; [[ "${2:-}" == "--native" ]] && NATIVE=1

case "$MODEL" in
  wan2.1-1.3b) DIFF_ID="Wan-AI/Wan2.1-T2V-1.3B-Diffusers"; NATIVE_ID="Wan-AI/Wan2.1-T2V-1.3B" ;;
  wan2.1-14b)  DIFF_ID="Wan-AI/Wan2.1-T2V-14B-Diffusers";  NATIVE_ID="Wan-AI/Wan2.1-T2V-14B"  ;;
  *) echo "Desteklenen: wan2.1-1.3b | wan2.1-14b"; exit 1 ;;
esac

export HF_HOME="$STUDIO_DIR/hf-cache"
PY="$STUDIO_DIR/OpenMontage/.venv/bin/python"
[[ -x "$PY" ]] || { echo "Önce setup.sh çalıştırın."; exit 1; }

dl() {  # $1=repo  $2=(opsiyonel) local-dir
  "$PY" - "$@" <<'PYEOF'
import sys
from huggingface_hub import snapshot_download
repo = sys.argv[1]
kw = {"local_dir": sys.argv[2]} if len(sys.argv) > 2 else {}
# README görselleri ve örnekler gereksiz; sadece model dosyaları
path = snapshot_download(repo, ignore_patterns=["assets/*", "examples/*", "*.md"], **kw)
print("   ->", path)
PYEOF
}

df -h "$STUDIO_DIR" | tail -1 | awk '{print "Boş disk: "$4}'
echo "==> $DIFF_ID (OpenMontage wan_video bu kopyayı HF_HOME önbelleğinden okur)"
dl "$DIFF_ID"

if (( NATIVE )); then
  echo "==> $NATIVE_ID (resmi Wan2.1 generate.py)"
  dl "$NATIVE_ID" "$STUDIO_DIR/Wan2.1/${NATIVE_ID#Wan-AI/}"
fi
echo "Tamam."
