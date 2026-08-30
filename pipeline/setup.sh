#!/usr/bin/env bash
# ============================================================
# 《原来是这样》流水线 - 服务器环境初始化脚本（可重跑）
# 目标：Ubuntu 20.04 / RTX 3060 / /hy-tmp 数据盘
# 注意：一切环境放 /hy-tmp（overlay 系统盘重启会重置）
# ============================================================
set -euo pipefail

BASE=/hy-tmp
CONDA_DIR=$BASE/miniconda3
ENV_DIR=$CONDA_DIR/envs/whisper
PROJECT=$BASE/whisperx_project
ENV_NAME=whisper
PY=$ENV_DIR/bin/python
PIP=$ENV_DIR/bin/pip

echo "==> [1/4] 系统依赖"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg

echo "==> [2/4] Miniconda（若未安装）"
if [ ! -x "$CONDA_DIR/bin/conda" ]; then
  wget -q https://mirrors.tuna.tsinghua.edu.cn/anaconda/miniconda/Miniconda3-latest-Linux-x86_64.sh -O $BASE/miniconda.sh
  bash $BASE/miniconda.sh -b -p $CONDA_DIR
  rm -f $BASE/miniconda.sh
fi
export PATH=$CONDA_DIR/bin:$PATH
conda config --add channels https://mirrors.tuna.tsinghua.edu.cn/anaconda/pkgs/main || true
conda config --set show_channel_urls yes || true

echo "==> [3/4] conda 环境"
if [ ! -x "$PY" ]; then
  conda create -y -n $ENV_NAME python=3.11
fi
$PIP config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple || true

echo "==> [4/4] Python 依赖（torch 固定 cu121，勿升级）"
$PIP install torch==2.5.1 torchaudio==2.5.1 faster-whisper pyannote.audio \
  jieba yt-dlp requests openai numpy pandas

echo "==> 项目目录"
mkdir -p $PROJECT/{audio,audio_new,outputs,analysis,tts_data,models}
mkdir -p $BASE/hf_cache

echo "==> 完成。使用前导出环境变量："
echo "    export HUGGINGFACE_HUB_TOKEN=<你的HF token>   # pyannote 说话人分离必需"
echo "    export DEEPSEEK_API_KEY=<你的key>             # 语义分配/拆分/分析必需"
echo "    cd $PROJECT && $PY pipeline.py --help"
