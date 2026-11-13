# -*- coding: utf-8 -*-
"""画面合编：把每个模块的新闻段 = 原新闻联播画面 + 本地素材画面 + 网上下载画面 三段拼接。
三者共用同一 news 旁白 + 字幕 + 消音，作用是"弱化原新闻段在画面上的存在感"。

切片比例：45% 原新闻 + 30% 本地素材 + 25% 网上下载（按 news_dur 比例切，最少 2 秒/段）。
输出 _composed_news/composed_XX.mp4，并在 plan_composed.json 给模块加 composed_news_path 字段。
供 step5_full_v2.py 读，作为新闻段视频源。"""
import os, sys, json, subprocess, random, glob
WORK = os.path.dirname(os.path.abspath(__file__))

PLAN_IN = os.path.join(WORK, "plan_studio_filtered.json")
PLAN_OUT = os.path.join(WORK, "plan_composed.json")
DURS = os.path.join(WORK, "_narration/durations.json")
MATERIAL_FOLDER = os.environ.get("MATERIAL_FOLDER", os.environ.get("MATERIAL_FOLDER", os.path.join(WORK, "materials")))
BOX = os.environ.get("BOX_DIR",
                     os.environ.get("BOX_DIR", os.path.join(WORK, "broll")))
STOCK_INDEX = os.path.join(WORK, "_stock/index.json")
OUT_DIR = os.path.join(WORK, "_composed_news")
TMP_DIR = os.path.join(OUT_DIR, "_segs")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(TMP_DIR, exist_ok=True)

# 切片比例（按 news_dur 比例）
RATIO_NEWS = 0.45
RATIO_LOCAL = 0.30
RATIO_WEB = 0.25
MIN_SEG = 2.0  # 每段最少 2 秒


def cut_clip(src, dst, start, dur):
    """ffmpeg 抽片段并缩放统一到 1280x720 / 30fps"""
    cmd = ["ffmpeg", "-y", "-ss", f"{start:.3f}", "-i", src,
           "-t", f"{dur:.3f}", "-vf", "scale=1280:720,setsar=1,fps=30",
           "-an", "-c:v", "libx264", "-pix_fmt", "yuv420p", dst]
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 1000


def concat_clips(parts, dst):
    """多段 mp4 拼接"""
    if len(parts) == 1:
        # 只有一个片段时直接复制
        subprocess.run(["ffmpeg", "-y", "-i", parts[0], "-c", "copy", dst], capture_output=True)
        return os.path.exists(dst)
    filt_parts = ";".join([f"[{i}:v]scale=1280:720,setsar=1,fps=30[v{i}]" for i in range(len(parts))])
    filt_concat = "".join([f"[v{i}]" for i in range(len(parts))]) + f"concat=n={len(parts)}:v=1:a=0[v]"
    filt = f"{filt_parts};{filt_concat}"
    cmd = ["ffmpeg", "-y"]
    for p in parts:
        cmd.extend(["-i", p])
    cmd.extend(["-filter_complex", filt, "-map", "[v]", "-r", "30",
                "-c:v", "libx264", "-pix_fmt", "yuv420p", dst])
    r = subprocess.run(cmd, capture_output=True)
    return r.returncode == 0 and os.path.exists(dst)


# 加载
plan = json.load(open(PLAN_IN, encoding="utf-8"))
durs = json.load(open(DURS, encoding="utf-8"))
dur_by_i = {s["i"]: s for s in durs}
stock_index = json.load(open(STOCK_INDEX, encoding="utf-8")).get("clips", {}) \
    if os.path.exists(STOCK_INDEX) else {}

src_videos = sorted(glob.glob(os.path.join(MATERIAL_FOLDER, "*.mp4")))
src_video = src_videos[0] if src_videos else None

# 本地素材池（每次随机取，避重复）
all_box = [os.path.join(BOX, f) for f in os.listdir(BOX) if f.lower().endswith(".mp4")]
random.seed()
random.shuffle(all_box)
box_cursor = 0  # 每次取下一条


