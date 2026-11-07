# DAW 可调用接口清单（自动化 / 参数 / 渲染）

本文件是 `daw-mcp-server` 的调研记录：列出各 DAW 能做什么、怎么调、局限在哪，以及本 MCP server 如何桥接。

## 总览

| DAW | 外部控制方式 | 读参数 | 写参数 | 渲染 | 工程文件 | 适合 MCP？ |
|---|---|---|---|---|---|---|
| **FL Studio** | MIDI scripting（Python，在 FL 内运行）+ Piano roll scripting | 轨道音量/声像/静音、插件参数、pattern/note、transport | 混音器、插件参数、piano roll notes、transport | 无官方 CLI（GUI Export） | .flp 二进制（无官方 API） | ✅ 需 queue/file 桥 |
| **REAPER** | ReaScript（Lua/EEL2/Python，在 REAPER 内运行）、CLI、Web Remote、OSC | 轨道/发送/FX 全参数、标记、tempo map、渲染设置 | 同上 | ✅ CLI `-renderproject` | ✅ .rpp 文本 | ✅ 最成熟 |
| **DAWproject** | 文件交换（ZIP+XML，MIT） | 轨道/通道/设备/自动化 | 整工程（转换器） | ❌（需 DAW） | ✅ 开放格式 | ✅ 文件级读写 |
| **Ardour** | Lua 脚本（Ardour 内）、OSC、headless CLI | 轨道/处理器/自动化/transport | 大部分会话状态 | ✅ CLI | ✅ .ardour XML | ✅（需安装） |
| **Ableton Live** | Max for Live（Live Object Model）、Remote Scripts（Python，Live 内） | transport/track/device/clip | 同上 | 无官方 CLI | .als（gzip XML，非官方） | ⚠️ 无外部 API |
| **Pro Tools** | Pro Tools Scripting SDK（官方，Win/macOS） | 大量 session 操作 | 同上 | ✅ bounce via SDK | .ptx 专有 | ✅ 需 SDK/Pro Tools |
| **Bitwig** | Java Controller API（Bitwig 内）、DAWproject | 设备/轨道参数 | 同上 | 无 CLI | .bwproject（DAWproject） | ⚠️ 需控制器脚本 |
| **Logic Pro** | Scripter MIDI FX（JS）、AppleScript UI | 有限 | 有限 | 无官方 CLI | .logicx（专有） | ❌（macOS only） |
| **Cubase** | 无官方脚本 API | 有限（DAWproject import/export） | 有限 | 无 CLI | .cpr 二进制 | ⚠️ 仅文件交换 |

## FL Studio（MIDI scripting API，Python）

在 FL 内运行（Options → MIDI settings → Controller type → 选择脚本），可调：

**transport**
- `transport.getSongPos()`, `transport.setSongPos(pos)`, `transport.getTempo()`
- `transport.start()`, `transport.stop()`, `transport.setLoopMode(mode)`
- `transport.globalTransport(command, value)`（走 FL 的全局命令，如播放/停止/录音）

**mixer（混音台）**
- `mixer.trackCount()`, `mixer.getTrackName(i)`, `mixer.setTrackName(i, name)`
- `mixer.getTrackVolume(i)` / `mixer.setTrackVolume(i, v)`（0–1 归一，视版本）
- `mixer.getTrackPan(i)` / `mixer.setTrackPan(i, v)`（-1..1）
- `mixer.isTrackMuted(i)` / 静音相关、`mixer.selectTrack(i)`
- 路由（send）：通过 mixer 路由/插件参数，脚本 API 覆盖有限

**channels（通道/乐器）**
- `channels.channelCount()`, `channels.getChannelName`, `channels.setChannelName`
- `channels.getChannelVolume/ Pan`, `channels.setChannelVolume/ Pan`
- `channels.muteChannel(i, mute)`, `channels.selectChannel(i)`

**plugins（插件参数，最重要的自动化面）**
- `plugins.getPluginCount()`, `plugins.getPluginName`, `plugins.getTrackPlugins(i)`
- `plugins.getParamCount(plugin)`, `plugins.getParamName(index, plugin)`
- `plugins.getParamValue(index, plugin)`, `plugins.setParamValue(value, index, plugin)`
- 参数值可为归一 0..1 或原生值（按版本/参数类型）

**pattern / playlist / arrangement**
- `patterns.patternCount()`, `patterns.getPatternName`, `patterns.setPatternName`
- `playlist.getPlaylistLength()`, `playlist.getTrackCount()`, clip API（版本相关）
- `arrangement.currentTime`, `arrangement.addAutoTimeMarker(pos, name)`

**piano roll scripting（`.pyscript`，Tools → Scripting）**
- `flpianoroll.score.noteCount()`, `score.getNote(i)`, `score.addNote(...)`, `score.deleteNote(...)`
- `score.setNotePitch/Time/Velocity(...)`, marker API（版本相关）

**MIDI 消息**
- `OnMidiMsg(event)`：`event.status/data1/data2/handled`，用于把外部 MIDI/虚拟端口消息变成控制命令
- `OnIdle()`：轮询桥接队列（本仓库 `adapters/flstudio_bridge.py` 用这个思路）

**局限**
- FL 无官方 headless CLI，无法在纯命令行渲染；.flp 二进制无官方 API（社区 `PyFLP`，GPL-3.0）。
- 脚本运行在 FL 进程内，外部 → FL 需要桥（文件队列 / 虚拟 MIDI 端口 / loopMIDI）。

## REAPER（自动化能力最强）

**ReaScript API（Lua / EEL2 / Python；`reaper.*` 约 2000 函数）**

