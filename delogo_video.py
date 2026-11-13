# -*- coding: utf-8 -*-
"""视频去水印（高斯模糊版 v2）：去除 CCTV13 台标(左上) + 底部标题条 + 右上央视网水印。

核心原理：
  对每个水印区域：crop → gblur(sigma=20) → overlay 叠回原位。
  使用单次 filter_complex 链式叠加全部区域（避免顺序多遍的临时文件和累积损失）。

关键坑（已解决）：
  ⚠️ crop 高度 ≤ ~25px 时，ffmpeg overlay 在非原点位置会失效并产生绿色伪影！
  ✅ 解决：每个框自动加 padding，确保源分辨率下高度 ≥ MIN_H (48px)。

用法：
  python delogo_video.py                          # 默认处理视频目录下第一个 mp4
  python delogo_video.py <video.mp4>              # 指定文件
  QE_DELOGO_SRC=<path> python delogo_video.py     # 环境变量指定

输出：<原名>_clean.mp4（原片不动）
"""
import os, sys, json, subprocess, glob

REF_W, REF_H = 1280, 720
WORK_ROOT = os.environ.get("SOURCE_DIR", os.path.join(WORK, "sources"))
SIGMA = 20       # 高斯模糊强度
MIN_H = 48       # crop 最小高度（低于此值 overlay 会失效+绿影，实测阈值 ~25px）
MIN_W = 48       # crop 最小宽度（保险）

# 基础框（1280x720 参考系，覆盖完整水印区域 + 足够边距）
# 运行时会自动加 padding 确保 >= MIN_H/MIN_W
BASE_BOXES_1280 = {
    "台标":       (20,   0,   240,  96),   # 左上 "CCTV 13 新闻"（加宽加高）
    "底部标题条":  (100, 560, 1080, 130),   # 底部标题条（全宽覆盖）
    "右上央视网":  (980,  0,   300,  96),   # 右上 "CCTV 央视网 CCTV.com"（加宽加高）
}


def resolve_src():
    if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
        return sys.argv[1]
    env = os.environ.get("QE_DELOGO_SRC")
    if env and os.path.exists(env):
        return env
    cand = sorted(glob.glob(os.path.join(WORK_ROOT, "视频", "*.mp4")))
    return cand[0] if cand else None


def probe_resolution(src):
    """返回 (width, height)"""
    out = subprocess.check_output([
        "ffprobe", "-v", "error",
        "-show_entries", "stream=width,height",
        "-select_streams", "v:0",
        "-of", "json", src,
    ], encoding="utf-8")
    s = json.loads(out)["streams"][0]
    return s["width"], s["height"]


def get_padded_boxes(src):
    """
    返回带 padding 的去水印框列表 [(tag, x, y, w, h), ...]
    每个框保证在源分辨率下 w >= MIN_W 且 h >= MIN_H，
    向四周均匀扩展（优先向下/向右，避免超出画面）。
    """
    sw, sh = probe_resolution(src)
    rx, ry = sw / REF_W, sh / REF_H

    # 可选自定义覆盖框
    cfg_path = os.path.join(os.path.dirname(src), "delogo_boxes.json")
    custom = []
    if os.path.exists(cfg_path):
        custom = json.load(open(cfg_path, encoding="utf-8"))

    boxes = []
    for name, (bx, by, bw, bh) in BASE_BOXES_1280.items():
        # 检查自定义覆盖
        overridden = False
        for c in custom:
            if c.get("tag") == name:
                boxes.append((name, int(c["x"]), int(c["y"]),
                              max(MIN_W, int(c["w"])), max(MIN_H, int(c["h"]))))
                overridden = True
                break
        if overridden:
            continue

        # 缩放到源分辨率
        x = max(0, int(bx * rx))
        y = max(0, int(by * ry))
        w = max(MIN_W, int(bw * rx))
        h = max(MIN_H, int(bh * ry))

        # 确保框不超出画面右/下边界（优先往左上缩进，保持尺寸）
        if x + w > sw:
            x = max(0, sw - w)
        if y + h > sh:
            y = max(0, sh - h)

        boxes.append((name, x, y, w, h))

    # 追加纯自定义
    for c in custom:
        if not any(b[0] == c["tag"] for b in boxes):
            boxes.append((c.get("tag", "自定义"), int(c["x"]), int(c["y"]),
                          max(MIN_W, int(c["w"])), max(MIN_H, int(c["h"]))))

    return boxes


def build_filter_complex(boxes):
    """
    构建单次 filter_complex：split + N个crop/gblur + 链式overlay
    返回 (filter_string, output_label)
    """
    n = len(boxes)
    if n == 0:
        return None, None

    # split = N+1 路（1路主画面 + N路裁剪），所有输出标签在同一行
    split_outputs = "".join(f"[t{i}]" for i in range(n))
    parts = [f"[0:v]split={n+1}[m]{split_outputs}"]

    # 每路裁剪+模糊
    for i, (tag, x, y, w, h) in enumerate(boxes):
        parts.append(
            f"[t{i}]crop={w}:{h}:{x}:{y},gblur=sigma={SIGMA},format=yuv420p[r{i}]"
        )

    # 链式叠加
    prev = "[m]"
    for i, (tag, x, y, w, h) in enumerate(boxes):
        if i < n - 1:
            parts.append(f"{prev}[r{i}]overlay={x}:{y}:format=auto[o{i}]")
            prev = f"[o{i}]"
        else:
            # 最后一个输出 [out]
            parts.append(f"{prev}[r{i}]overlay={x}:{y}:format=auto[out]")

    return ";".join(parts), "[out]"


def main():
    src = resolve_src()
    if not src:
        print("[delogo] 找不到源视频")
        sys.exit(1)

    print(f"[delogo] 源视频: {src}")
    sw, sh = probe_resolution(src)
    print(f"[delogo] 分辨率: {sw}x{sh}")

    boxes = get_padded_boxes(src)
    if not boxes:
        print("[delogo] 无去水印区域")
        sys.exit(1)

    for i, (tag, x, y, w, h) in enumerate(boxes):
        print(f"[delogo]   [{i+1}] {tag}: ({x},{y}) {w}x{h}")

    fc, map_label = build_filter_complex(boxes)
    if not fc:
        print("[delogo] filter 构建失败")
        sys.exit(1)

    base, ext = os.path.splitext(src)
    out = base + "_clean" + ext

    cmd = [
        "ffmpeg", "-y", "-i", src,
        "-filter_complex", fc,
        "-map", map_label,
        "-c:v", "libx264", "-crf", "18", "-preset", "veryfast",
        "-c:a", "copy",
        out,
    ]

    print(f"[delogo] 开始处理 -> {out}")
    r = subprocess.run(cmd, capture_output=True, text=True)

    if r.returncode != 0:
        print(f"[delogo] 处理失败!\n{(r.stderr or '')[-600:]}")
        sys.exit(1)

    out_size_mb = os.path.getsize(out) / (1024 * 1024)
    print(f"[delogo] 完成! -> {out} ({out_size_mb:.1f}MB)")


if __name__ == "__main__":
    main()
