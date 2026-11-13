# -*- coding: utf-8 -*-
"""生成「高技术制造 +13.3% / 芯片出口 +88.7%」动态数据柱状图 mp4 片段。
用于验证：图形动画类特效能否用 Python 渲染成 mp4，再叠进剪映草稿。
"""
import matplotlib
import os
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.font_manager as fm
from matplotlib.animation import FFMpegWriter
WORK = os.path.dirname(os.path.abspath(__file__))

FONT = "C:/Windows/Fonts/msyh.ttc"
fm.fontManager.addfont(FONT)
ZH = fm.FontProperties(fname=FONT).get_name()
plt.rcParams["font.sans-serif"] = [ZH]
plt.rcParams["axes.unicode_minus"] = False

OUT = os.path.join(WORK, "特效_数据柱状图.mp4")
W, H, DPI, FPS = 1280, 720, 100, 30
BG = "#0A1A2E"
RED1, RED2 = "#E24B4A", "#FF7A45"
WHITE, GRAY = "#FFFFFF", "#9AA7B5"

ITEMS = [("高技术制造", 13.3, RED1), ("芯片出口", 88.7, RED2)]
MAXV = 100


def ease(t):
    return 1 - (1 - t) ** 3


GROW, HOLD = 60, 45  # 2s 增长 + 1.5s 定格 = 3.5s
TOTAL = GROW + HOLD

fig, ax = plt.subplots(figsize=(W / DPI, H / DPI), dpi=DPI)
fig.patch.set_facecolor(BG)
ax.set_facecolor(BG)

writer = FFMpegWriter(fps=FPS, metadata={"title": "数据柱状图"})
with writer.saving(fig, OUT, dpi=DPI):
    for f in range(TOTAL):
        p = ease(min(f / GROW, 1.0)) if f < GROW else 1.0
        ax.clear()
        ax.set_facecolor(BG)
        ax.set_xlim(-0.7, 1.7)
        ax.set_ylim(-9, MAXV + 18)
        ax.axis("off")
        ax.text(0.5, MAXV + 13, "硬核制造 · 业绩兑现", ha="center", va="center",
                color=WHITE, fontsize=26, fontweight="bold")
        ax.text(0.5, MAXV + 6, "2026 上半年关键指标", ha="center", va="center",
                color=GRAY, fontsize=14)
        for i, (name, v, col) in enumerate(ITEMS):
            h = v * p
            ax.bar(i, h, width=0.52, color=col, zorder=2)
            ax.text(i, h + 3, f"+{v * p:.1f}%", ha="center", va="bottom",
                    color=WHITE, fontsize=22, fontweight="bold")
            ax.text(i, -5, name, ha="center", va="top", color=GRAY, fontsize=16)
        ax.plot([-0.7, 1.7], [0, 0], color=GRAY, lw=1, zorder=1)
        writer.grab_frame()

print("OK", OUT)
