# -*- coding: utf-8 -*-
"""剪映特效 · 调度器（规则引擎）—— 决定「何时用何特效」。

这是特效引擎之上的一层编排：读取 plan 里每个片段(module)的上下文字段，
自动提取五维特征（角色 / 内容主题 / 时长 / 画面类型 / 位置），查 RULES 规则表，
生成该片段的特效套餐 EffectSpec，再 apply_effect_spec 套到 VideoSegment 上。

判断依据全部来自现有 plan 字段，无需人工标注：
- 角色   : id 顺序 + name 关键词 + intro 段
- 主题   : search_query / note / name / narration 关键词
- 时长   : clip.duration_sec 或 composed_news_dur
- 画面类型: data.value 非空 = 数据段；composed_news_segments = 合成画面
- 位置   : id 在 modules 中的序位（首/中/末）
- 演播室 : name/note 含演播室/主持人/出镜 → 双保险跳过关键帧推近

新闻线(plan_composed.json)与探店线(plan_tanchuang_mixed.json) plan 结构同源，通用。
"""
import json
from dataclasses import dataclass
from typing import Optional

from pyJianYingDraft import KeyframeProperty, SEC, FilterType
import effects_engine as fx


# ---------------------------------------------------------------------------
# 主题关键词 → 滤镜（按用户确认「按主题分色」）
# ---------------------------------------------------------------------------
THEME_KEYWORDS = {
    "科技": ["人工智能", "ai", "芯片", "半导体", "科技", "智能", "数字", "算力", "算法"],
    "工厂": ["工厂", "基建", "制造", "建设", "高铁", "工地", "产线", "车间", "机械"],
    "美食": ["芋儿鸡", "美食", "打卡", "排队", "探店", "火锅", "小吃", "餐饮", "菜品", "店"],
    "人物": ["人物", "访谈", "专家", "老板", "嬢嬢", "主播", "顾客", "师傅"],
    "财经": ["出口", "增长", "营收", "经济", "财政", "货币", "gdp", "消费", "物流"],
}
THEME_FILTER = {
    "科技": ("克洛伊", 30.0),    # 冷调
    "工厂": ("侘寂灰", 35.0),    # 高对比冷灰
    "美食": ("亮夏", 55.0),      # 暖亮
    "人物": ("书意", 35.0),      # 柔和
    "财经": ("侘寂灰", 25.0),    # 稳重
    "通用": ("侘寂灰", 25.0),
}
STUDIO_KEYWORDS = ["演播室", "主持人", "出镜", "主播台", "台标"]


# ---------------------------------------------------------------------------
# 角色基础套餐（默认规则强度，已与用户确认）
# ---------------------------------------------------------------------------
ROLE_BASE = {
    "开场": dict(scale_from=1.0, scale_to=1.10, pan=0.02, fade_in=0.5,
                 transition_dur=0.5, brightness=0.08),
    "主体": dict(scale_from=1.0, scale_to=1.05, pan=0.02, fade_in=0.4,
                 transition_dur=0.4),
    "数据": dict(scale_from=None, scale_to=None, pan=0.0, fade_in=0.3,
                 transition_dur=0.3,
                 mask=dict(mask_name="矩形", cx=0.0, cy=0.0, w=0.42, h=0.42, feather=0.06)),
    "收尾": dict(scale_from=1.05, scale_to=1.0, pan=0.0, fade_out=0.5,
                 transition_dur=0.5),
}


# ---------------------------------------------------------------------------
# 特效套餐数据结构
# ---------------------------------------------------------------------------
@dataclass
class EffectSpec:
    index: int
    role: str
    scale_from: Optional[float] = None     # None = 不推近
    scale_to: Optional[float] = None
    pan: float = 0.0                        # 0 = 不摇移
    fade_in: float = 0.0
    fade_out: float = 0.0
    filter_name: Optional[str] = None
    filter_intensity: float = 30.0
    transition_name: Optional[str] = None
    transition_dur: float = 0.4
    mask: Optional[dict] = None             # {"mask_name","cx","cy","w","h",...}
    brightness: Optional[float] = None
    contrast: Optional[float] = None
    saturation: Optional[float] = None
    skip_keyframe: bool = False             # 演播室双保险：跳过关键帧推近/摇移/淡入/调色


# ---------------------------------------------------------------------------
# 特征提取
# ---------------------------------------------------------------------------
def detect_role(m, idx, total, intro):
    name = m.get("name") or ""
    data = m.get("data") or {}
    dv = (data.get("value") or "").strip()
    if any(k in name for k in ("钩子", "开场", "引爆", "引入")) or (idx == 0 and (intro or {}).get("enabled")):
        return "开场"
    if dv:
        return "数据"
    if any(k in name for k in ("结尾", "总结", "收尾", "收束")) or idx == total - 1:
        return "收尾"
    return "主体"


def detect_theme(m):
    text = " ".join(str(m.get(k) or "") for k in
                    ("name", "search_query", "stock_query", "note", "narration")).lower()
    for theme, kws in THEME_KEYWORDS.items():
        if any(k.lower() in text for k in kws):
            return theme
    return "通用"


def get_duration(m):
    clip = m.get("clip") or {}
    if clip.get("duration_sec"):
        return float(clip["duration_sec"])
    d = m.get("composed_news_dur")
    if d:
        return float(d)
    return 8.0


def detect_vtype(m):
    data = m.get("data") or {}
    if (data.get("value") or "").strip():
        return "数据图"
    if m.get("composed_news_segments") or m.get("composed_news_path"):
        return "合成画面"
    return "实拍"


def detect_studio(m):
    text = " ".join(str(m.get(k) or "") for k in
                    ("name", "note", "search_query", "narration")).lower()
    return any(k in text for k in STUDIO_KEYWORDS)


