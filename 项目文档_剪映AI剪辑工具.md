# 剪映 AI 剪辑工具 · 项目文档与规划底稿

> 用途：当前系统已写到这里，本文档是给**新会话重新规划整个项目**的交接底稿。包含技术架构、文件清单、各模块功能、已实现/未实现、已知 bug、以及所有待决策点。
> 最后更新：2026-08-03

---

## 0. 一句话定位

这是一个「用大模型当导演、自动生成剪映草稿」的工具。最早用《新闻联播》跑通端到端，现在主线改造成**探店短视频版**，并落地成一个可售卖的服务：**探店脚本 + 代剪**（闲鱼获客）。

核心卖点（已验证的判断）：**惊艳来自脚本的爆款结构（钩子→场景→亮点→价格→引导），不来自转场/卡点**；转场/滤镜剪映模板三秒套、最不值钱。护城河雏形 = 脚本爆款结构 + 稳定可复制。

---

## 1. 核心机制（必须先懂）

程序**不直接操控剪映软件**，而是用 `pyJianYingDraft`（来自 `capcut-mate/src`）**生成一个剪映「本地草稿」文件夹**（`draft_content.json` + 素材引用）。

用户操作：打开剪映 →「本地草稿」→ 看到排好的时间轴 → 手动点导出成片。

所以「自动剪辑」= 自动排好一条剪映时间轴。**约定的终点是「草稿为主」，程序不替用户导出成片**（也给用户留了手动精修空间）。

---

## 2. 整体数据流

### 2.1 通用内核（两套管线共用，`<剪映编辑器目录>`）
```
需求文档 + 素材转写稿
   → director.py（LLM 导演）       产出 EditPlan(JSON)
   → schemas.py（build_editplan）  校验 + 归一化
   → matcher.py（片段匹配）        解析成 ResolvedClip（path, start, dur）
   → renderer.py（剪映草稿渲染）   写剪映本地草稿
   → [配音 step2_tts.py / edge-tts]  旁白 mp3 铺进音轨
```

### 2.2 新闻管线（已完整端到端，但已非主线）
`step1_genplan.py → step2_tts.py → step3_render.py → step4_full.py`

### 2.3 探店管线（当前主线，仅验证到「出方案」）
`run_tanchuang.py`（导演提示词换探店范式 + 逐段转写 + 双层脚本渲染） → `plan_tanchuang.json` + `脚本_探店.md`
→ **配音 + 渲染成剪映草稿：尚无专属入口脚本**，目前靠通用 `renderer.py`，需接 `step2` 配音（见 §9 待修）。

---

## 3. 目录与文件清单

### 3.1 内核：`<剪映编辑器目录>`
| 文件 | 作用 |
|---|---|
| `config.py` / `editor_config.json` | 配置加载（LLM key、路径、pyJianYingDraft 源码路径注入） |
| `director.py` | LLM 导演：需求+转写 → EditPlan JSON（含 JSON 容错修复） |
| `schemas.py` | EditPlan 数据结构 / 校验 / 归一化（`build_editplan`） |
| `ingest.py` | 素材摄入 + 语音转写（逐段缓存，whisper） |
| `matcher.py` | 片段匹配：clip 直达 或 search_query 检索扩展 |
| `renderer.py` | **剪映草稿渲染**（真正写草稿的地方，功能见 §5） |
| `pipeline.py` | 串联全流程（待确认是否仍用） |
| `web.py` | 疑似 Web 接口（待确认功能） |
| `requirements.txt` / 测试脚本 | 依赖与自测 |

