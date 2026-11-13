# -*- coding: utf-8 -*-
"""演播室画面识别：opencv 模板匹配识别 CCTV13 新闻联播演播室典型特征。
- 模板 1：左上角 CCTV13 台标
- 模板 2：底部"中国中央电视台/新闻联播/日期"标题条

策略：
  1. ffmpeg 一次抽帧（2 fps）到临时目录
  2. 每帧过 NCC 模板匹配（cv2.matchTemplate + TM_CCOEFF_NORMED）
  3. 演播室 = (标题条 ≥ 0.70) 或 (台标 ≥ 0.65 且 标题条 ≥ 0.55)
  4. 合并连续演播室区间，从片段时间码里掐头去尾

集成在 step1 之后、step5 之前。读 plan.json，输出 plan_studio_filtered.json。
被裁得太空（< 2s）的模块标记 clip=None + dropped_by_studio=True，由 matcher 跳过。

阈值可通过环境变量 STUDIO_THRESHOLD_TL / STUDIO_THRESHOLD_BOT 调。"""
import os, sys, json, subprocess, tempfile, glob
import cv2
import numpy as np
WORK = os.path.dirname(os.path.abspath(__file__))


def cv2_imread_unicode(path):
    """绕过 cv2.imread 对 Windows 中文路径的 bug：用 numpy 读字节再 imdecode。
    先 normpath 把正斜杠转反斜杠（np.fromfile 对 Windows 中文正斜杠路径会失败）。"""
    try:
        path = os.path.normpath(path)
        buf = np.fromfile(path, dtype=np.uint8)
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
        return img
    except Exception as e:
        return None


def _resolve_anchor():
    """自动发现演播室 anchor 图：环境变量 > 默认路径 > 新闻素材文件夹。
    多个候选都找不到时回退到默认路径（触发降级提示，不阻断流程）。"""
    candidates = []
    if os.environ.get("STUDIO_ANCHOR"):
        candidates.append(os.environ["STUDIO_ANCHOR"])
    candidates.append(os.path.join(WORK, "assets", "ScreenShot_2026-07-30_211823_101.png"))
    candidates.append(os.path.join(os.environ.get("SOURCE_DIR", os.path.join(WORK, "sources")), "演播室镜头.png"))
    candidates.append(os.path.join(os.environ.get("SOURCE_DIR", os.path.join(WORK, "sources")), "测试/演播室镜头.png"))
    for c in candidates:
        if c and os.path.exists(c):
            return c
    return candidates[0]  # 回退到默认（会触发降级提示）


ANCHOR_PATH = _resolve_anchor()

# ----- 配置 -----
PLAN_IN = os.path.join(WORK, "plan.json")
PLAN_OUT = os.path.join(WORK, "plan_studio_filtered.json")
MATERIAL_FOLDER = os.environ.get("MATERIAL_FOLDER", os.environ.get("MATERIAL_FOLDER", os.path.join(WORK, "materials")))
TH_TL = float(os.environ.get("STUDIO_THRESHOLD_TL", "0.65"))
TH_BOT = float(os.environ.get("STUDIO_THRESHOLD_BOT", "0.70"))
SAMPLE_FPS = 2.0

# 模板（懒加载）
_tpl_topleft = None
_tpl_bottom = None


