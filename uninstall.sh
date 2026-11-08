#!/usr/bin/env bash
# 移除 Wuwa Tappo for Linux（包含 Wine 環境、已安裝的桌寵與其資料）
set -euo pipefail
BASE="${WUWA_TAPPO_HOME:-$HOME/.local/share/wuwa-tappo}"

echo "將刪除: $BASE"
echo "（包含 Wine 環境、桌寵本體、登入資料與設定；Steam 的 GE-Proton 不受影響）"
read -r -p "確定要移除嗎？[y/N] " ans
[[ "$ans" == [yY]* ]] || { echo "已取消"; exit 0; }

[[ -x "$BASE/wuwa-tappo" ]] && "$BASE/wuwa-tappo" kill 2>/dev/null || true
rm -f "$HOME/.local/bin/wuwa-tappo" "$HOME/.local/share/applications/wuwa-tappo.desktop"
rm -rf "$BASE"
echo "已移除。"
