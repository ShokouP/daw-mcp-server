# 发布与引流素材（LAUNCH）

三个开源仓库，互相引流：

| 项目 | 一句话 | 链接 |
|---|---|---|
| daw-mcp-server | 把 DAW 自动化/渲染/验证封装成 11 个 MCP tools | https://github.com/ShokouP/daw-mcp-server |
| open-music-production-corpus | 3,713 万 tokens 音乐制作/音频工程文本语料 | https://github.com/ShokouP/open-music-production-corpus |
| open-music-engineering-data | 鼓 Pattern + 结构标注 + DAWproject + 参数样本 | https://github.com/ShokouP/open-music-engineering-data |

## 30 秒版（朋友圈 / 即刻 / 群）

> 做音乐 AI 的可以看看：我们把三个东西开源了。
> 1）daw-mcp-server：11 个 MCP tools，让 AI Agent 真能读工程、套混音 patch、渲染、测 LUFS/频谱、闭环验证 FL/REAPER；
> 2）音乐制作语料库：3,713 万 tokens，23 个来源，含和声/对位/乐器法/总谱分析公版教材；
> 3）工程/符号数据：1 万个鼓 Pattern + 3 万条结构标注 + DAWproject 规范。
> 无 DAW 也能用 mock 跑通训练闭环。欢迎 Star。
> https://github.com/ShokouP/daw-mcp-server

## 英文版（Reddit r/LocalLLaMA, r/MachineLearning, HN Show）

**Title:** I built an MCP server that lets agents operate a DAW (REAPER/FL Studio) and verify mixes

**Body:**

We're building music-production AI and got tired of "generate a JSON patch and hope it's right".
So we open-sourced three projects:

1. **daw-mcp-server** — 11 MCP tools to read projects (.rpp/.dawproject), apply mix patches (track volume/pan/EQ/comp/sends/markers), render WAV (REAPER CLI or deterministic mock), measure peak/RMS/LUFS-approx/LRA/spectral centroid/bands/stereo width, and close the loop with `verify_patch` (apply → render baseline+patched → analyze → score vs intent). Works without a DAW via mock mode; live bridges for REAPER (ReaScript) and FL Studio (MIDI scripting).
   https://github.com/ShokouP/daw-mcp-server

2. **open-music-production-corpus** — 37.1M-token license-audited corpus for music production/audio engineering: Stack Exchange dumps, public-domain harmony/counterpoint/instrumentation/orchestration textbooks (Grove dictionary, Berlioz/Widor/Gevaert/Prout/Kitson...), Chinese Wikipedia music articles, arXiv abstracts, open audio-engineering docs. CC BY-SA 4.0 + permissive subset.
   https://github.com/ShokouP/open-music-production-corpus

3. **open-music-engineering-data** — 10,208 two-bar drum patterns (Groove MIDI derived), 30,336 structural boundaries (SALAMI), DAWproject spec, 900 parameter-patch samples.
   https://github.com/ShokouP/open-music-engineering-data

No DAW installed? `python tests/test_smoke.py` and `examples/training_loop.py` run entirely on the mock renderer.

Feedback welcome — especially from people who want adapters for Ableton/Ardour/Pro Tools.

## V2EX / 中文技术社区版

**标题：** 开源了一个 DAW MCP server：让 AI Agent 真的能操作 FL/REAPER 并验证混音

**正文：**

最近在做音乐制作 AI（DAWcoder），卡在两件事：模型输出混音参数后，怎么真正执行、怎么验证效果。
于是把中间层做成了 MCP server 并开源：daw-mcp-server（Apache-2.0）。

- 11 个 tools：读 .rpp/.dawproject、校验/套用混音 patch、渲染 WAV、分析 LUFS/频谱/立体声、闭环打分、live DAW 桥、telemetry 回流
- 无 DAW 也能跑：mock renderer + 指标分析，CI/训练闭环完整
- live 桥：REAPER ReaScript、FL Studio MIDI scripting（模板，需本机适配）
- 配套还放了两个数据库：3,713 万 tokens 音乐制作语料、1 万鼓 Pattern + 3 万结构标注

https://github.com/ShokouP/daw-mcp-server
https://github.com/ShokouP/open-music-production-corpus
https://github.com/ShokouP/open-music-engineering-data

欢迎试用/提 issue，尤其想加 Ableton / Ardour / Pro Tools 适配的。

## 发帖 checklist

- [x] GitHub repo public + description + 20 topics
- [x] Release（catchy 标题、安装说明、Star 徽章 + CTA）
- [x] README Star 徽章 + CTA + 生态互链
- [x] Homepage 指向 Release（可改为 Pages 落地页）
- [x] 三个仓库互相链接
- [x] DAW 接口清单文档（引流锚点：搜 "FL Studio MCP" / "REAPER MCP" 能找到）
- [ ] 发布到社区（需要账号，人工操作）：V2EX / 即刻 / Reddit / HN / 公众号
- [ ] 录 30 秒 demo GIF（mock 闭环或 live REAPER）
