# -*- coding: utf-8 -*-
"""剪映特效引擎 —— 关键帧动画 / 调色 / 滤镜 / 内置特效 / 转场 / 蒙版 / 文字动画。

交付两种形态：
- 独立模块：其它脚本 import 本模块，逐片段调用 apply_* 函数套用特效。
- 插件形态：现有渲染器在创建每个 VideoSegment / TextSegment 后调用 apply_*。

风格全部集中在 PRESETS 字典，改效果只改这里。
"""
from pyJianYingDraft import (
    VideoSegment, TextSegment, KeyframeProperty, SEC,
    FilterType, VideoSceneEffectType, TransitionType, MaskType,
    TextIntro, TextOutro, TextLoopAnim,
)
from pyJianYingDraft.video_segment import Transition, Mask


def _enum(enum_cls, name):
    """按中文名取枚举成员，找不到时列出可用项，方便排查。"""
    try:
        return getattr(enum_cls, name)
    except AttributeError:
        avail = [m.name for m in enum_cls]
        raise ValueError("未知%s：%s；可用项（前20）：%s" % (enum_cls.__name__, name, avail[:20]))


# ---------------------------------------------------------------------------
# 预设库：改风格只改这里
# ---------------------------------------------------------------------------
PRESETS = {
    "horizontal": {                 # 新闻横屏 1920x1080
        "video": {
            "scale": (1.0, 1.06),   # (起, 止) 均匀推近，新闻克制
            "pan_x": 0.02,          # 轻微摇移（半画布单位，右移为正）
            "fade_in": 0.4,         # 入场淡入秒
            "fade_out": 0.0,        # 出场淡出秒（0=不）
            "filter": ("侘寂灰", 30.0),   # (滤镜名, 强度0-100)
            "effect": None,         # (内置特效名, [参数0-100]) 或 None
        },
        "title":    {"intro": "弹入", "outro": None, "loop": None},
        "subtitle": {"intro": "向上滑动", "outro": None, "loop": "扫光"},
        "transition": ("叠化", 0.4),
    },
    "vertical": {                   # 探店竖屏 1080x1920（备用，本次样片未用）
        "video": {
            "scale": (1.0, 1.12),
            "pan_x": 0.03,
            "fade_in": 0.4,
            "fade_out": 0.0,
            "filter": ("亮夏", 70.0),
            "effect": None,
        },
        "title":    {"intro": "弹入", "outro": None, "loop": None},
        "subtitle": {"intro": "向上滑动", "outro": None, "loop": "扫光"},
        "transition": ("叠化", 0.4),
    },
}


# ---------------------------------------------------------------------------
# 视频片段特效
# ---------------------------------------------------------------------------
def apply_video_effects(seg, preset, dur_us, pan_dir=1):
    """对单个视频片段施加：均匀推近 + 轻微摇移 + 入场淡入 + 滤镜(+可选特效)。"""
    sx, sy = preset["scale"]
    # 均匀推近：scale_x / scale_y 同步关键帧（二者等值即视觉均匀缩放）
    seg.add_keyframe(KeyframeProperty.scale_x, 0, sx)
    seg.add_keyframe(KeyframeProperty.scale_x, dur_us, sy)
    seg.add_keyframe(KeyframeProperty.scale_y, 0, sx)
    seg.add_keyframe(KeyframeProperty.scale_y, dur_us, sy)
    # 轻微摇移（交替方向避免单调）
    p = preset["pan_x"] * pan_dir
    seg.add_keyframe(KeyframeProperty.position_x, 0, 0.0)
    seg.add_keyframe(KeyframeProperty.position_x, dur_us, p)
    # 入场淡入
    fi = preset["fade_in"]
    if fi and fi > 0:
        seg.add_keyframe(KeyframeProperty.alpha, 0, 0.0)
        seg.add_keyframe(KeyframeProperty.alpha, int(fi * SEC), 1.0)
    # 出场淡出
    fo = preset["fade_out"]
    if fo and fo > 0:
        seg.add_keyframe(KeyframeProperty.alpha, dur_us - int(fo * SEC), 1.0)
        seg.add_keyframe(KeyframeProperty.alpha, dur_us, 0.0)
    # 滤镜
    if preset.get("filter"):
        fname, intensity = preset["filter"]
        seg.add_filter(_enum(FilterType, fname), intensity)
    # 内置特效
    if preset.get("effect"):
        ename, params = preset["effect"]
        seg.add_effect(_enum(VideoSceneEffectType, ename), params)
    return seg


def apply_transition(seg, name, dur_s):
    """给片段挂转场（与上一片段衔接）。"""
    seg.transition = Transition(_enum(TransitionType, name), duration=int(dur_s * SEC))
    return seg


def apply_mask(seg, mask_name, cx=0.0, cy=0.0, w=0.5, h=0.5,
               ratio=1.0, rot=0.0, invert=False, feather=0.0, round_corner=0.0):
    """给片段挂蒙版（画中画 / 分屏用）。"""
    seg.mask = Mask(_enum(MaskType, mask_name).value, cx, cy, w, h, ratio, rot, invert, feather, round_corner)
    return seg


# ---------------------------------------------------------------------------
# 文字动画
# ---------------------------------------------------------------------------
def apply_text_animation(seg, intro=None, outro=None, loop=None):
    """给文本片段挂文字动画（入场 / 出场 / 循环）。"""
    if intro:
        seg.add_animation(_enum(TextIntro, intro))
    if outro:
        seg.add_animation(_enum(TextOutro, outro))
    if loop:
        seg.add_animation(_enum(TextLoopAnim, loop))
    return seg
