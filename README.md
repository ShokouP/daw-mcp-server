# daw-mcp-server

[![GitHub stars](https://img.shields.io/github/stars/ShokouP/daw-mcp-server?style=social)](https://github.com/ShokouP/daw-mcp-server)
[![Release](https://img.shields.io/github/v/release/ShokouP/daw-mcp-server)](https://github.com/ShokouP/daw-mcp-server/releases)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue)](https://www.python.org/)
[![License](https://img.shields.io/badge/license-Apache--2.0-lightgrey)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-model--context--protocol-purple)](https://modelcontextprotocol.io/)

> 如果这个项目对你有用，欢迎点个 Star，让更多做音乐 AI / Agent 的人找到它。

MCP server for **DAW automation, rendering and verification** — 把 DAW 能调用的接口（FL Studio MIDI scripting / REAPER ReaScript / DAWproject / 文件级工程）封装成 MCP tools，给 **训练闭环** 和 **推理验证** 用。

## 生态（三个仓库）

| 仓库 | 内容 |
|---|---|
| **daw-mcp-server**（本仓库） | DAW 自动化/渲染/验证 MCP tools（11 个） |
| [open-music-production-corpus](https://github.com/ShokouP/open-music-production-corpus) | 3,713 万 tokens 音乐制作/音频工程文本语料（23 源，含和声/对位/乐器法/总谱分析） |
| [open-music-engineering-data](https://github.com/ShokouP/open-music-engineering-data) | 鼓 Pattern（10,208）、结构标注（30,336）、DAWproject 规范、参数样本 |

## 能力

| Tool | 作用 |
|---|---|
| `daw_status` | 服务配置、桥接模式、可用 DAW |
| `daw_apis` | 各 DAW 可调用 API/命令清单（FL/REAPER/DAWproject/Ardour/PT/Bitwig…） |
| `project_read` | 读 `.rpp` / `.dawproject`：轨道、音量/声像、send、标记、tempo |
| `patch_validate` | 校验 DAWcoder IR patch（ops 结构 + 参数范围） |
| `patch_apply` | 把 patch 应用到 `.rpp` 副本（音轨/send/marker；EQ/压缩交由 live bridge） |
| `render` | 渲染 WAV：配置的 DAW 命令（如 `reaper -renderproject`）或确定性 mock 渲染 |
| `analyze` | WAV 指标：peak/RMS/LUFS-approx/LRA/频谱质心/频带占比/立体声宽度/相关度 |
| `compare` | 两个 WAV 的指标差 |
| `verify_patch` | **闭环**：apply → render baseline+patched → analyze → 按 intent 打分 |
| `bridge_call` | 调用 live DAW 桥（get_state/set_track/set_eq/set_comp/add_marker/transport） |
| `telemetry_append` | 工程师操作/验证结果写入 JSONL（训练数据回流） |

详见 [docs/DAW-API-SURVEY.md](docs/DAW-API-SURVEY.md)。

## 30 秒上手

```bash
git clone https://github.com/ShokouP/daw-mcp-server
cd daw-mcp-server
python -m pip install -r requirements.txt
python tests/test_smoke.py     # 无需安装 DAW，全部测试应通过
python examples/training_loop.py
```

接入 MCP 客户端（Claude / Codex / DSH）：

```json
{
  "mcpServers": {
    "daw": {
      "command": "python",
      "args": ["-m", "daw_mcp.server", "--config", "C:/path/to/config.json"]
    }
  }
}
```

训练脚本直接 import：

```python
from daw_mcp.tools import Context, dispatch
ctx = Context({"telemetry_path": "telemetry.jsonl"})
res = dispatch(ctx, "verify_patch", {"path": "song.rpp", "patch": patch,
                                    "intent": {"rms_dbfs": -1.5}})
```

## 架构

```
MCP client (Claude Code / DSH / Codex / Claude Desktop)
        │  stdio JSON-RPC (MCP)
        ▼
daw-mcp-server
  ├── tools.py        tool schemas + dispatch
  ├── rpp.py          .rpp 解析/改写（音轨音量/声像/send/marker）
  ├── dawproject.py   DAWproject ZIP+XML 读取
  ├── render.py       真实命令渲染 / mock 渲染
  ├── metrics.py      WAV 测量（numpy）
  └── bridge.py       队列桥协议（.req.json → .res.json + index.json）
        │  文件队列
        ▼
adapters/reaper_bridge.lua   （REAPER 内 ReaScript 常驻循环）
adapters/flstudio_bridge.py  （FL Studio MIDI scripting 脚本）
```

无 DAW 时用 **mock 模式**（默认）：文件级补丁 + 确定性合成渲染 + 指标分析，训练/CI 可完整跑闭环。

## 配置

```json
{
  "render_cmd": "",
  "bridge_queue": "C:/daw_mcp_queue",
  "bridge_timeout": 15,
  "telemetry_path": "daw_telemetry.jsonl",
  "mock_tracks": [{"name": "Drums", "volume_db": 0.0, "pan": 0.0}]
}
```

- `render_cmd` 为空 → mock 渲染；填 `reaper -renderproject {project}` 之类 → 真实渲染。
- `bridge_queue` 为空 → 内存 mock bridge；填写则启用文件队列桥（REAPER/FL 适配器）。

## Live DAW 桥接

- **REAPER**：Actions → Load ReaScript → `adapters/reaper_bridge.lua`，改 `QUEUE_DIR` 与 server `bridge_queue` 一致，运行即常驻。
- **FL Studio**：`adapters/flstudio_bridge.py` 复制到 `...\Image-Line\FL Studio\Settings\Hardware\daw_mcp\device_daw_mcp.py`，改 `QUEUE_DIR`，选中该 controller 脚本。
- 细节与注意事项见 [adapters/README.md](adapters/README.md)。

## 测试状态

- `tests/test_smoke.py`：rpp 解析/改写、patch 校验、mock 渲染、WAV 指标、闭环打分、MCP stdio 握手/tools 列表/调用 → **ALL TESTS PASSED**
- `examples/training_loop.py`：30 个 patch 的生成-验证-记录闭环；自洽 intent 30/30 通过
- 开发环境未安装 FL Studio / REAPER：live 适配器为模板（协议与 mock 已验证），需在装有 DAW 的机器上加载校对

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

## 许可

Apache-2.0（见 LICENSE）。适配器脚本安装到对应 DAW，不包含 DAW 本体或受版权手册。

## 相关模型

DAWcoder 4B（音乐制作参数模型，Qwen3.5-4B 基座，GGUF Q4_K_M）：https://huggingface.co/Shokou1/qwen3.5-4B-dawcoder
