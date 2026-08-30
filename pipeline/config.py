# -*- coding: utf-8 -*-
"""
《原来是这样》播客内容加工流水线 - 集中配置

所有路径 / 参数都在这里。根目录默认 /hy-tmp/whisperx_project，
可用环境变量 PROJECT_ROOT 覆盖（例如本机调试时改到别处）。
API Key 一律走环境变量，不写入任何文件。
"""
import os
from pathlib import Path

# HuggingFace 国内镜像加速（模型下载）。可通过 HF_ENDPOINT 环境变量覆盖。
os.environ.setdefault("HF_ENDPOINT", os.environ.get("HF_ENDPOINT", "https://hf-mirror.com"))
# hf-mirror 不支持 Xet 存储协议（会 401），禁用后回退普通 HTTP 下载。
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

# 加载项目根目录 .env（若有）：密钥放这里比命令行安全、持久（/hy-tmp 数据盘）。
_ENV_FILE = Path(__file__).resolve().parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip().strip('"').strip("'"))

# ---------- 目录 ----------
BASE_DIR = Path(os.environ.get("PROJECT_ROOT", "/hy-tmp/whisperx_project"))
AUDIO_DIR = BASE_DIR / "audio"            # 原始音频
AUDIO_NEW_DIR = BASE_DIR / "audio_new"    # 新一批音频（含 16k 版本）
OUTPUT_DIR = BASE_DIR / "outputs"         # 产物，按节目分目录 outputs/<ep>/
ANALYSIS_DIR = BASE_DIR / "analysis"      # 风格分析产物
TTS_DIR = BASE_DIR / "tts_data"           # TTS 训练数据
HF_CACHE = Path(os.environ.get("HF_HOME", "/hy-tmp/hf_cache"))  # HuggingFace 模型缓存
MODEL_CACHE = BASE_DIR / "models"         # 本地模型缓存（pyannote 等）

# ---------- 密钥（环境变量，绝不落盘） ----------
HF_TOKEN = os.environ.get("HUGGINGFACE_HUB_TOKEN", "")       # pyannote 说话人分离必需
DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY", "")     # DeepSeek 语义分配/拆分/分析必需
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

# ---------- 模型 / 设备 ----------
WHISPER_MODEL = os.environ.get("WHISPER_MODEL", "large-v3")   # faster-whisper
DIARIZE_MODEL = os.environ.get("DIARIZE_MODEL", "pyannote/speaker-diarization-3.1")
DEVICE = os.environ.get("DEVICE", "")   # 留空自动检测
COMPUTE_TYPE = "float16"                # GPU 用 float16，CPU 自动降 int8


def detect_device():
    global DEVICE, COMPUTE_TYPE
    if not DEVICE:
        try:
            import torch
            DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            DEVICE = "cpu"
    if DEVICE == "cpu":
        COMPUTE_TYPE = "int8"
    return DEVICE


# ---------- 节目说话人 ----------
# 两个主持人；归一化表把历史多种写法统一
SPEAKER_MAIN = "旭岽"     # 知识输出型
SPEAKER_SUB = "子零"      # 捧哏/接梗型
SPEAKER_ALIASES = {
    SPEAKER_MAIN: {"旭岽", "徐东", "旭东", "徐岽"},
    SPEAKER_SUB: {"子零", "子琳", "子玲", "子凌", "子菱"},
}


def normalize_speaker(name: str) -> str:
    """把任意历史写法归一化为 旭岽 / 子零；声纹标签 SPEAKER_xx 原样保留。"""
    if not name:
        return "UNKNOWN"
    name = name.strip()
    for canon, aliases in SPEAKER_ALIASES.items():
        if name in aliases or any(a in name for a in aliases if len(a) >= 2):
            return canon
    return name


# ---------- 转写 / 分离参数 ----------
TRANSCRIBE_LANG = "zh"
VAD_FILTER = True           # silero VAD 过滤静音
TRANSCRIBE_BATCH_SIZE = int(os.environ.get("TRANSCRIBE_BATCH_SIZE", "16"))  # BatchedInferencePipeline 批大小（24G 显存可开大）
MIN_SPEAKERS = 2
MAX_SPEAKERS = 2

# ---------- DeepSeek 语义拆分参数 ----------
DEEPSEEK_BATCH = 40         # 每批交给 DeepSeek 的片段数
DEEPSEEK_TEMP = 0.1
SHORT_RESPONSES = ["是的", "没错", "对啊", "可不是", "就是", "对呀", "对", "是", "嗯", "欸", "哎", "好", "行"]

# ---------- TTS 切割参数 ----------
TTS_SKIP_START = 10.0       # 跳过开头（秒）
TTS_SKIP_END = 300.0        # 跳过结尾（秒）
TTS_MIN_DURATION = 1.5      # 最短片段（秒）
TTS_FILTER_KEYWORDS = ["片头", "片尾", "宣传", "广告", "订阅", "关注", "鸣谢"]


def ensure_dirs():
    for d in [AUDIO_DIR, AUDIO_NEW_DIR, OUTPUT_DIR, ANALYSIS_DIR, TTS_DIR, HF_CACHE, MODEL_CACHE]:
        d.mkdir(parents=True, exist_ok=True)
    return BASE_DIR
