# DAW 适配器

`daw-mcp-server` 默认运行在 **mock 模式**（无需安装 DAW）。要让 MCP 真正操作 DAW，需要把下面的适配器加载到对应 DAW 里，并把 server 配置的 `bridge_queue` 指向同一个目录。

> 本仓库提供的适配器是**模板**：开发环境未安装 FL Studio / REAPER，队列协议与 mock bridge 已通过测试；适配器里的 DAW API 调用需在你本机对应版本上验证（FL 版本差异较大）。

## REAPER：`reaper_bridge.lua`

1. 打开 REAPER → Actions → Show action list…
2. New action → Load ReaScript… → 选择 `reaper_bridge.lua`
3. 编辑脚本第 20 行附近：`local QUEUE_DIR = "C:/daw_mcp_queue"`
4. 运行脚本（常驻，通过 `reaper.defer` 轮询）
5. server 配置：

```json
{"bridge_queue": "C:/daw_mcp_queue"}
```

支持的 action：`get_state` / `set_track` / `set_eq` / `set_comp` / `add_marker` / `transport`。
（`set_eq`/`set_comp` 会匹配轨道第一个 FX 的参数名：gain/freq/q/thresh/ratio/attack/release。）

## FL Studio：`flstudio_bridge.py`

1. 复制到：
   `%USERPROFILE%\Documents\Image-Line\FL Studio\Settings\Hardware\daw_mcp\device_daw_mcp.py`
2. 编辑 `QUEUE_DIR` 与 server 的 `bridge_queue` 一致
3. FL：Options → MIDI settings → 选择 `daw_mcp` controller 脚本
4. 支持的 action：`get_state` / `set_track` / `set_eq` / `set_comp` / `set_send` / `add_marker` / `transport`

注意：FL 的 MIDI scripting API 在不同版本间命名/取值范围有差异（如 `mixer.setTrackVolume` 的 0–1 或 dB），请用你版本的脚本 API 文档校对。

## 渲染

- REAPER：server 配置 `"render_cmd": "reaper -renderproject {project}"`（输出路径/格式用工程的 render settings；需要时先用 ReaScript 设置）
- FL Studio：无官方 headless 渲染，使用 GUI 导出；训练闭环建议 mock 或 REAPER/Ardour 渲染，或用 FL 导出的 WAV 走 `analyze`
- 无 DAW：默认 mock renderer（确定性合成，用于 CI/训练）

## 安全

- `verify_patch` 只写 `daw_mcp_work/` 下的副本，不覆盖工程；
- 生产使用时建议在工程副本上操作，或先 `saveas` 再 apply。