# ---------------------------------------------------------------------------
# 规则合成：角色基础 + 主题滤镜 + 时长微调 + 双保险
# ---------------------------------------------------------------------------
def build_spec(role, theme, dur, vtype, pos, studio_skip, index):
    base = dict(ROLE_BASE.get(role, ROLE_BASE["主体"]))
    spec = EffectSpec(index=index, role=role, **base)

    # 主题分色滤镜（数据段不上滤镜，保清晰）
    if role == "数据":
        spec.filter_name = None
    else:
        fname, intensity = THEME_FILTER.get(theme, THEME_FILTER["通用"])
        spec.filter_name, spec.filter_intensity = fname, intensity

    # 转场：首段不上（前面无片段可衔接）；短镜头转场减半
    if pos == "first":
        spec.transition_name = None
    else:
        spec.transition_name = "叠化"
        td = base.get("transition_dur", 0.4)
        if dur < 5:
            td = round(td * 0.5, 2)
        spec.transition_dur = td

    # 长镜头(>15s)推近幅度减半，避免长时间突兀
    if dur > 15 and spec.scale_from is not None:
        spec.scale_to = round(spec.scale_from + (spec.scale_to - spec.scale_from) * 0.5, 3)

    # 演播室双保险：跳过关键帧推近/摇移/淡入/调色（滤镜与转场仍保留）
    spec.skip_keyframe = studio_skip
    return spec


def build_effect_plan(plan):
    """读 plan，为每个 module 生成特效套餐。返回 list[EffectSpec]。"""
    mods = plan.get("modules", [])
    intro = plan.get("intro") or {}
    specs = []
    for i, m in enumerate(mods):
        role = detect_role(m, i, len(mods), intro)
        theme = detect_theme(m)
        dur = get_duration(m)
        vtype = detect_vtype(m)
        pos = "first" if i == 0 else ("last" if i == len(mods) - 1 else "mid")
        studio_skip = detect_studio(m)
        specs.append(build_spec(role, theme, dur, vtype, pos, studio_skip, i))
    return specs


# ---------------------------------------------------------------------------
# 套用到片段
# ---------------------------------------------------------------------------
def apply_effect_spec(seg, spec, pan_dir=1):
    """把套餐套到 VideoSegment 上（复用 effects_engine 的 apply_mask/apply_transition）。"""
    dur_us = seg.target_timerange.duration

    if not spec.skip_keyframe:
        # 关键帧推近 / 拉远
        if spec.scale_from is not None and spec.scale_to is not None:
            seg.add_keyframe(KeyframeProperty.scale_x, 0, spec.scale_from)
            seg.add_keyframe(KeyframeProperty.scale_x, dur_us, spec.scale_to)
            seg.add_keyframe(KeyframeProperty.scale_y, 0, spec.scale_from)
            seg.add_keyframe(KeyframeProperty.scale_y, dur_us, spec.scale_to)
        # 轻微摇移
        if spec.pan:
            seg.add_keyframe(KeyframeProperty.position_x, 0, 0.0)
            seg.add_keyframe(KeyframeProperty.position_x, dur_us, spec.pan * pan_dir)
        # 入场淡入
        if spec.fade_in > 0:
            seg.add_keyframe(KeyframeProperty.alpha, 0, 0.0)
            seg.add_keyframe(KeyframeProperty.alpha, int(spec.fade_in * SEC), 1.0)
        # 出场淡出
        if spec.fade_out > 0:
            seg.add_keyframe(KeyframeProperty.alpha, max(0, dur_us - int(spec.fade_out * SEC)), 1.0)
            seg.add_keyframe(KeyframeProperty.alpha, dur_us, 0.0)
        # 调色（恒定值，单点关键帧）
        if spec.brightness is not None:
            seg.add_keyframe(KeyframeProperty.brightness, 0, spec.brightness)
        if spec.contrast is not None:
            seg.add_keyframe(KeyframeProperty.contrast, 0, spec.contrast)
        if spec.saturation is not None:
            seg.add_keyframe(KeyframeProperty.saturation, 0, spec.saturation)

    # 滤镜（双保险不跳过）
    if spec.filter_name:
        seg.add_filter(fx._enum(FilterType, spec.filter_name), spec.filter_intensity)
    # 蒙版
    if spec.mask:
        fx.apply_mask(seg, **spec.mask)
    # 转场
    if spec.transition_name:
        fx.apply_transition(seg, spec.transition_name, spec.transition_dur)
    return seg


# ---------------------------------------------------------------------------
# 自检：打印每个 module 的决策结果（不生成草稿）
# ---------------------------------------------------------------------------
def _print_plan(plan):
    specs = build_effect_plan(plan)
    meta = plan.get("meta", {})
    print("\n===== %s =====" % meta.get("title", "(无标题)"))
    print("画幅 %sx%s | 模块数 %d" % (meta.get("width"), meta.get("height"), len(specs)))
    for s in specs:
        filt = "%s(%s)" % (s.filter_name, s.filter_intensity) if s.filter_name else "无"
        scale = "%.2f→%.2f" % (s.scale_from, s.scale_to) if s.scale_from is not None else "不推近"
        tr = "%s(%.2fs)" % (s.transition_name, s.transition_dur) if s.transition_name else "无"
        print("  [%d] %s | 滤镜%-12s | 推近%-9s | 转场%-10s | 蒙版%s | 双保险%s"
              % (s.index, s.role, filt, scale, tr, "是" if s.mask else "否", "跳" if s.skip_keyframe else "-"))


if __name__ == "__main__":
    for pf in ("plan_composed.json", "plan_tanchuang_mixed.json"):
        try:
            _print_plan(json.load(open(pf, encoding="utf-8")))
        except Exception as e:
            print(pf, "读取失败：", e)
