#!/usr/bin/env bash
# Tüm karuselleri (4:5) ve Google postunun dikey videosunu (9:16) yeniden üretir.
# Kullanım: bash pazarlama/sosyal-medya/_kaynak/hepsini-uret.sh
set -euo pipefail
cd "$(dirname "$0")"

node render.mjs
node render.mjs --dikey 02

cd ../02-google-kanal-onceligi
ffmpeg -y -loglevel error \
  -loop 1 -t 4.5 -i dikey/slayt-1.png -loop 1 -t 5.5 -i dikey/slayt-2.png -loop 1 -t 5.5 -i dikey/slayt-3.png \
  -loop 1 -t 6 -i dikey/slayt-4.png -loop 1 -t 5 -i dikey/slayt-5.png \
  -filter_complex "[0][1]xfade=transition=slideleft:duration=0.5:offset=4[a];[a][2]xfade=transition=slideleft:duration=0.5:offset=9[b];[b][3]xfade=transition=slideleft:duration=0.5:offset=14[c];[c][4]xfade=transition=fade:duration=0.5:offset=19.5,format=yuv420p[v]" \
  -map "[v]" -r 30 -c:v libx264 -crf 20 -movflags +faststart google-kanal-onceligi-9x16.mp4
echo "Video: $(pwd)/google-kanal-onceligi-9x16.mp4"
