"""OpenMontage'ın wan_video aracını doğrudan çağırarak tek klip üretir.

Tam prodüksiyon (senaryo, seslendirme, müzik, altyazı, kurgu) için OpenMontage
klasöründe Claude Code'u açıp ajana konuşarak yaptırın. Bu script ise kurulumun
çalıştığını doğrulamak ve tek tek sahne klibi almak için.

Örnekler (OpenMontage venv'i ile çalıştırın):
    python wan_openmontage.py --prompt "..." --dry-run          # GPU'ya dokunmadan süre tahmini
    python wan_openmontage.py --prompt "..." --seconds 5
    python wan_openmontage.py --prompt "..." --seconds 15 \
        --shot "ürün yakın plan" --shot "ürün döner" --shot "logo belirir"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

STUDIO_DIR = Path(os.environ.get("STUDIO_DIR", Path.home() / "hyt-video-studio"))
OM_DIR = Path(os.environ.get("OPENMONTAGE_DIR", STUDIO_DIR / "OpenMontage"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Wan2.1 klibi (OpenMontage wan_video üzerinden)")
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--seconds", type=float, default=5.0, help="5 sn üstü otomatik parçalı üretilir")
    parser.add_argument("--shot", action="append", default=[], help="Uzun klipte parça başına prompt (sıralı)")
    parser.add_argument("--model", default=os.environ.get("VIDEO_GEN_LOCAL_MODEL") or "wan2.1-1.3b")
    parser.add_argument("--width", type=int)
    parser.add_argument("--height", type=int)
    parser.add_argument("--steps", type=int, help="Az adım = hızlı taslak (örn. 20), varsayılan 50")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", help="Çıktı .mp4 yolu (varsayılan: OpenMontage/library/wan/)")
    parser.add_argument("--dry-run", action="store_true", help="Sadece plan ve süre tahmini")
    args = parser.parse_args()

    if not (OM_DIR / "tools" / "video" / "wan_video.py").exists():
        print(f"OpenMontage bulunamadı: {OM_DIR}. Önce setup.sh çalıştırın veya OPENMONTAGE_DIR verin.")
        return 1
    sys.path.insert(0, str(OM_DIR))
    os.chdir(OM_DIR)  # .env ve göreli yollar OpenMontage köküne göre çözülür

    from tools.video.wan_video import WanVideo  # noqa: E402  (OpenMontage .env'i burada yüklenir)

    out = Path(args.out) if args.out else OM_DIR / "library" / "wan" / f"wan_{args.seed}.mp4"
    inputs = {
        "prompt": args.prompt,
        "operation": "text_to_video",
        "model_variant": args.model,
        "duration_seconds": args.seconds,
        "seed": args.seed,
        "output_path": str(out),
    }
    if args.shot:
        inputs["segment_prompts"] = args.shot
    for key, value in (("width", args.width), ("height", args.height), ("num_inference_steps", args.steps)):
        if value:
            inputs[key] = value

    tool = WanVideo()
    plan = tool._plan(inputs)
    print(json.dumps({
        "model": plan["meta"]["name"],
        "hf_id": plan["meta"]["hf_id"],
        "boyut": f'{plan["width"]}x{plan["height"]}',
        "fps": plan["fps"],
        "kare": plan["total_frames"],
        "parca": plan["segments"],
        "adim": plan["steps"],
        "hassasiyet": plan["precision"],
        "offload": plan["offload_mode"],
        "tahmini_sure_dk": round(tool.estimate_runtime(inputs) / 60, 1),
        "durum": tool.get_status().value,
    }, ensure_ascii=False, indent=2))
    print("Not: süre tahmini 12 GB'lık bir dizüstü GPU'da ölçülmüş; kartınıza göre değişir.")

    if args.dry_run:
        return 0

    result = tool.execute(inputs)
    if not result.success:
        print("Hata:", result.error)
        return 1
    print("Klip hazır:", result.data.get("output"), f"({result.duration_seconds} sn)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