### 3.2 项目：``
| 文件 | 作用 |
|---|---|
| **`run_tanchuang.py`** | **探店运行器（主线）**：导演提示词探店版 + 逐段转写 + 双层脚本渲染 |
| `run_a.py` / `run_all.py` | 旧 / 新闻版运行入口 |
| `step1_genplan.py` ~ `step5_full_v2.py` / `step_studio_filter.py` / `step_compose_news.py` / `step3_download.py` | 新闻相关步骤（演播室识别、网上下载素材等） |
| `render_script.py` | 从已有 `plan.json` 渲染「双层可读脚本」md（无需重跑导演） |
| `gen_data_videos.py` / `generate_bar.py` / `make_broll_draft.py` | 新闻数据图 / 柱状图 / 网上下载素材草稿 |
| `merge.py` / `quick_edit.py` | 旧工具 |
| `req_tanchuang.txt` / `plan_tanchuang*.json` / `脚本_探店.md` | 探店样例输入/产出 |
| 业务文档若干 `.md` | 见 §11 |

---

## 4. 各模块详解

### 4.1 `director.py` — LLM 导演
- **新闻版 `SYSTEM_PROMPT`**（文件内置）：含三条红线——①画面定位禁演播室/主持人（演播室识别）；②投资建议话术红线（"建议关注/建仓" 等禁写）；③检索词来源隔离（禁出现"新闻联播/CCTV" 等字面）。
- **探店版 `TANCHUANG_PROMPT`**（`run_tanchuang.py` 内重写，覆盖 `director.SYSTEM_PROMPT`）：探店范式（钩子→场景→亮点→价格→引导）；**混合素材**——有原声优先采用店名/菜品/价格/感受词，静音段靠需求单；需求单驱动，不依赖语音转写。
- `LLMDirector.direct(req, index)`：拼 user_prompt（需求 + 转写稿上下文）→ 调 OpenAI 兼容接口（当前 DeepSeek，`response_format=json_object`，`temperature=0.2`）→ `build_editplan` 校验 → 失败重试 2 次 + 启发式 JSON 修复（裸双引号/未转义换行）。
- EditPlan 结构：`meta / intro / background / modules[] / bgm`。

### 4.2 `schemas.py` — 校验归一化
- `default_editplan` + `build_editplan`：缺 `modules` 抛错，其余填默认。
- ⚠️ **已知 bug**：`default_editplan` 里 `resolution` 写死 `"16:9"`，探店 `1080×1920` 实为 9:16。渲染按 `width/height` 走、不受影响，但该字段误导（首次真渲染核对）。

### 4.3 `ingest.py` — 素材摄入 / 转写
- `MaterialIngestor._ingest_one` 逐段独立，whisper 转写。
- **探店改造**（`run_tanchuang.py`）：逐段 `try`，失败/无语音 → 标记 `merged=[]`（静音），**互不拖累**。适配真实探店「部分有原声、部分静音空镜」的混合素材。
- 备注：手头 `_data/seg_*.mp4` 实测**无音轨**，验证用的是静音占位；真实有声音镜头会被实际转写。

### 4.4 `matcher.py` — 片段匹配
- `ResolvedClip(module, material_path, start_sec, duration_sec)`。
- 两类：① `clip` 给定 `start_sec/duration_sec` 直达；② `search_query` → 在 `segments` 里关键词打分 + 向两侧扩展至目标时长（默认 15s，上限 40s）。
- 新闻特有：`dropped_by_studio` 演播室识别裁空整段跳过。

### 4.5 `renderer.py` — 剪映草稿渲染（见 §5）
### 4.6 `step2_tts.py` — 配音
- 微软 `edge-tts` 合成旁白 mp3：音色 `zh-CN-YunxiNeural`（云熙男声，探店可换女声），语速 `+6%`，每模块一个 mp3，失败重试最多 4 次；`ffprobe` 测时长写 `durations.json`。
- ⚠️ 依赖未装在受管 python，需用**系统 python** 跑（`python.exe`）。

### 4.7 `pipeline.py` / `web.py`
- `pipeline.py`：串联全流程（新会话需确认是否仍作为主入口）。
- `web.py`：疑似提供 Web 接口（功能待确认）。

---

## 5. 渲染层功能逐项（`renderer.py` 真实已实现的）

