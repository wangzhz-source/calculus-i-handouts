#!/bin/sh
set -eu

ROOT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT_DIR"

if ! git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
  echo "发布失败：当前目录不是 Git 仓库。" >&2
  exit 1
fi

if ! git remote get-url origin >/dev/null 2>&1; then
  echo "发布失败：尚未配置 origin 远程仓库。" >&2
  exit 1
fi

branch=$(git branch --show-current)
if [ -z "$branch" ]; then
  echo "发布失败：当前处于 detached HEAD。" >&2
  exit 1
fi

echo "[1/5] 同步远程分支 origin/$branch"
git pull --ff-only origin "$branch"

echo "[2/5] 校验全部 16 讲"
python3 -B tools/release_next.py --audit

echo "[3/5] 执行本周发布"
python3 -B tools/release_next.py --apply

git add \
  release-state.json \
  published/README.md \
  published/manifest.json \
  published/lectures

if git diff --cached --quiet; then
  echo "没有新的发布变更。"
  exit 0
fi

lecture=$(grep -Eo '[0-9]+' release-state.json | tail -n 1)
lecture=$(printf '%02d' "$lecture")

echo "[4/5] 创建第 $lecture 讲发布提交"
git commit -m "release: publish lecture $lecture"

echo "[5/5] 推送到 origin/$branch"
git push origin "$branch"
echo "第 $lecture 讲已发布并推送完成。"
