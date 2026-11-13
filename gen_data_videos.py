# -*- coding: utf-8 -*-
"""批量生成每模块的数据图 mp4（基于 plan.json 的 data 字段）。managed venv 跑。"""
import matplotlib
import os
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.animation import FFMpegWriter
import json, os
WORK = os.path.dirname(os.path.abspath(__file__))

FONT = "C:/Windows/Fonts/msyh.ttc"
fm.fontManager.addfont(FONT)
ZH = fm.FontProperties(fname=FONT).get_name()
plt.rcParams["font.sans-serif"] = [ZH]
plt.rcParams["axes.unicode_minus"] = False

PLAN = os.path.join(WORK, "plan.json")
OUT_DIR = os.path.join(WORK, "_data")
W, H, DPI, FPS = 1280, 720, 100, 30
BG = "#0A1A2E"
YELLOW, WHITE, GRAY = "#FFD24D", "#FFFFFF", "#9AA7B5"

os.makedirs(OUT_DIR, exist_ok=True)
plan = json.load(open(PLAN, encoding="utf-8"))
mods = plan["modules"]


def ease(t):
    return 1 - (1 - t) ** 3


def gen_one(mod, out):
    d = mod.get("data") or {}
    label = d.get("label", "")
    value = d.get("value", "")
    unit = d.get("unit", "")
    caption = d.get("caption", "")
    GROW, HOLD = 60, 30  # 2s + 1s
    TOTAL = GROW + HOLD
    fig, ax = plt.subplots(figsize=(W / DPI, H / DPI), dpi=DPI)
    fig.patch.set_facecolor(BG)
    ax.set_facecolor(BG)
    writer = FFMpegWriter(fps=FPS)
    with writer.saving(fig, out, dpi=DPI):
        for f in range(TOTAL):
            p = ease(min(f / GROW, 1.0)) if f < GROW else 1.0
            ax.clear()
            ax.set_facecolor(BG)
            ax.set_xlim(0, 1)
            ax.set_ylim(0, 1)
            ax.axis("off")
            ax.text(0.5, 0.85, label, ha="center", va="center",
                    color=YELLOW, fontsize=24, fontweight="bold")
            if value:
                try:
                    vnum = float(value) * p
                    txt = f"{vnum:.1f}" if "." in value else f"{vnum:.0f}"
                except Exception:
                    txt = value
                ax.text(0.5, 0.5, txt + unit, ha="center", va="center",
                        color=WHITE, fontsize=80, fontweight="bold")
                if caption:
                    ax.text(0.5, 0.18, caption, ha="center", va="center",
                            color=GRAY, fontsize=20)
            else:
                ax.text(0.5, 0.5, caption, ha="center", va="center",
                        color=WHITE, fontsize=46, fontweight="bold")
            writer.grab_frame()
    plt.close(fig)


for i, m in enumerate(mods, 1):
    out = os.path.join(OUT_DIR, f"seg_{i:02d}.mp4")
    print(f"[data] {i}/{len(mods)} {m['name']} -> {os.path.basename(out)}")
    gen_one(m, out)
print("DATA_VIDEOS_DONE", OUT_DIR)