| # | 功能 | 实现要点 |
|---|---|---|
| 1 | 画布 / 分辨率 | 读 `meta.width/height/fps`；探店 `1080×1920` 竖屏，新闻 `1280×720` |
| 2 | 主视频轨 | 片头(可选) + 各模块片段顺序拼接；`source_timerange`（源截取起点）+ `target_timerange`（时间轴位置/时长） |
| 3 | 视频原声消音 | 默认 `volume=0`，空出音轨给旁白；仅模块 `keep_audio=true` 保留原声 |
| 4 | 画布纯色背景 | `background_filling("color", …)`，颜色来自 `background.color`（默认深蓝）；**仅纯色底，不是调色滤镜** |
| 5 | 文本轨·标题（顶部大字） | `title` → 文本轨「文本_标题」，`transform_y=-0.6` 顶部，黄字+黑描边 ⚠️ 偏新闻味（见 §10-①） |
| 6 | 文本轨·字幕（底部大字） | `subtitle` → 文本轨「文本_字幕」，`transform_y=0.6` 底部，白字+黑描边 ⚠️ 对静音观看有价值（见 §10-①） |
| 7 | 音频轨·旁白 | 每模块 `narration_mp3`（edge-tts 生成）按该段时间区间精确铺到「音频_旁白」轨 |
| 8 | 音频轨·BGM | `bgm.enabled=true` 且 `bgm_path` 文件存在 → 整段平铺到「音频_BGM」轨 |
| 9 | 片头（intro） | 有片头视频文件用视频；无视频但有标题文字 → 用画布底色生成纯文字片头 |

---

## 6. 已实现 vs 未实现（美化层）

**已实现**：消音、纯色底、标题、字幕、旁白轨、BGM、片头。

**未在渲染层实现（阶段 2 才补，勿以为已能用）**：
- ❌ 转场（片段间目前硬切）
- ❌ 滤镜 / 调色（仅纯色底，无暖色调等画质美化）
- ❌ 卡点（BGM 整段平铺，没做节奏对齐）
- ❌ 分屏 / 画中画
- ❌ 数字弹出 / 数据图表：`data` 字段导演会产出，但渲染层完全没消费（新闻版数据图是另一条独立脚本 `generate_bar.py`，未接进此草稿）

---

## 7. 探店业务适配（已落地的交付物）

- **需求单格式**：`探店信息收集表.md`（达人 30 秒填版，删了文件名/逐段编号，镜头对号由运营补）。
- **双层脚本**：`脚本_探店.md` = 拍摄规划版（分镜+口播，达人拍前用）+ 剪辑执行版（大字/字幕/节奏/BGM，机器用）。`render_script.py` 从 plan 渲染。
- **售卖结构**：脚本=大脑+独立卖品；免费/低价换数据 → 闲鱼低价真实单换数据+案例。
- **护城河**：脚本爆款结构 + 稳定可复制。

---

## 8. 运行环境要点（坑）

1. **受管 python（3.13.12）缺 `opencc` 等依赖** → 跑 `universal_editor` 流水线必须用**系统 python**：`python.exe`。
2. **`edge-tts` 未装在受管 python** → 配音同样用系统 python。
3. **`pyJianYingDraft` 来自 `capcut-mate/src`**（`editor_config.json` 的 `paths.capcut_src`），由 `ensure_pyjianying()` 注入 `sys.path`。
4. **草稿输出目录**：`<剪映草稿根目录>`（剪映本地草稿根）。
5. ⚠️ **`editor_config.json` 明文存了 LLM api_key 和 pexels api_key**——新会话若公开/提交需注意脱敏。

---

## 9. 已知 bug / 待修

1. **`resolution` 字段误标 "16:9"**（§4.2），探店应为 9:16。渲染按宽高走不受影响，但字段误导。
2. **`step3_render.py` 调用 `render(..., narration_mp3=...)` 但 `renderer.render()` 签名不接受该参数** → 新闻渲染入口很可能直接报错（需确认/修复；通用渲染是逐 clip 挂 `narration_mp3`，不是整体传一个 mp3）。
3. **探店无专属「配音 + 渲染」入口脚本** —— `run_tanchuang.py` 只产出 plan + 脚本 md，要成剪映草稿还差一步接 `step2_tts` + `renderer.render`。这是新会话必须先补的闭环缺口。
4. **第 5、6 项（标题/字幕）探店去留**（见 §10-①）。

