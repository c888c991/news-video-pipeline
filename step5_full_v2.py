# -*- coding: utf-8 -*-
"""完整v4：片头(日期标题) + 每模块[画面合编段(新闻+本地素材+网上下载共用旁白字幕) + 数据段]。
本地素材和网上下载已合到新闻段画面里(由 step_compose_news.py 合成 composed_news_path)，
step5 只负责把合编视频挂上旁白+字幕+消音，再拼数据段；不再单独插入扩展片段段。"""
import sys, json, os, re
import os
sys.path.insert(0, os.environ.get("JIANYING_EDITOR", os.path.join(WORK, "_editor")))
from config import load_config
from ingest import MaterialIngestor, discover_videos
from matcher import ClipMatcher, ResolvedClip
from renderer import DraftRenderer
sys.path.insert(0, WORK)
from effects_director import build_spec, detect_role, detect_theme, detect_studio
WORK = os.path.dirname(os.path.abspath(__file__))

cfg = load_config()
log = lambda m: print(m, flush=True)

# 优先读 plan_composed.json → plan_studio_filtered.json → plan.json
PLAN_PATHS = [
    os.path.join(WORK, "plan_composed.json"),
    os.path.join(WORK, "plan_studio_filtered.json"),
    os.path.join(WORK, "plan.json"),
]
PLAN_PATH = next((p for p in PLAN_PATHS if os.path.exists(p)), PLAN_PATHS[-1])
plan = json.load(open(PLAN_PATH, encoding="utf-8"))
log(f"[v4] 读取 plan: {PLAN_PATH}")

durs = json.load(open(os.path.join(WORK, "_narration/durations.json"), encoding="utf-8"))
dur_by_i = {s["i"]: s for s in durs}
MERGED_DIR = os.path.join(WORK, "_merged")

ing = MaterialIngestor(cfg, log)
MATERIAL_FOLDER = os.environ.get("MATERIAL_FOLDER", os.environ.get("MATERIAL_FOLDER", os.path.join(WORK, "materials")))
index = ing.ingest(discover_videos(MATERIAL_FOLDER))
clips = ClipMatcher(cfg, log).resolve(plan, index)

# 日期从视频名解析（20260720 → 2026年7月20日）
vid_name = index["materials"][0]["name"]
m = re.search(r'(\d{8})', vid_name)
date_str = f"{m.group(1)[:4]}年{int(m.group(1)[4:6])}月{int(m.group(1)[6:8])}日" if m else ""

# 用合编视频替换原新闻段（如果模块有 composed_news_path 且文件存在）
for i, mod in enumerate(plan.get("modules", [])):
    if mod.get("dropped_by_studio"):
        continue  # 该模块已被 studio_filter 丢弃，ClipMatcher 已跳过
    composed = mod.get("composed_news_path")
    if composed and os.path.exists(composed) and i < len(clips):
        clips[i].material_path = composed
        clips[i].start_sec = 0.0
        mid = mod.get("id")
        if mid in dur_by_i:
            clips[i].duration_sec = float(dur_by_i[mid]["news_dur"])
        log(f"[v4] 模块{mid}「{mod.get('name')}」使用合编视频 {os.path.basename(composed)}")

mixed = []


def build_news_clip(idx):
    """根据 idx 构造新闻段 ResolvedClip（用合编视频或原视频）"""
    if idx - 1 >= len(clips):
        return None
    c = clips[idx - 1]
    s = dur_by_i[idx]
    c.keep_audio = False  # 消音原视频
    c.narration_mp3 = s["news_mp3"]
    c.subtitle = {"text": s["news_text"]}
    c.title = None
    c.duration_sec = s["news_dur"]
    return c


def build_data_clip(idx, module_name):
    """根据 idx 构造数据段 ResolvedClip"""
    s = dur_by_i[idx]
    if not s.get("data_mp3"):
        return None
    merged_path = os.path.join(MERGED_DIR, f"merged_{idx:02d}.mp4")
    if not os.path.exists(merged_path):
        log(f"[v4] 模块{idx} 缺 merged_xx.mp4，跳过数据段")
        return None
    dc = ResolvedClip({"name": f"数据·{module_name}"},
                      merged_path, 0.0, s["data_dur"])
    dc.narration_mp3 = s["data_mp3"]
    dc.subtitle = {"text": s["data_text"]}
    return dc


# ===== 拼接：每模块 = 画面合编段 + 数据段，并挂特效套餐 =====
total = len(plan.get("modules", []))
intro_meta = plan.get("intro", {})
for idx in range(1, total + 1):
    mod = plan["modules"][idx - 1]
    if mod.get("dropped_by_studio"):
        log(f"[v4] 模块{idx}「{mod.get('name')}」被演播室识别裁空，跳过")
        continue
    if idx not in dur_by_i:
        log(f"[v4] 模块{idx} 无配音时长信息，跳过")
        continue
    i = idx - 1
    theme = detect_theme(mod)
    studio_skip = detect_studio(mod)
    pos = "first" if i == 0 else ("last" if i == total - 1 else "mid")
    news_dur = float(dur_by_i[idx]["news_dur"])
    # 新闻段套餐：用模块角色（若该模块本身是数据型则降为"主体"），合成画面，挂主题滤镜+推近+转场
    mrole = detect_role(mod, i, total, intro_meta)
    if mrole == "数据":
        mrole = "主体"
    news_spec = build_spec(mrole, theme, news_dur, "合成画面", pos, studio_skip, i)
    # 数据段套餐：强制"数据"角色=不推近+不上滤镜+转场；新闻数据段是满屏图表，去掉矩形蒙版
    data_dur = float(dur_by_i[idx].get("data_dur", 0) or 0)
    data_spec = build_spec("数据", theme, data_dur, "数据图", pos, False, i)
    data_spec.mask = None
    nc = build_news_clip(idx)
    if nc:
        nc.effect_spec = news_spec
        mixed.append(nc)
        log(f"[v4] 模块{idx}「{nc.name}」新闻合编段 {nc.duration_sec:.1f}s <- {os.path.basename(nc.material_path)} [特效:{mrole}/{theme}]")
    dc = build_data_clip(idx, mod.get("name", "?"))
    if dc:
        dc.effect_spec = data_spec
        mixed.append(dc)
        log(f"[v4] 模块{idx}「{dc.name}」数据段 {dc.duration_sec:.1f}s [特效:数据]")

# ===== 片头：日期标题（中性，不暴露节目来源）=====
if date_str:
    intro = plan.setdefault("intro", {})
    intro["enabled"] = True
    intro["title"] = {"text": f"{date_str}\n今日资讯", "color": "#FFD24D"}
    if not intro.get("duration_sec"):
        intro["duration_sec"] = 3

n_news = sum(1 for x in mixed if not x.name.startswith("数据·"))
n_data = len(mixed) - n_news
log(f"[v4] 总段数 {len(mixed)}（片头 + {n_news}个新闻合编段 + {n_data}个数据段）")
DRAFT_NAME = os.environ.get("DRAFT_NAME", "新闻_完整v4")
path = DraftRenderer(cfg, log).render(plan, mixed, draft_name=DRAFT_NAME)
print("DRAFT=" + path)