# -*- coding: utf-8 -*-
"""Step2 v2: 读 plan.json，每模块生成 news_narration + data_narration 两套 mp3。
输出 durations.json 含 news_mp3/news_dur/data_mp3/data_dur。managed venv 跑。"""
import asyncio, json, os, subprocess
import os
import edge_tts
WORK = os.path.dirname(os.path.abspath(__file__))

PLAN = os.path.join(WORK, "plan.json")
OUT_DIR = os.path.join(WORK, "_narration")
VOICE = "zh-CN-YunxiNeural"
RATE = "+6%"


async def tts_one(text, mp3, retries=8):
    last = None
    for attempt in range(retries):
        try:
            await edge_tts.Communicate(text, VOICE, rate=RATE).save(mp3)
            return
        except Exception as e:
            last = e
            if attempt < retries - 1:
                wait = 3 * (attempt + 1)
                print(f"  [retry {attempt+1}/{retries-1}] wait {wait}s: {str(e)[:50]}", flush=True)
                await asyncio.sleep(wait)
    raise last


def mp3_duration(mp3):
    out = subprocess.check_output(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", mp3])
    return float(out.decode().strip())


async def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    plan = json.load(open(PLAN, encoding="utf-8"))
    mods = plan["modules"]
    segs = []
    for i, m in enumerate(mods, 1):
        news = (m.get("narration") or "").strip()
        data = (m.get("data_narration") or "").strip()
        rec = {"i": i, "name": m["name"], "news_text": news, "data_text": data}
        if news:
            nmp = os.path.join(OUT_DIR, f"news_{i:02d}.mp3")
            print(f"[tts] news {i}/{len(mods)} {m['name']}")
            await tts_one(news, nmp)
            rec["news_mp3"] = nmp
            rec["news_dur"] = round(mp3_duration(nmp), 2)
        else:
            rec["news_mp3"] = None
            rec["news_dur"] = 0
        if data:
            dmp = os.path.join(OUT_DIR, f"data_{i:02d}.mp3")
            print(f"[tts] data {i}/{len(mods)} {m['name']}")
            await tts_one(data, dmp)
            rec["data_mp3"] = dmp
            rec["data_dur"] = round(mp3_duration(dmp), 2)
        else:
            rec["data_mp3"] = None
            rec["data_dur"] = 0
        segs.append(rec)

    json.dump(segs, open(os.path.join(OUT_DIR, "durations.json"), "w", encoding="utf-8"),
              ensure_ascii=False, indent=2)
    print("TTS_DONE segs=", len(segs))


asyncio.run(main())
