# Wuwa Tappo for Linux

讓《鳴潮》官方桌寵 **Wuwa Tappo**（只有 Windows 版）在 Linux 上執行的安裝包。

這不是官方專案，和庫洛遊戲（Kuro Games）無關。這個包**不含**桌寵本體：桌寵安裝檔請自行從官方管道下載，其餘需要的東西（GE-Proton、Microsoft WebView2、Windows 版 Python）都由安裝腳本從各自的官方來源下載。

## 系統需求

- x86_64 的 Linux，**X11 工作階段**（Wayland 不行：透明效果、輸入偵測、置頂都依賴 X11）
- 桌面要開啟**視窗合成效果（compositor）**，否則桌寵背景會是黑色方塊
  - GNOME、KDE、Cinnamon 預設就有；MATE 要在「外觀 / 視窗管理員」開啟合成；Xfce 要在「視窗管理員微調 → 合成器」開啟
- 套件（以 Ubuntu / Debian 為例）：

  ```bash
  sudo apt install python3 python3-xlib python3-numpy python3-scipy curl p7zip-full
  ```

  `p7zip-full` 可省略，只是選單捷徑會沒有圖示。
- 約 2.5 GB 磁碟空間（GE-Proton、WebView2、桌寵本體）

已在 Ubuntu 24.04 + MATE（X11）+ GE-Proton11-6 測試過。

## 安裝

1. 解壓縮這個包，並從官方管道下載 Wuwa Tappo 的 Windows 安裝檔（例如 `WuwaTappo-cn_1.0.4_x64-setup.exe`）。
2. 在解壓縮後的資料夾執行：

   ```bash
   ./install.sh ~/Downloads/WuwaTappo-cn_1.0.4_x64-setup.exe
   ```

   - 如果 Steam 裡已經有 GE-Proton 10 以上的版本，會直接拿來用；沒有的話會自動下載 GE-Proton11-6（約 500 MB，並核對官方校驗碼）。
   - 第一次執行要準備 Wine 環境並安裝 WebView2，需要幾分鐘。
3. 桌寵安裝程式的視窗出現後，照平常一樣勾選同意條款、按「安裝」。

> 若安裝程式的視窗沒有出現，再執行一次 `wuwa-tappo install <安裝檔>` 即可。

## 使用

- 從應用程式選單開啟「Wuwa Tappo」，或在終端機執行 `wuwa-tappo`
- 一定要透過上面兩種方式啟動，下面那些修正才會一起生效
- 桌寵卡住時：`wuwa-tappo kill`，然後重新開啟

## 這個包做了哪些修正

在 Wine 下直接執行桌寵會遇到一連串問題，這個包都處理掉了：

| 問題 | 處理方式 |
|---|---|
| 舊版 Wine 跑不動 WebView2 | 改用 GE-Proton 的 Wine 11，並以相容參數執行 WebView2 |
| 安裝程式偶爾一開就自己結束 | 和下一列是同一個 bug；安裝時會先複製一份安裝檔並修補後再執行，原始檔不會被修改 |
| 主程式一啟動就崩潰 | Wine 處理拖放（drag & drop）時有 bug，啟動前會把主程式中的一個相關呼叫換成無作用的函式（原檔備份為 `WuwaTappo.exe.orig`，程式更新後會自動重新套用）。副作用：可能無法把檔案拖進桌寵 |
| 桌寵背景是黑色方塊、出現白色框線 | 用一個透明的覆蓋視窗重新顯示桌寵，把背景去掉 |
| 桌寵的「透明度」設定只會讓它變暗 | 讀取設定值，換成真正的半透明 |
| 寶箱出現時畫面破圖 | 桌寵顯示範圍改變時，強制重繪畫面 |
| 在其他程式打字或點滑鼠時，桌寵沒反應 | 把 Linux 端的按鍵與點擊轉給桌寵（只轉給它的計數功能，不會重複輸入到其他地方） |
| 選單按鈕點不到 | 讓桌寵保持在所有視窗的最上層 |

## 已知限制

- 桌寵邊緣是硬邊，沒有柔和的半透明過渡；本身就半透明的元素（例如泡泡）會略微偏暗。這是 Wine 缺少 Windows 合成功能的限制。
- 拖放檔案到桌寵可能無效。
- 桌寵永遠在其他視窗之上，被它蓋住的一小塊區域點不到後面的視窗（和 Windows 版行為相同）。
- 程式內的「開機自動啟動」在 Linux 上沒有作用；需要的話，請把「Wuwa Tappo」加入桌面環境的「啟動應用程式」。

## 疑難排解

- **角色圖片顯示不出來**：角色圖片放在官方的中國 CDN（`mc-wuwatappo.kurogames-global.com`）上。某些網路環境連線不穩，短時間內反覆重開桌寵也可能被暫時擋下。等一段時間再試，或換個網路。這和本安裝包無關。
- **背景是黑的**：確認桌面的合成效果有開，且使用 X11 工作階段。
- **只想關掉某個修正**：
  - `WUWA_ALPHA_MIRROR=0 wuwa-tappo`：關閉透明覆蓋
  - `WUWA_KEY_FORWARD=0 wuwa-tappo`：關閉鍵盤與滑鼠轉送
- **指定別的 Wine**：`WUWA_WINE_DIR=/path/to/wine/bin wuwa-tappo`（需要 Wine 10 以上，建議用 GE-Proton）

## 移除

```bash
./uninstall.sh
```

會刪除 `~/.local/share/wuwa-tappo`（Wine 環境、桌寵本體與其登入資料、設定）、`wuwa-tappo` 指令與選單捷徑。Steam 的 GE-Proton 不受影響。

## 檔案位置

| 路徑 | 內容 |
|---|---|
| `~/.local/share/wuwa-tappo/wuwa-tappo` | 啟動器（`~/.local/bin/wuwa-tappo` 指向它） |
| `~/.local/share/wuwa-tappo/prefix/` | Wine 環境（桌寵安裝在裡面的 `Program Files/WuwaTappo`） |
| `~/.local/share/wuwa-tappo/helpers/` | 透明覆蓋、輸入轉送等輔助程式 |
| `~/.local/share/wuwa-tappo/proton/` | 自動下載的 GE-Proton（只有在 Steam 沒有時才會有） |
