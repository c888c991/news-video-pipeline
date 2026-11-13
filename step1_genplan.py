# -*- coding: utf-8 -*-
"""Step1: 跑 director 生成含 narration 的 plan，存 plan.json。用系统 python 跑。"""
import sys, json, os
import os
sys.path.insert(0, os.environ.get("JIANYING_EDITOR", os.path.join(WORK, "_editor")))
from config import load_config
from ingest import MaterialIngestor, discover_videos
from director import LLMDirector
WORK = os.path.dirname(os.path.abspath(__file__))

cfg = load_config()
log = lambda m: print(m, flush=True)
ing = MaterialIngestor(cfg, log)
MATERIAL_FOLDER = os.environ.get("MATERIAL_FOLDER", os.environ.get("MATERIAL_FOLDER", os.path.join(WORK, "materials")))
index = ing.ingest(discover_videos(MATERIAL_FOLDER))
REQ_FILE = os.environ.get("REQ_FILE", os.path.join(WORK, "req_a.txt"))
req = open(REQ_FILE, encoding="utf-8").read()
plan = LLMDirector(cfg, log).direct(req, index)

PLAN_OUT = os.environ.get("PLAN_OUT", os.path.join(WORK, "plan.json"))
with open(PLAN_OUT, "w", encoding="utf-8") as f:
    json.dump(plan, f, ensure_ascii=False, indent=2)

print("PLAN_SAVED modules=", len(plan.get("modules", [])))
for m in plan.get("modules", []):
    n = m.get("narration") or ""
    print(" -", m.get("name"), "|", (n[:50] + "...") if len(n) > 50 else n)