def take_box_path():
    """从本地素材池按游标顺序取一条（已随机打乱）"""
    global box_cursor
    if not all_box:
        return None
    p = all_box[box_cursor % len(all_box)]
    box_cursor += 1
    return p


modules = plan.get("modules", [])
for m in modules:
    mid = m.get("id")
    name = m.get("name", "?")
    if m.get("dropped_by_studio"):
        print(f"[compose] 模块{mid}「{name}」被 studio_filter 跳过，不合成")
        continue
    d_info = dur_by_i.get(mid)
    if not d_info:
        print(f"[compose] 模块{mid}「{name}」无配音时长信息，跳过")
        continue
    news_dur = float(d_info["news_dur"])
    if news_dur < 4.0:
        print(f"[compose] 模块{mid}「{name}」旁白过短({news_dur:.1f}s)，跳过画面合编")
        continue

    # 切片时长
    dur_news_clip = max(news_dur * RATIO_NEWS, MIN_SEG)
    dur_local = max(news_dur * RATIO_LOCAL, MIN_SEG)
    dur_web = max(news_dur * RATIO_WEB, MIN_SEG)
    total = dur_news_clip + dur_local + dur_web
    if total > news_dur + 0.5:
        scale = news_dur / total
        dur_news_clip *= scale
        dur_local *= scale
        dur_web *= scale

    parts = []

    # 1) 原新闻片段（已被 studio_filter 裁过）
    clip = m.get("clip") or {}
    if src_video and clip.get("start_sec") is not None:
        s = float(clip["start_sec"])
        available = float(clip.get("duration_sec", dur_news_clip))
        actual = min(available, dur_news_clip)
        if actual >= 1.0:
            seg = os.path.join(TMP_DIR, f"news_{mid:02d}.mp4")
            if cut_clip(src_video, seg, s, actual):
                parts.append(seg)
                print(f"  [compose] 模块{mid} 原新闻 {actual:.1f}s")
            else:
                print(f"  [compose] 模块{mid} 原新闻抽帧失败")
    if not parts:
        # 没有原新闻片段时退而求其次：本地素材全占
        dur_local = dur_news_clip + dur_local + dur_web
        dur_web = 0

    # 2) 本地素材片段
    box_path = take_box_path()
    if box_path and dur_local >= 1.0:
        seg = os.path.join(TMP_DIR, f"local_{mid:02d}.mp4")
        if cut_clip(box_path, seg, 0, dur_local):
            parts.append(seg)
            print(f"  [compose] 模块{mid} 本地素材 {dur_local:.1f}s <- {os.path.basename(box_path)}")
        else:
            print(f"  [compose] 模块{mid} 本地素材抽帧失败")

    # 3) 网上下载片段
    stock_info = stock_index.get(str(mid))
    if stock_info and os.path.exists(stock_info.get("path", "")) and dur_web >= 1.0:
        seg = os.path.join(TMP_DIR, f"web_{mid:02d}.mp4")
        if cut_clip(stock_info["path"], seg, 0, dur_web):
            parts.append(seg)
            print(f"  [compose] 模块{mid} 网上下载 {dur_web:.1f}s")
        else:
            print(f"  [compose] 模块{mid} 网上下载抽帧失败")

    if not parts:
        print(f"[compose] 模块{mid}「{name}」无可用片段，跳过")
        continue

    # 拼接
    composed = os.path.join(OUT_DIR, f"composed_{mid:02d}.mp4")
    if concat_clips(parts, composed):
        m["composed_news_path"] = composed
        m["composed_news_dur"] = news_dur
        m["composed_news_segments"] = len(parts)
        print(f"[compose] 模块{mid}「{name}」合成 {composed} ({news_dur:.1f}s, {len(parts)}段)")
    else:
        print(f"[compose] 模块{mid}「{name}」拼接失败")

json.dump(plan, open(PLAN_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
n_done = sum(1 for m in modules if m.get("composed_news_path"))
print(f"\n[compose] 完成 → {PLAN_OUT}（{n_done}/{len(modules)}个模块合成成功）")