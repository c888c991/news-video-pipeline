# -*- coding: utf-8 -*-
"""通用 TTS 工作器：读 EditPlan，为指定字段逐模块合成 mp3，输出 durations.json。

与 step2_tts.py 的区别：
  - 不硬编码 plan 路径 / 输出目录 / 字段名，全部走命令行参数
  - 字段名通用化（text/mp3/dur），不再是 news_*/data_* 双套
  - 可被任意管线以 subprocess 调用 —— 用于绕开「edge-tts 只装在受管 venv」的双环境问题

用法：
  python tts_worker.py --plan plan_tanchuang.json --out-dir _narration_tanchuang \
                       --field narration --voice zh-CN-XiaoxiaoNeural

输出 <out-dir>/durations.json：
  [{"i":1, "name":"钩子", "text":"...", "mp3":"...\\narration_01.mp3", "dur":12.34}, ...]
"""
import argparse
import asyncio
import json
import os
import subprocess
import sys

try:
    import edge_tts
except ImportError:
    print("[tts] 错误：当前 Python 未安装 edge-tts。", file=sys.stderr)
    print("[tts] 请用装了 edge-tts 的解释器运行，或执行： pip install edge-tts", file=sys.stderr)
    sys.exit(2)


async def tts_one(text: str, mp3: str, voice: str, rate: str, retries: int = 4):
    """合成单段语音，带指数退避重试（edge-tts 偶发网络抖动）。"""
    last = None
    for attempt in range(retries):
        try:
            await edge_tts.Communicate(text, voice, rate=rate).save(mp3)
            return
        except Exception as e:
            last = e
            if attempt < retries - 1:
                wait = 2 * (attempt + 1)
                print(f"  [retry {attempt+1}/{retries-1}] 等待 {wait}s: {str(e)[:60]}", flush=True)
                await asyncio.sleep(wait)
    raise last


def mp3_duration(mp3: str) -> float:
    """用 ffprobe 读 mp3 时长（秒）。失败返回 0。"""
    try:
        out = subprocess.check_output(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", mp3],
            stderr=subprocess.DEVNULL)
        return round(float(out.decode().strip()), 2)
    except Exception as e:
        print(f"  [warn] ffprobe 读时长失败({e})，记为 0", flush=True)
        return 0.0


async def main_async(args):
    os.makedirs(args.out_dir, exist_ok=True)
    with open(args.plan, encoding="utf-8") as f:
        plan = json.load(f)

    modules = plan.get("modules", [])
    if not modules:
        print("[tts] plan 里没有 modules，什么都不做", flush=True)

    prefix = args.field  # 文件名前缀直接用字段名，如 narration_01.mp3
    segs = []
    for i, m in enumerate(modules, 1):
        text = (m.get(args.field) or "").strip()
        rec = {"i": i, "name": m.get("name", f"模块{i}"), "text": text,
               "mp3": None, "dur": 0.0}
        if not text:
            print(f"[tts] {i}/{len(modules)} 「{rec['name']}」无 {args.field}，跳过", flush=True)
            segs.append(rec)
            continue
        mp3 = os.path.join(args.out_dir, f"{prefix}_{i:02d}.mp3")
        print(f"[tts] {i}/{len(modules)} 「{rec['name']}」{len(text)}字 -> {os.path.basename(mp3)}",
              flush=True)
        await tts_one(text, mp3, args.voice, args.rate)
        rec["mp3"] = mp3
        rec["dur"] = mp3_duration(mp3)
        segs.append(rec)

    out_json = os.path.join(args.out_dir, "durations.json")
    with open(out_json, "w", encoding="utf-8") as f:
        json.dump(segs, f, ensure_ascii=False, indent=2)

    total = sum(s["dur"] for s in segs)
    done = sum(1 for s in segs if s["mp3"])
    print(f"TTS_DONE segs={len(segs)} voiced={done} total={total:.1f}s -> {out_json}", flush=True)


def main():
    ap = argparse.ArgumentParser(description="通用 TTS 工作器（edge-tts）")
    ap.add_argument("--plan", required=True, help="EditPlan JSON 路径")
    ap.add_argument("--out-dir", required=True, help="mp3 与 durations.json 输出目录")
    ap.add_argument("--field", default="narration", help="要合成的模块字段名（默认 narration）")
    ap.add_argument("--voice", default="zh-CN-XiaoxiaoNeural",
                    help="音色。探店建议女声 zh-CN-XiaoxiaoNeural；新闻用 zh-CN-YunxiNeural")
    ap.add_argument("--rate", default="+6%", help="语速，如 +6%%")
    args = ap.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
