#!/usr/bin/env bash
# 產生發佈用檔案到 dist/：
#   dist/wuwa-tappo-linux.tar.gz        壓縮包版
#   dist/wuwa-tappo-linux-install.sh    單一檔案安裝程式（內嵌壓縮包，不需解壓縮）
#
# 內容取自 git（預設 HEAD），所以只會包含已提交的檔案；未提交的修改不會進去。
#   ./build.sh           以 HEAD 建置
#   ./build.sh v1.0.0    以指定的 tag / commit 建置
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
REF="${1:-HEAD}"
DIST="dist"
NAME="wuwa-tappo-linux"

if [[ "$REF" == HEAD ]] && ! git diff --quiet HEAD -- ; then
    echo "注意：有未提交的修改，它們不會包含在建置結果中。" >&2
fi

mkdir -p "$DIST"
# .gitattributes 中標記 export-ignore 的檔案（例如本腳本）不會被打包
git archive --format=tar --prefix="$NAME/" "$REF" | gzip -n > "$DIST/$NAME.tar.gz"

out="$DIST/$NAME-install.sh"
cat > "$out" <<'EOF'
#!/usr/bin/env bash
# Wuwa Tappo for Linux — 單一檔案安裝程式（內含完整安裝包，不需另外解壓縮）
#
#   bash wuwa-tappo-linux-install.sh                         只準備環境
#   bash wuwa-tappo-linux-install.sh WuwaTappo-xx_setup.exe  準備環境並執行官方安裝程式
#   bash wuwa-tappo-linux-install.sh --extract <資料夾>       只解出安裝包內容（含 README、uninstall.sh）
set -euo pipefail
SELF="$(realpath "${BASH_SOURCE[0]}")"
LINE=$(awk '/^__PAYLOAD_BELOW__$/{print NR + 1; exit}' "$SELF")
if [[ "${1:-}" == "--extract" ]]; then
    dest="${2:?用法: $0 --extract <資料夾>}"
    mkdir -p "$dest"
    tail -n +"$LINE" "$SELF" | tar -xz -C "$dest"
    echo "已解出到 $dest/wuwa-tappo-linux"
    exit 0
fi
tmp="$(mktemp -d)"
trap 'rm -rf "$tmp"' EXIT
tail -n +"$LINE" "$SELF" | tar -xz -C "$tmp"
# 讓相對路徑的安裝檔參數在切換目錄後仍然有效
args=()
for a in "$@"; do [[ -f "$a" ]] && args+=("$(realpath "$a")") || args+=("$a"); done
bash "$tmp/wuwa-tappo-linux/install.sh" "${args[@]}"
exit $?
__PAYLOAD_BELOW__
EOF
cat "$DIST/$NAME.tar.gz" >> "$out"
chmod +x "$out"

echo "建置完成（$(git rev-parse --short "$REF^{commit}")）:"
ls -l "$DIST/$NAME.tar.gz" "$out"