def load_templates():
    """从 anchor 图裁出两个模板区域。anchor 必须是 1280x720，否则缩放。"""
    global _tpl_topleft, _tpl_bottom
    if _tpl_topleft is not None:
        return
    anchor = cv2_imread_unicode(ANCHOR_PATH)
    if anchor is None:
        raise RuntimeError(f"读不到 anchor 图: {ANCHOR_PATH}")
    h, w = anchor.shape[:2]
    print(f"[studio_filter] anchor 图: {w}x{h}")
    if (w, h) != (1280, 720):
        anchor = cv2.resize(anchor, (1280, 720))
    # 左上角 CCTV13 台标（约 5-55 行 x 5-130 列）
    _tpl_topleft = anchor[5:55, 5:130]
    # 底部标题条（约 640-715 行 x 80-1170 列，含"中国中央电视台 新闻联播 日期"）
    _tpl_bottom = anchor[640:715, 80:1170]
    print(f"[studio_filter] 模板就绪: 台标{_tpl_topleft.shape[:2]} 标题条{_tpl_bottom.shape[:2]}")
    # self-check：模板在 anchor 自身的匹配分数应该接近 1.0
    s_tl = match_score(anchor, _tpl_topleft)
    s_bot = match_score(anchor, _tpl_bottom)
    print(f"[studio_filter] anchor self-match: 台标={s_tl:.3f} 标题条={s_bot:.3f} (期望接近 1.0)")


def match_score(img, tpl):
    """NCC 归一化相关系数匹配分数 [-1, 1]"""
    if img.shape[0] < tpl.shape[0] or img.shape[1] < tpl.shape[1]:
        return 0.0
    res = cv2.matchTemplate(img, tpl, cv2.TM_CCOEFF_NORMED)
    _, max_val, _, _ = cv2.minMaxLoc(res)
    return float(max_val)


def is_studio_frame(img):
    """综合判断该帧是否是演播室画面"""
    s_tl = match_score(img, _tpl_topleft)
    s_bot = match_score(img, _tpl_bottom)
    # 强信号：底部标题条高匹配（演播室特征最显著）
    if s_bot >= TH_BOT:
        return True, s_tl, s_bot
    # 弱信号：台标和标题条都中等匹配（防御性）
    if s_tl >= TH_TL and s_bot >= 0.55:
        return True, s_tl, s_bot
    return False, s_tl, s_bot


def extract_frames(video_path, start_sec, dur_sec, out_dir):
    """ffmpeg 一次抽帧到 out_dir，按 SAMPLE_FPS 抽，自动缩放到 1280x720"""
    out_pattern = os.path.join(out_dir, "f%04d.png")
    cmd = ["ffmpeg", "-y", "-ss", f"{start_sec:.3f}", "-i", video_path,
           "-t", f"{dur_sec:.3f}", "-vf", f"fps={SAMPLE_FPS},scale=1280:720",
           out_pattern]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode != 0:
        print(f"  [studio_filter] 抽帧失败: {r.stderr.decode()[-200:]}")
    return sorted(glob.glob(os.path.join(out_dir, "f*.png")))


def trim_studio(video_path, start_sec, dur_sec, tmp_root):
    """识别演播室区间，返回新 (start_sec, dur_sec) + intervals 记录"""
    tmp_dir = tempfile.mkdtemp(prefix="studio_", dir=tmp_root)
    try:
        frames = extract_frames(video_path, start_sec, dur_sec, tmp_dir)
        if not frames:
            print(f"  [studio_filter] 时段[{start_sec:.1f}+{dur_sec:.1f}s] 抽帧为空，保留原样")
            return (start_sec, dur_sec, [])
        n = len(frames)
        dt = 1.0 / SAMPLE_FPS
        flags = []
        for fpath in frames:
            img = cv2_imread_unicode(fpath)
            if img is None:
                flags.append(False)
                continue
            studio, s_tl, s_bot = is_studio_frame(img)
            flags.append(studio)
        # 合并连续演播室区间
        intervals = []
        i = 0
        while i < n:
            if not flags[i]:
                i += 1
                continue
            j = i
            while j < n and flags[j]:
                j += 1
            intervals.append((i * dt, j * dt))
            i = j
        if not intervals:
            print(f"  [studio_filter] 时段[{start_sec:.1f}+{dur_sec:.1f}s] 无演播室帧，保留")
            return (start_sec, dur_sec, [])
        # 合并间隔 < 1 秒的（容错）
        merged = [intervals[0]]
        for cur in intervals[1:]:
            last = merged[-1]
            if cur[0] - last[1] < 1.0:
                merged[-1] = (last[0], cur[1])
            else:
                merged.append(cur)
        # 掐头去尾：演播室在头/尾砍掉，保留外景段
        head_cut = 0.0
        tail_cut = 0.0
        if merged[0][0] < dur_sec * 0.4:
            head_cut = merged[0][1]
        if merged[-1][1] > dur_sec * 0.6:
            tail_cut = dur_sec - merged[-1][0]
        kept = dur_sec - head_cut - tail_cut
        if kept < 2.0:
            print(f"  [studio_filter] 时段[{start_sec:.1f}+{dur_sec:.1f}s] 裁后 {kept:.1f}s 太空，整段跳过")
            return (None, None, merged)
        new_start = start_sec + head_cut
        new_dur = kept
        iv_str = [(round(a, 1), round(b, 1)) for a, b in merged]
        print(f"  [studio_filter] 时段[{start_sec:.1f}+{dur_sec:.1f}s] 演播室区间={iv_str} "
              f"→ 砍头{head_cut:.1f}s砍尾{tail_cut:.1f}s → 新[{new_start:.1f}+{new_dur:.1f}s]")
        return (new_start, new_dur, merged)
    finally:
        # 清理临时帧
        for f in glob.glob(os.path.join(tmp_dir, "f*.png")):
            try: os.remove(f)
            except: pass
        try: os.rmdir(tmp_dir)
        except: pass


