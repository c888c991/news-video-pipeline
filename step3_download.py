# -*- coding: utf-8 -*-
"""Step3.5: 读 plan.json 每个模块的 stock_query → 调 Pexels 视频搜索 → 下载到 _stock/。
写 _stock/index.json 记录模块号到文件映射，供 step5 编排时取用。
用系统 python 跑（只用标准库 + urllib，无需装包）。"""
import os, json, sys, time, urllib.request, urllib.parse
WORK = os.path.dirname(os.path.abspath(__file__))

PLAN = os.path.join(WORK, "plan.json")
CFG = os.path.join(os.environ.get("JIANYING_EDITOR", os.path.join(WORK, "_editor")), "editor_config.json")
OUT_DIR = os.path.join(WORK, "_stock")
INDEX = os.path.join(OUT_DIR, "index.json")
os.makedirs(OUT_DIR, exist_ok=True)

cfg = json.load(open(CFG, encoding="utf-8"))
px = cfg.get("pexels", {})
API_KEY = px.get("api_key", "")
PER_PAGE = px.get("search_per_page", 3)
MIN_DUR = px.get("min_duration_sec", 5)
MAX_DUR = px.get("max_duration_sec", 20)
TARGET_W = px.get("target_width", 1280)
TARGET_H = px.get("target_height", 720)

if not API_KEY:
    # 无 key：若已有旧缓存则保留（让 compose 仍能用到网上下载画面），否则写空
    if os.path.exists(INDEX) and os.path.getsize(INDEX) > 0:
        try:
            old = json.load(open(INDEX, encoding="utf-8"))
            if old.get("clips"):
                print(f"[stock] 未配置 pexels.api_key，保留旧缓存({len(old['clips'])}个)，跳过下载")
                sys.exit(0)
        except Exception:
            pass
    print("[stock] 未配置 pexels.api_key，且无旧缓存，跳过素材下载")
    json.dump({"clips": {}}, open(INDEX, "w", encoding="utf-8"), ensure_ascii=False)
    sys.exit(0)

plan = json.load(open(PLAN, encoding="utf-8"))
modules = plan.get("modules", [])
index = {"clips": {}}  # {"1": {"path": "...", "duration": 7.0, "query": "train"}, ...}

def search_video(query):
    """调 Pexels 搜索，返回最佳视频的下载链接+时长"""
    url = "https://api.pexels.com/videos/search?" + urllib.parse.urlencode({
        "query": query, "per_page": PER_PAGE, "orientation": "landscape"
    })
    req = urllib.request.Request(url, headers={
        "Authorization": API_KEY,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    })
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        print(f"  [stock] 搜索失败({query}): {e}")
        return None
    for v in data.get("videos", []):
        dur = v.get("duration", 0)
        if dur < MIN_DUR or dur > MAX_DUR:
            continue
        # 优先选接近目标分辨率的文件
        best = None
        for f in v.get("video_files", []):
            w, h = f.get("width", 0), f.get("height", 0)
            if w >= TARGET_W and h >= TARGET_H:
                best = f
                break
        if not best:
            # 退而求其次选最大的
            files = [f for f in v.get("video_files", []) if f.get("link")]
            if files:
                best = max(files, key=lambda f: f.get("width", 0) * f.get("height", 0))
        if best and best.get("link"):
            return {"link": best["link"], "duration": float(dur), "id": v.get("id")}
    return None

def download(url, dest):
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
            f.write(resp.read())
        return True
    except Exception as e:
        print(f"  [stock] 下载失败: {e}")
        return False

for m in modules:
    i = m["id"]
    q = (m.get("stock_query") or "").strip()
    if not q:
        print(f"[stock] 模块{i}「{m.get('name')}」无 stock_query，跳过")
        continue
    dest = os.path.join(OUT_DIR, f"stock_{i:02d}.mp4")
    # 已下载则跳过（缓存）
    if os.path.exists(dest) and os.path.getsize(dest) > 10000:
        dur = os.path.getsize(dest) / (500 * 1024)  # 粗估
        index["clips"][str(i)] = {"path": dest, "query": q, "duration": round(dur, 1), "cached": True}
        print(f"[stock] 模块{i}「{m.get('name')}」已有缓存: {q}")
        continue
    print(f"[stock] 模块{i}「{m.get('name')}」搜索: {q}")
    result = search_video(q)
    if not result:
        print(f"  [stock] 未找到合适素材，跳过")
        continue
    print(f"  [stock] 命中(id={result['id']}, {result['duration']:.0f}s)，下载中...")
    if download(result["link"], dest):
        index["clips"][str(i)] = {
            "path": dest, "query": q,
            "duration": result["duration"], "pexels_id": result["id"]
        }
        print(f"  [stock] 已保存: {os.path.basename(dest)} ({result['duration']:.0f}s)")
    time.sleep(0.5)  # 接口限速礼貌

json.dump(index, open(INDEX, "w", encoding="utf-8"), ensure_ascii=False, indent=2)
n = len(index["clips"])
print(f"STOCK_DONE 共下载 {n}/{len(modules)} 个扩展片段 -> {OUT_DIR}")