工程/轨道：
- `reaper.CountTracks(0)`, `reaper.GetTrack(0, i)`, `reaper.GetSetMediaTrackInfo_String(tr, "P_NAME", ...)`
- `reaper.GetMediaTrackInfo_Value(tr, "D_VOL" | "D_PAN" | "B_MUTE" | "I_SOLO" | "B_MAINSEND")`
- `reaper.SetMediaTrackInfo_Value(tr, parm, value)`
- `reaper.GetTrackNumSends(tr, 0)` / `reaper.GetTrackSendInfo_Value(tr, 0, snd, "D_VOL")` / `reaper.SetTrackSendInfo_Value(...)`

FX 参数（EQ/压缩器自动化核心）：
- `reaper.TrackFX_GetCount(tr)`, `reaper.TrackFX_GetFXName(tr, fx, "")`
- `reaper.TrackFX_GetNumParams(tr, fx)`, `reaper.TrackFX_GetParamName(tr, fx, p, "")`
- `reaper.TrackFX_GetParam(tr, fx, p)`, `reaper.TrackFX_SetParam(tr, fx, p, value)`
- `reaper.TrackFX_GetParamNormalized`, `reaper.TrackFX_SetParamNormalized(tr, fx, p, norm)`
- `reaper.TrackFX_GetFormattedParamValue(tr, fx, p, "")`（显示值，如 "3.0 dB"）

标记/区间/transport：
- `reaper.AddProjectMarker2(0, false, pos, 0, name, -1, 0)`
- `reaper.EnumProjectMarkers2(0, i)`, `reaper.CountProjectMarkers(0)`
- `reaper.Master_GetTempo()`, `reaper.SetCurrentBPM(0, bpm, false)`
- `reaper.Main_OnCommand(action_id, 0)`：例如播放 1007、停止 1016、播放/停止 40044、渲染 41824（依赖版本，需在 Action List 确认）
- `reaper.Main_SaveProject(0, false)`, `reaper.GetProjectPath("")`

循环/渲染/其他：
- `reaper.defer(fn)`（常驻脚本循环）、`reaper.time_precise()`
- `reaper.GetSet_LoopTimeRange(...)`、`reaper.GetSet_ArrangeView2(...)`
- 渲染可搭配 CLI：`reaper -renderproject project.rpp`

**命令行（可直接由 MCP server 调）**
- `reaper -new`, `reaper -open <file>`, `reaper -saveas <file>`, `reaper -renderproject <file>`
- `reaper -batchconvert <files>`, `reaper -nosplash`, `reaper -ignoreerrors`
- 注意：`-renderproject` 使用工程内的 render settings（输出路径/格式需预先配置）；批量渲染更推荐 ReaScript + `GetSetProjectInfo` 设置后再 render。

**Web Remote Control / OSC**
- Preferences → Control/OSC/web → Web browser interface：局域网 HTTP 控制（`/_/` 页面 + action/id 端点）
- OSC：`/track/{n}/volume`、`/track/{n}/pan`、`/transport/play` 等（需在 OSC 设备里配）

**文件格式**
- `.rpp` 是文本（本仓库 `daw_mcp/rpp.py` 解析/改写 track VOLPAN、sends、markers）
- 用 `ProjectConverter` / `DawVert` 可与 `.dawproject` 互转

## DAWproject（开放工程格式，MIT）

- 规范：https://github.com/bitwig/dawproject（`Project.xsd`）
- 格式：ZIP 内 `project.xml` + 媒体引用；Bitwig / Studio One / Cubase 原生支持导入导出，REAPER 通过转换器
- 可读写主体：tracks/channels/devices/automation/transport/markers
- 本 MCP server：`project_read` 读取概要；写入建议用转换器（不做二进制未定义行为的改写）

## Ardour（Windows/Linux 可用）

- Lua 脚本：`Session:get_tracks()`, `Track:set_gain/set_pan`, processor 参数、automation、transport
- OSC：`/ardour/...`（track gain/pan/mute/solo、transport）
- headless：`ardour -N`；导出 via CLI/Lua
- `.ardour` 是 XML

## Ableton Live

- Max for Live（Live Object Model：`live_set tracks N devices ...`）可读写参数
- Remote Scripts（Python，Live 内运行）可控制 mixer/transport/clip
- 无官方外部 API/CLI；`.als` 为 gzip XML 非官方

## Pro Tools（官方 Scripting SDK）

- Pro Tools Scripting SDK（PTSL）：会话操作、transport、bounce/export、编辑命令
- 需要安装 Pro Tools 与 SDK 工具链；适合企业级渲染/校验闭环

## Bitwig / Logic / Cubase

- Bitwig：Java Controller API（Bitwig 内）+ DAWproject
- Logic Pro：Scripter（JS MIDI FX）+ AppleScript UI 自动化；macOS only
- Cubase：无官方脚本 API；通过 DAWproject 导入导出交换

## 本 MCP server 的桥接策略

| 场景 | 方式 | 工具 |
|---|---|---|
| 无 DAW（CI/训练） | mock renderer + 文件解析 | `render`（mock）、`project_read`、`patch_apply`、`verify_patch` |
| REAPER | ReaScript 队列桥 (`adapters/reaper_bridge.lua`) | `bridge_call`、`render`（render_cmd=`reaper -renderproject {project}`） |
| FL Studio | MIDI-script 队列桥 (`adapters/flstudio_bridge.py`) | `bridge_call`（get_state/set_track/set_eq/set_comp） |
| 文件级 | .rpp 读写、DAWproject 概要 | `project_read`、`patch_apply`、`patch_validate` |
| 测量 | WAV 分析 | `analyze`、`compare`、`verify_patch` |
| 数据回流 | JSONL telemetry | `telemetry_append` |

> 安全建议：训练/推理闭环使用工程副本渲染（`verify_patch` 默认写 `daw_mcp_work/`），不要直接覆盖用户正在编辑的工程。
