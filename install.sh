#!/usr/bin/env bash
# Wuwa Tappo for Linux 安裝程式
#   ./install.sh                         只準備環境（之後再用 wuwa-tappo install 安裝桌寵）
#   ./install.sh WuwaTappo-xx_setup.exe  準備環境並直接執行官方安裝程式
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE="${WUWA_TAPPO_HOME:-$HOME/.local/share/wuwa-tappo}"
BIN_DIR="$HOME/.local/bin"
APPS_DIR="$HOME/.local/share/applications"

PROTON_TAG="GE-Proton11-6"   # 已測試的版本
PROTON_FILE="$PROTON_TAG-x86_64.tar.gz"
PROTON_URL="https://github.com/GloriousEggroll/proton-ge-custom/releases/download/$PROTON_TAG"

say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m警告:\033[0m %s\n' "$*" >&2; }
die()  { printf '\033[1;31m錯誤:\033[0m %s\n' "$*" >&2; exit 1; }

setup_exe="${1:-}"
[[ -z "$setup_exe" || -f "$setup_exe" ]] || die "找不到安裝檔: $setup_exe"
[[ -n "$setup_exe" ]] && setup_exe="$(realpath "$setup_exe")"

# ---------- 1. 檢查系統 ----------
[[ "$(uname -m)" == x86_64 ]] || die "只支援 x86_64。"
if [[ "${XDG_SESSION_TYPE:-}" == wayland ]]; then
    warn "目前是 Wayland 工作階段。透明效果、輸入轉送與置頂都需要 X11（登入時選擇 Xorg/X11 工作階段）。"
fi

missing=()
command -v python3 >/dev/null || missing+=(python3)
command -v curl    >/dev/null || missing+=(curl)
python3 -c 'import Xlib' 2>/dev/null       || missing+=(python3-xlib)
python3 -c 'import numpy' 2>/dev/null      || missing+=(python3-numpy)
python3 -c 'import scipy.ndimage' 2>/dev/null || missing+=(python3-scipy)
if ((${#missing[@]})); then
    echo "缺少必要套件: ${missing[*]}"
    if command -v apt-get >/dev/null; then
        echo "請先執行:  sudo apt install ${missing[*]} p7zip-full"
    else
        echo "請用你的套件管理員安裝對應套件（Python 模組也可用 pip install python-xlib numpy scipy）。"
    fi
    exit 1
fi
command -v 7z >/dev/null || warn "沒有 7z（p7zip-full），選單捷徑將沒有圖示。"

# 透明覆蓋需要合成器（compositor）
if [[ -n "${DISPLAY:-}" ]] && ! python3 -I -c '
from Xlib import display
d = display.Display()
sel = d.intern_atom("_NET_WM_CM_S%d" % d.get_default_screen())
raise SystemExit(0 if d.get_selection_owner(sel) else 1)' 2>/dev/null; then
    warn "偵測不到視窗合成器（compositor）。沒有它桌寵背景會是黑色方塊；請在桌面設定中開啟合成效果。"
fi

# ---------- 2. GE-Proton ----------
have_proton=""
for d in "$BASE"/proton/GE-Proton*/files/bin \
         "$HOME"/.local/share/Steam/compatibilitytools.d/GE-Proton1[0-9]*/files/bin \
         "$HOME"/.steam/root/compatibilitytools.d/GE-Proton1[0-9]*/files/bin; do
    [[ -x "$d/wine" ]] && { have_proton="$d"; break; }
done
if [[ -n "${WUWA_WINE_DIR:-}" ]]; then
    say "使用 WUWA_WINE_DIR: $WUWA_WINE_DIR"
elif [[ -n "$have_proton" ]]; then
    say "使用現有的 GE-Proton: ${have_proton%/files/bin}"
else
    say "下載 $PROTON_TAG（約 500 MB，僅此一次）"
    mkdir -p "$BASE/proton" "$BASE/downloads"
    tarball="$BASE/downloads/$PROTON_FILE"
    if [[ ! -f "$tarball" ]]; then
        curl -fL -o "$tarball.part" "$PROTON_URL/$PROTON_FILE"
        mv "$tarball.part" "$tarball"
    fi
    expected="$(curl -fsSL "$PROTON_URL/$PROTON_TAG-x86_64.sha512sum" | awk '{print $1}')"
    actual="$(sha512sum "$tarball" | awk '{print $1}')"
    [[ -n "$expected" && "$expected" == "$actual" ]] || { rm -f "$tarball"; die "GE-Proton 檔案校驗失敗，請重新執行。"; }
    say "解壓縮 GE-Proton"
    tar -xzf "$tarball" -C "$BASE/proton"
    rm -f "$tarball"
fi

# ---------- 3. 複製檔案 ----------
say "安裝檔案到 $BASE"
mkdir -p "$BASE/helpers" "$BIN_DIR" "$APPS_DIR"
install -m 755 "$HERE/files/wuwa-tappo"        "$BASE/wuwa-tappo"
install -m 644 "$HERE/files/patch_dragdrop.py" "$BASE/patch_dragdrop.py"
install -m 644 "$HERE"/files/helpers/*.py      "$BASE/helpers/"
ln -sf "$BASE/wuwa-tappo" "$BIN_DIR/wuwa-tappo"

cat > "$APPS_DIR/wuwa-tappo.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Wuwa Tappo
Name[zh_TW]=Wuwa Tappo 鳴潮桌寵
Name[zh_CN]=Wuwa Tappo 鸣潮桌宠
Comment=鳴潮桌寵軟體（透過 Wine 執行）
Exec=$BASE/wuwa-tappo
Icon=$BASE/icon.png
Terminal=false
Categories=Game;
EOF
command -v update-desktop-database >/dev/null && update-desktop-database "$APPS_DIR" 2>/dev/null || true

# ---------- 4. Wine 環境 ----------
say "準備 Wine 環境（第一次約需數分鐘）"
"$BASE/wuwa-tappo" setup

# ---------- 5. 官方安裝程式 ----------
if [[ -n "$setup_exe" ]]; then
    say "開啟官方安裝程式，請在視窗中完成安裝"
    "$BASE/wuwa-tappo" install "$setup_exe" || true
fi

echo
say "完成！"
if [[ -z "$setup_exe" ]]; then
    echo "  1. 從官方網站下載 Wuwa Tappo 的 Windows 安裝檔"
    echo "  2. 執行:  wuwa-tappo install ~/Downloads/WuwaTappo-xx_x64-setup.exe"
fi
echo "  啟動:  應用程式選單中的「Wuwa Tappo」，或執行 wuwa-tappo"
case ":$PATH:" in *":$BIN_DIR:"*) ;; *) warn "$BIN_DIR 不在 PATH 中，請重新登入或用完整路徑 $BASE/wuwa-tappo";; esac
