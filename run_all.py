# -*- coding: utf-8 -*-
"""一键运行全流程：新闻视频 → 消音+AI旁白+数据图+素材合并 → 剪映草稿。
正式用：改下方 CONFIG 区四项，然后 `python run_all.py`。用系统 python 跑。"""
import os, subprocess, sys
WORK = os.path.dirname(os.path.abspath(__file__))

# ===== 配置区（每次换视频只改这里）=====
CONFIG = {
    "MATERIAL_FOLDER": os.environ.get("MATERIAL_FOLDER", os.path.join(WORK, "materials")),  # 新闻原片所在文件夹
    "REQ_FILE": os.environ.get("REQ_FILE", os.path.join(WORK, "req.txt")),                  # 需求/分镜要求
    "DRAFT_NAME": os.environ.get("DRAFT_NAME", "news_draft"),                               # 剪映草稿名
    "BOX_DIR": os.environ.get("BOX_DIR", os.path.join(WORK, "broll")),                      # B-roll 素材箱
}
SYS_PY = sys.executable
VENV_PY = os.environ.get("VENV_PY", sys.executable)   # 若有虚拟环境，指到它的 python.exe
SCRIPTS = WORK
# 剪映草稿编辑器目录（依赖 pyJianYingDraft 的那套封装），按需设置环境变量
PROJECT = os.environ.get("JIANYING_EDITOR", os.path.join(WORK, "_editor"))

env = os.environ.copy()
env.update(CONFIG)

STEPS = [
    ("[1/8] 生成plan(导演+旁白+数据)", SYS_PY, "step1_genplan.py"),
    ("[2/8] TTS合成(news+data旁白)", VENV_PY, "step2_tts.py"),
    ("[3/8] 生成数据图mp4", VENV_PY, "gen_data_videos.py"),
    ("[4/8] 合并数据图+B-roll", SYS_PY, "merge.py"),
    ("[5/8] 演播室识别裁剪(模板匹配)", SYS_PY, "step_studio_filter.py"),
    ("[6/8] 下载网图扩展画面(Pexels→_stock)", SYS_PY, "step3_download.py"),
    ("[7/8] 画面合编(新闻+本地+网上共用旁白)", SYS_PY, "step_compose_news.py"),
    ("[8/8] 渲染草稿", SYS_PY, "step5_full_v2.py"),
]

os.chdir(PROJECT)
for desc, py, script in STEPS:
    print(desc + "...")
    r = subprocess.run([py, os.path.join(SCRIPTS, script)], env=env)
    if r.returncode != 0:
        print("失败：" + desc)
        sys.exit(1)
print("\n完成！打开剪映 Pro → 本地草稿找：「" + CONFIG["DRAFT_NAME"] + "」")