def main():
    try:
        load_templates()
    except Exception as e:
        print(f"[studio_filter] ⚠️ anchor 图读取失败: {e}")
        print(f"[studio_filter] 跳过演播室裁剪，plan 原样透传（演播室镜头可能保留）")
        print(f"[studio_filter] 把演播室画面截图存到 {ANCHOR_PATH} 或设环境变量 STUDIO_ANCHOR 后重跑即可启用裁剪")
        plan = json.load(open(PLAN_IN, encoding="utf-8"))
        json.dump(plan, open(PLAN_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return
    plan = json.load(open(PLAN_IN, encoding="utf-8"))
    modules = plan.get("modules", [])
    src_videos = sorted(glob.glob(os.path.join(MATERIAL_FOLDER, "*.mp4")))
    if not src_videos:
        print("[studio_filter] 素材目录无 mp4，跳过裁剪，plan 原样输出")
        json.dump(plan, open(PLAN_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
        return
    src_video = src_videos[0]
    print(f"[studio_filter] 源视频: {src_video}")
    tmp_root = tempfile.gettempdir()
    for m in modules:
        mid = m.get("id", "?")
        name = m.get("name", "?")
        clip = m.get("clip")
        if not clip:
            print(f"[studio_filter] 模块{mid}「{name}」无 clip 字段，跳过")
            continue
        s = clip.get("start_sec")
        d = clip.get("duration_sec")
        if s is None or d is None:
            print(f"[studio_filter] 模块{mid}「{name}」clip 不全，跳过")
            continue
        new_s, new_d, intervals = trim_studio(src_video, s, d, tmp_root)
        m["studio_trim"] = {
            "original": {"start_sec": s, "duration_sec": d},
            "trimmed_intervals": intervals,
            "thresholds": {"topleft": TH_TL, "bottom": TH_BOT},
        }
        if new_s is None:
            m["clip"] = None
            m["studio_trim"]["action"] = "dropped"
            m["dropped_by_studio"] = True
        else:
            m["clip"]["start_sec"] = round(new_s, 2)
            m["clip"]["duration_sec"] = round(new_d, 2)
            m["studio_trim"]["action"] = "trimmed"
    json.dump(plan, open(PLAN_OUT, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
    n_drop = sum(1 for m in modules if m.get("dropped_by_studio"))
    n_trim = sum(1 for m in modules if (m.get("studio_trim") or {}).get("action") == "trimmed")
    print(f"\n[studio_filter] 完成 → {PLAN_OUT}（裁剪{n_trim}个、跳过{n_drop}个）")


if __name__ == "__main__":
    main()