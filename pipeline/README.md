# 《原来是这样》内容加工流水线（服务器版）

围绕中文科普播客《原来是这样》（主持人：旭岽 / 子零）的一站式内容加工工具：
**音频 → 带说话人文稿 → 风格分析 → 新文案 / TTS 训练数据（GPT-SoVITS 声音克隆）**。

## 环境要求

- Linux + NVIDIA GPU（本项目目标机：Ubuntu 20.04 / RTX 3060 12GB / driver 535 → **必须 torch cu121**）
- Python 3.11（conda 环境，路径 `/hy-tmp/miniconda3/envs/whisper`）
- 全部路径位于 `/hy-tmp`（数据盘）；**勿放系统盘**（overlay 重启重置）

## 一键初始化

```bash
# 首次部署（装 conda/ffmpeg/依赖，幂等可重跑）
bash setup.sh

# 导出密钥（不落盘）
export HUGGINGFACE_HUB_TOKEN=hf_xxx     # pyannote 说话人分离必需
export DEEPSEEK_API_KEY=sk-xxx          # 语义分配/拆分/风格分析/文案必需
```

## 使用

```bash
PY=/hy-tmp/miniconda3/envs/whisper/bin/python
cd /hy-tmp/whisperx_project

# ① 处理一批喜马拉雅 URL（下载→16k→转写→分离→语义→文稿）
$PY pipeline.py --urls urls.txt --steps 1,2,3

# ② 处理已有音频目录
$PY pipeline.py --audio-dir audio_new --steps 1,2,3

# ③ 只重跑语义步骤
$PY pipeline.py --audio audio_new/548：银杏为什么这么臭？_16k.wav --ep 548 --steps 3

# ④ 风格分析（多期合并统计 + DeepSeek 报告）
$PY analyze.py --all

# ⑤ 仿风格文案生成
$PY generate_copy.py "车厘子"

# ⑥ TTS 训练数据切割（含说话人纯净度校验）
$PY make_tts_data.py --ep 548
```

## 流水线步骤

| 步骤 | 脚本 | 输入→输出 |
|---|---|---|
| 1 | `transcribe.py` | 音频 → `outputs/<期>/<期>_raw.json`（faster-whisper large-v3 词级时间戳） |
| 2 | `diarize.py` | 音频+raw → `<期>_with_switches.json`（pyannote 说话人分离+切换点标记） |
| 3 | `semantic_split.py` | switches → `<期>_final.json/.txt`（DeepSeek 分配说话人+拆分+短回应修正） |
| 4 | `analyze.py` | 多期 final → `analysis/stats.json` + `style_report.md` |
| 5 | `generate_copy.py` | 风格报告+官方案例 → `analysis/original_copy_*.txt` |
| 6 | `make_tts_data.py` | final.txt+音频 → `tts_data/<期>/<说话人>/*.wav` |

## 目录约定

```
/hy-tmp/whisperx_project/
├── config.py            # 全部路径/参数（根目录可被 PROJECT_ROOT 覆盖）
├── pipeline.py          # 主编排
├── transcribe.py diarize.py semantic_split.py   # 核心三步
├── analyze.py generate_copy.py make_tts_data.py # 三个分支
├── requirements.txt setup.sh
├── audio/ audio_new/    # 原始音频 / 新批次
├── outputs/<期号>/      # 按节目分目录的产物（_raw/_with_switches/_final.json+.txt）
├── analysis/            # 统计与报告
└── tts_data/<期号>/<说话人>/   # TTS 片段（xudong / ziling，可疑进 pending/）
```

## 注意事项

- **torch 勿升级**：驱动 535 只支持 cu121（torch 2.5.1）。安装任何包时显式 `pip install torch==2.5.1 torchaudio==2.5.1`，否则 pip 会拉 torch 2.8+（cu128）导致 CUDA 失效。
- **数据盘**：/hy-tmp 按量实例 24h 不启动会被清除；重要产物请及时下载备份。
- **说话人归一化**：历史写法（徐东/旭东/子琳/子玲/子凌…）自动归一到 旭岽/子零（`config.normalize_speaker`）。
- 说话人"旭岽/子零"由 DeepSeek 语义规则分配；pyannote 只提供切换点（声纹）。

## 历史产物迁移说明

本地（Windows）已清理合并过，上传到服务器时按本结构放置即可：
`outputs/` 下已按期号分目录（541/545/546/547/548/554/555/556），`analysis/`、`audio*/`、`tts_data/` 直接拷贝。