---

## 10. 给新会话的规划输入（关键决策 / 开放问题）

> 以下是要「重新规划整个项目」时必须拍板的点。

**① 第 5、6 项（顶部大字标题 / 底部字幕）探店要不要？**
- 用户判断：这两项偏新闻味，视频剪辑不需要。
- 顾问修正：顶部「大字标题」确属新闻播报味，探店可去掉；但**底部「字幕」（旁白上屏）对探店很重要**——大量用户静音刷视频，没字幕完播率下降。建议：可去掉顶部标题，**保留底部字幕**（或做成可开关的配置项）。新会话决定。

**② 产品定位**：做「通用剪映 AI 剪辑工具」还是「探店垂直」？是否把新闻/探店两套提示词与渲染统一到一个通用编辑器（用「模板/范式」切换）？

**③ 渲染美化层优先级**：转场 / 暖色调滤镜 / 卡点 / 分屏，先做哪个？（判断：都属「地板」非护城河，建议最低成本补「暖色调滤镜 + 1 个轻转场 + 卡点 BGM」基线，别堆工程量。）

**④ 配音 + 渲染入口脚本补全**：把探店「run_tanchuang → 配音 → 渲染成剪映草稿」打通一个一键脚本。

**⑤ 画面识别（VLM）要不要上、何时上**：真实探店素材多、达人懒得标镜头时，是否自动打标？判断：v1 不做，让达人在信息收集表顺手标 / 运营补；上量后再用便宜本地/小模型，且耗时只跟镜头数挂钩不跟视频大小挂钩（先本地 ffmpeg 场景检测切镜头 → 每镜头抽 1 帧 → 识别）。

**⑥ 信息收集表是否网页化**：当前 markdown 复制粘贴版能用；冷启动验证后，是否做成网页表单/问卷提升转化 + 自动生成需求单。

**⑦ 闲鱼获客 → 交付闭环自动化**：接单后能否半自动（需求单进 → 脚本/草稿出 → 回传），减少人工。

**⑧ 安全/配置**：api_key 明文、配置与代码分离、是否上版本库。

---

## 11. 现有可直接复用的产物（省力清单）

**代码**
- `run_tanchuang.py`（探店运行器，可用，验证过静音 + 混合素材）
- `render_script.py`（plan → 双层脚本 md）
- `plan_tanchuang_mixed.json` / `plan_tanchuang_mixed_脚本.md` / `脚本_探店.md`（李嬢嬢芋儿鸡样例）
- `req_tanchuang.txt`（样例需求单）

**业务文档**
- `探店信息收集表.md`（达人填的需求单模板）
- `免费招募话术.md`（小红书限流失败，转闲鱼前的历史）
- `闲鱼店铺_搭建指南.md` + `闲鱼上架文案_可直接粘贴.txt`（当前获客主渠道）
- `探店双层脚本_交付模板.md`（产品定位 + 三层卖法）
- `小红书新号布置指南.md` + `小红书头像背景图提示语.md`（早期引流尝试）
- `探店剪辑服务_行动规划.md`（含战略定调、阶段路线图、免费换数据飞轮）
- `流水线使用说明.md`（用法）

**素材**
- `_xianyu_assets/Clean_3D_clay_render_illustrat_2026-08-03T15-17-04.png`（闲鱼封面图）

---

## 12. 一句话给新会话

> 内核（director → schemas → matcher → renderer + tts）已能生成剪映草稿；探店主线只验证到「出方案+脚本」，配音+渲染成片闭环还没补；渲染美化层（转场/滤镜/卡点/分屏/数据图）全是空的；生意侧已想清（探店脚本+代剪、闲鱼获客、护城河=脚本结构），但**零真实付费案例**。新会话应重新规划：① 打通探店一键出片闭环；② 决定 5/6 项与美化层优先级；③ 把新闻/探店统一成可配置通用工具；④ 用闲鱼真实单验证并迭代。
