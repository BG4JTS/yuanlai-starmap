#!/bin/bash
# ============================================================
# 4090 实例一键部署：《原来是这样》流水线 + 星图
# 前提: 本脚本与数据包放在 /hy-tmp 下
#   deploy_4090.sh
#   whisperx_backup_final.tar.gz   (已备份的 outputs/清单/token/星图)
#   whisperx_project/              (代码目录，或本脚本所在即项目)
# 用法: bash deploy_4090.sh [--continue]
#   --continue  部署完成后自动续跑剩余批次(567,569)
# ============================================================
set -uo pipefail

BASE=/hy-tmp
PROJECT=${PROJECT:-$BASE/whisperx_project}
BACKUP=${BACKUP:-$BASE/whisperx_backup_final.tar.gz}

echo "==> [0/6] 环境检测"
uname -a
nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader 2>/dev/null || echo "WARN: 无 GPU 或驱动未就绪"

# 定位 python（优先 conda/venv，其次系统）
find_py() {
    for c in \
        "$HOME/miniconda3/envs/whisper/bin/python" \
        "$BASE/miniconda3/envs/whisper/bin/python" \
        "$HOME/miniconda3/bin/python" \
        "$BASE/miniconda3/bin/python" \
        "python3"; do
        if command -v "$c" >/dev/null 2>&1; then echo "$c"; return; fi
    done
}
PY=$(find_py)
PIP="$PY -m pip"
echo "  Python: $PY ($($PY --version 2>&1))"

echo "==> [1/6] 系统依赖 (ffmpeg)"
apt-get update -qq 2>/dev/null || true
DEBIAN_FRONTEND=noninteractive apt-get install -y -qq ffmpeg 2>/dev/null || echo "  WARN: ffmpeg 安装失败(可能需手动)"

echo "==> [2/6] Python 依赖（torch 用实例自带，不降级）"
$PIP config set global.index-url https://pypi.tuna.tsinghua.edu.cn/simple 2>/dev/null || true
$PIP install -q faster-whisper pyannote.audio jieba yt-dlp requests numpy pandas scikit-learn 2>&1 | tail -2
$PIP install -q sentence-transformers 2>&1 | tail -1 || echo "  WARN: sentence-transformers 安装失败(星图嵌入降级 TF-IDF)"

echo "==> [3/6] 数据解压"
mkdir -p "$PROJECT"
if [ -f "$BACKUP" ]; then
    tar xzf "$BACKUP" -C "$PROJECT"
    echo "  已解压备份到 $PROJECT"
else
    echo "  WARN: 未找到 $BACKUP（需手动上传数据包）"
fi

echo "==> [4/6] 星图 asset（vis-network，离线渲染用）"
mkdir -p "$PROJECT/assets"
if [ ! -s "$PROJECT/assets/vis-network.min.js" ]; then
    wget -q -T 30 -O "$PROJECT/assets/vis-network.min.js" \
        https://cdn.jsdelivr.net/npm/vis-network@9.1.2/dist/vis-network.min.js \
        && echo "  vis-network.min.js $(stat -c%s "$PROJECT/assets/vis-network.min.js" 2>/dev/null || echo '?')B" \
        || echo "  WARN: 下载失败，星图将尝试 CDN"
fi

echo "==> [5/6] GPU 验证"
$PY -c "import torch; print('  torch', torch.__version__, '| cuda', torch.cuda.is_available(), '|', torch.cuda.get_device_name(0) if torch.cuda.is_available() else 'NO-GPU')" 2>&1 | tail -1
$PY -c "import faster_whisper, pyannote.audio; print('  faster-whisper', faster_whisper.__version__, '| pyannote', pyannote.audio.__version__)" 2>&1 | tail -1

echo "==> [6/6] 完成"
echo "  数据期数: $(ls -d "$PROJECT"/outputs/*/ 2>/dev/null | wc -l) 期目录"
echo "  续跑批次: cd $PROJECT && $PY batch_ingest.py --range 567,569 --steps 1,2 --batch-size 5"
echo "  刷新星图: cd $PROJECT && $PY build_starmap.py"

if [ "${1:-}" = "--continue" ]; then
    echo "==> 自动续跑剩余批次 ..."
    cd "$PROJECT" && $PY batch_ingest.py --range 567,569 --steps 1,2 --batch-size 5
    echo "==> 续跑完成，刷新星图 ..."
    cd "$PROJECT" && $PY build_starmap.py
fi
echo "DONE"
