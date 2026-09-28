#!/usr/bin/env bash
# Resmi Wan2.1 generate.py ile tek klip üretir (setup.sh --native + download_models.sh --native gerekir).
#   bash wan_native.sh "prompt" [cikti.mp4] [832*480]
# Üretilen klip OpenMontage projesine elle eklenebilir: OpenMontage/library/ altına kopyalayıp
# ajana "library/wan/... klibini kullan" demeniz yeterli.
set -euo pipefail
STUDIO_DIR="${STUDIO_DIR:-$HOME/hyt-video-studio}"
PROMPT="${1:?Kullanım: wan_native.sh \"prompt\" [cikti.mp4] [832*480]}"
OUT="${2:-$STUDIO_DIR/OpenMontage/library/wan/wan_$(date +%Y%m%d_%H%M%S).mp4}"
SIZE="${3:-832*480}"
mkdir -p "$(dirname "$OUT")"
cd "$STUDIO_DIR/Wan2.1"

# 1.3B için Wan ekibinin önerdiği değerler: guide_scale 6, shift 8-12.
# --offload_model + --t5_cpu: 8-12 GB VRAM'li kartlarda bellek taşmasını önler.
.venv/bin/python generate.py \
  --task t2v-1.3B --size "$SIZE" --ckpt_dir ./Wan2.1-T2V-1.3B \
  --offload_model True --t5_cpu \
  --sample_shift 8 --sample_guide_scale 6 \
  --save_file "$OUT" \
  --prompt "$PROMPT"
echo "Klip: $OUT"
