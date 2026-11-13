# -*- coding: utf-8 -*-
"""合并v2：每模块 数据图mp4(3s) + B-roll补足到 data_narration 时长 → merged_i.mp4。
B-roll 长度 = data_dur - 3（让合并段时长≈数据旁白时长，画面旁白对齐）。system python 跑。"""
import os, subprocess, json, random
WORK = os.path.dirname(os.path.abspath(__file__))

PLAN = os.path.join(WORK, "plan.json")
DATA_DIR = os.path.join(WORK, "_data")
BOX = os.environ.get("BOX_DIR", os.environ.get("BOX_DIR", os.path.join(WORK, "broll")))
OUT_DIR = os.path.join(WORK, "_merged")
DURS = os.path.join(WORK, "_narration/durations.json")
os.makedirs(OUT_DIR, exist_ok=True)

plan = json.load(open(PLAN, encoding="utf-8"))
durs = json.load(open(DURS, encoding="utf-8"))
n = len(plan["modules"])
all_mp4 = [f for f in os.listdir(BOX) if f.lower().endswith(".mp4")]
random.seed()  # 用系统时间做种子，每次跑结果不同
n_take = min(n, len(all_mp4))
brolls = random.sample(all_mp4, n_take)  # 不重复随机取 n 条（不足则取全部）
if n_take < n:
    print(f"[merge] 警告：素材箱仅有{n_take}个mp4，少于{n}个模块，最后{brolls[-1]}会重复用")

for s in durs:
    i = s["i"]
    data_dur = s.get("data_dur", 8)
    broll_len = max(data_dur - 3, 2)  # 数据图3s + B-roll补足
    data_mp4 = os.path.join(DATA_DIR, f"seg_{i:02d}.mp4")
    broll_mp4 = os.path.join(BOX, brolls[i - 1])
    merged = os.path.join(OUT_DIR, f"merged_{i:02d}.mp4")
    filt = (f"[0:v]scale=1280:720,setsar=1[v0];"
            f"[1:v]trim=0:{broll_len:.2f},scale=1280:720,setsar=1[v1];"
            f"[v0][v1]concat=n=2:v=1:a=0[v]")
    r = subprocess.run(
        ["ffmpeg", "-y", "-i", data_mp4, "-i", broll_mp4,
         "-filter_complex", filt, "-map", "[v]", "-r", "30",
         "-c:v", "libx264", "-pix_fmt", "yuv420p", merged],
        capture_output=True)
    if r.returncode != 0:
        print(f"[merge] {i} 失败: {r.stderr.decode()[-300:]}")
    else:
        print(f"[merge] {i} broll={broll_len:.1f}s -> {os.path.basename(merged)}")
print("MERGED_DONE", OUT_DIR)
