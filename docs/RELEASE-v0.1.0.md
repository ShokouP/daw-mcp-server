# DAW MCP Server v0.1.0 — 让 AI Agent 真正操作 DAW

[![GitHub stars](https://img.shields.io/github/stars/ShokouP/daw-mcp-server?style=social)](https://github.com/ShokouP/daw-mcp-server)

把 DAW 可调用接口封装成 **11 个 MCP tools**，用于训练闭环与推理验证：
`daw_status`、`daw_apis`、`project_read`、`patch_validate`、`patch_apply`、`render`、`analyze`、`compare`、`verify_patch`、`bridge_call`、`telemetry_append`。

如果这个项目对你有用，欢迎给仓库点个 Star，让更多做音乐 AI / Agent 的人找到它。

## 覆盖的 DAW 接口（调研结果见 docs/DAW-API-SURVEY.md）

| DAW | 可调用方式 | 本仓库支持 |
|---|---|---|
| REAPER | ReaScript API（Lua/EEL2/Python）、CLI `-renderproject`、Web Remote、OSC、`.rpp` 文本 | `adapters/reaper_bridge.lua` 队列桥 + `render_cmd` + `rpp.py` 文件级读写 |
| FL Studio | MIDI scripting（Python，设备脚本）、Piano roll scripting、插件参数 API | `adapters/flstudio_bridge.py` 队列桥（模板） |
| DAWproject | 开放 ZIP+XML（MIT，Bitwig/Studio One/Cubase，REAPER 经转换器） | `dawproject.py` 读取（tracks/markers/tempo） |
| Ardour / Pro Tools / Ableton / Bitwig / Logic / Cubase | Lua+OSC / Scripting SDK / M4L / Controller API / Scripter / 文件交换 | 调研记录 + 桥接建议 |

## 训练/推理闭环

```
模型输出 IR patch
  → patch_validate（结构+范围）
  → patch_apply（写 .rpp 副本）
  → render（真实 DAW 命令 或 mock 渲染）
  → analyze（peak/RMS/LUFS-approx/LRA/频谱/立体声）
  → compare / verify_patch（按 intent 打分）
  → bridge_call（通过则应用到 live DAW）
  → telemetry_append（训练数据回流）
```

`examples/training_loop.py`：30 个 patch 的生成-验证-记录闭环（无 DAW 也可跑通）；自洽 intent 验证 30/30 通过。

## 30 秒上手

```bash
git clone https://github.com/ShokouP/daw-mcp-server
cd daw-mcp-server
python -m pip install -r requirements.txt
python tests/test_smoke.py      # ALL TESTS PASSED（无需安装 DAW）
python examples/training_loop.py
```

**MCP 客户端（Claude/Codex/DSH）**：

```json
{"mcpServers": {"daw": {"command": "python",
  "args": ["-m", "daw_mcp.server", "--config", "C:/path/to/config.json"]}}}
```

**训练脚本直接 import**：

```python
from daw_mcp.tools import Context, dispatch
ctx = Context({"telemetry_path": "telemetry.jsonl"})
res = dispatch(ctx, "verify_patch", {"path": "song.rpp", "patch": patch, "intent": {...}})
```

## 生态

- 文本语料：[open-music-production-corpus](https://github.com/ShokouP/open-music-production-corpus) — 3,713 万 tokens，23 源，含和声/对位/乐器法/总谱分析
- 工程/符号数据：[open-music-engineering-data](https://github.com/ShokouP/open-music-engineering-data) — 10,208 鼓 Pattern / 30,336 结构边界 / DAWproject / 参数样本
- 发布与引流素材：[docs/LAUNCH.md](https://github.com/ShokouP/daw-mcp-server/blob/main/docs/LAUNCH.md)

## 限制

- mock 渲染是确定性合成（用于 CI/训练闭环），不是真实音质；
- FL Studio 无官方 headless 渲染/工程 API，live 控制依赖脚本桥；
- REAPER 适配器需在 REAPER 内加载并校对 action/param 名称；
- 训练闭环默认只写 `daw_mcp_work/` 副本，不覆盖用户工程。
