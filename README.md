# daw-mcp-server

MCP server for **DAW automation, rendering and verification** — 把 DAW 能调用的接口（FL Studio MIDI scripting / REAPER ReaScript / DAWproject / 文件级工程）封装成 MCP tools，给 **训练闭环** 和 **推理验证** 用。

> 配套：语义/参数数据见 [open-music-engineering-data](https://github.com/ShokouP/open-music-engineering-data)；文本语料见 [open-music-production-corpus](https://github.com/ShokouP/open-music-production-corpus)。

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

## 安装

```bash
git clone https://github.com/ShokouP/daw-mcp-server
cd daw-mcp-server
python -m pip install -r requirements.txt
python tests/test_smoke.py          # 无 DAW 也能跑通
```

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
- `bridge_queue` 为空 → 使用内存 mock bridge；填写则启用文件队列桥（REAPER/FL 适配器）。

## MCP 客户端接入

**Claude Desktop / Claude Code**

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

**Codex / 其他 MCP 客户端**：同样以 `python -m daw_mcp.server --config ...` 作为 stdio server 启动。

**训练脚本直接调用**（不经 MCP 协议，直接 import）：

```python
from daw_mcp.tools import Context, dispatch
ctx = Context({"telemetry_path": "telemetry.jsonl"})
res = dispatch(ctx, "verify_patch", {"path": "song.rpp", "patch": patch,
                                    "intent": {"rms_dbfs": -1.5}})
```

也可用 HTTP JSON-RPC 调试：

```bash
python -m daw_mcp.server --http 8765 --config config.json
curl -s http://127.0.0.1:8765/health
```

## Live DAW 桥接

### REAPER

1. 安装 REAPER；Actions → Show action list → New action → Load ReaScript → 选 `adapters/reaper_bridge.lua`；
2. 改脚本里的 `QUEUE_DIR` 与 server 配置 `bridge_queue` 一致；
3. Run（脚本常驻），MCP 的 `bridge_call` / `render`（`render_cmd`）即可用。

### FL Studio

1. 把 `adapters/flstudio_bridge.py` 放到 `%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\daw_mcp\device_daw_mcp.py`；
2. 改 `QUEUE_DIR`；Options → MIDI settings → 选择该 controller 脚本；
3. `bridge_call` 走 `get_state` / `set_track` / `set_eq` / `set_comp`。
   FL 版本间 API 名称可能有差异，按你版本的 MIDI Scripting 文档校对。

## 训练闭环示例

```python
from daw_mcp.tools import Context, dispatch
import json

ctx = Context({"mock_tracks": [{"name": "Bass", "volume_db": 0.0, "pan": 0.0}]})
base = "examples/sample_project.rpp"
patch = {"ops": [{"op": "set_track", "track": "Bass", "fields": {"volume_db": -6, "pan": 0.0}},
                 {"op": "add_marker", "time_beats": 16, "name": "chorus"}]}
res = dispatch(ctx, "verify_patch", {"path": base, "patch": patch,
                                    "intent": {"rms_dbfs": -2.0}, "min_score": 0.0})
data = json.loads(res["content"][0]["text"])
print(data["score"], data["delta"])
```

- 训练数据生成：随机/模型采样 patch → `verify_patch` → 记录 `delta`/`score` 与 telemetry；
- 推理：模型输出 patch → `patch_validate` → `verify_patch` → 通过则 `bridge_call` 应用到 live DAW 或 `patch_apply` 保存副本；
- 失败反馈：`checks` 与 `delta` 可直接作为下一轮提示/奖励信号。

## 与 DAWcoder 的关系

- DAWcoder 模型输出三类 IR：mix / form / texture；
- MCP server 把 IR 变成可执行操作 + 可测量结果（渲染/指标），是"生成 → 验证 → 反馈"的中间层；
- 工程参数数据（Groove/SALAMI/DAWproject）见姊妹仓库。

## 许可

Apache-2.0（见 LICENSE）。REAPER/FL Studio 适配器脚本由你安装到对应 DAW，遵守各 DAW 的许可；不包含任何 DAW 本体或受版权手册。
