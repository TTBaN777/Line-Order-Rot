# LINE 點餐機器人 🍱

群組點餐紀錄機器人，支援 .txt 菜單匯入、多筆點餐、歷史紀錄查詢與刪除、多位管理員權限管理。

## 功能

| 指令 | 說明 | 權限 |
|------|------|------|
| `/menu` | 顯示目前使用中的菜單 | 所有人 |
| `/order 1 2 3 少冰` | 點餐（可一次點多筆，重複編號代表多份，備註直接接在最後） | 所有人 |
| `/cancel 1 2` | 取消我點的品項（可一次取消多筆） | 所有人 |
| `/reduce 1 1 2` | 減少我點的品項份數（重複編號代表減多份） | 所有人 |
| `/status` | 查看目前點餐狀況 | 所有人 |
| `/myhistory` | 我的點餐歷史（依訂單分組顯示） | 所有人 |
| `/history` | 群組點餐歷史清單 | 所有人 |
| `/history 2` | 查看該次結單詳情 | 所有人 |
| `/menulist` | 列出所有已儲存的菜單 | 所有人 |
| `/search 奶茶` | 搜尋菜單與歷史紀錄 | 所有人 |
| `/help` | 指令說明 | 所有人 |
| `/setadmin` | 設定自己為管理員（最多可設定 3 位，已是管理員則不可重複設定） | 所有人 |
| 上傳 `.txt` 檔案 | 匯入菜單（保留舊菜單，可用 `/switchmenu` 切換） | 管理員 |
| `/switchmenu 2` | 切換使用中的菜單（開單中無法切換） | 管理員 |
| `/deletemenu 2` | 刪除指定菜單，連同其點餐紀錄一併刪除（需 `/confirm` 確認） | 管理員 |
| `/deletehistory 1` | 刪除單筆歷史紀錄（需 `/confirm` 確認） | 管理員 |
| `/admincancel 3` | 取消他人點的品項（序號見 `/status`） | 管理員 |
| `/clearorder` | 清除本輪所有人的點餐品項，但不結單（需 `/confirm` 確認） | 管理員 |
| `/openmenu` | 開放點餐 | 管理員 |
| `/openmenu 2` | 開單並套用該次歷史紀錄的品項（編號見 `/history`） | 管理員 |
| `/done` | 結單並顯示清單與個人應付金額 | 管理員 |
| `/adminlist` | 查看目前管理員名單 | 管理員 |
| `/removeadmin 2` | 移除指定管理員身分（編號見 `/adminlist`，需 `/confirm` 確認） | 管理員 |

> 所有涉及刪除／移除的操作都需要輸入 `/confirm` 二次確認，且只有發起指令的那位管理員本人可以確認，避免誤觸。

## 菜單匯入格式（.txt）

```
店名：清心福全

# 茶類
珍珠奶茶 55
烏龍茶 45

# 其他
紅茶 35
```
`#分類名稱` 為選填，可以將品項分組顯示。

## 本地開發

```bash
# 安裝套件
pip install -r requirements.txt

# 複製環境變數
cp .env.example .env
# 編輯 .env 填入你的金鑰

# 啟動伺服器
uvicorn app.main:app --reload --port 8000

# 使用 ngrok 於本地端（開發測試用）
ngrok http 8000
```

本機預設會使用 SQLite（`orderbot.db`），跟正式環境的 PostgreSQL 是完全獨立的兩份資料，互不影響。

## 部署到 Railway

1. 將專案推上 GitHub（記得 `Procfile`、`requirements.txt`、`.gitignore` 都要在根目錄；`.env`、`.venv/`、`orderbot.db` 絕對不要推上去）
2. 至 [railway.app](https://railway.app) 建立新專案，選 **Deploy from GitHub repo**
3. 加入 PostgreSQL（+ New → Database → Add PostgreSQL）
4. 在 web service 的 Variables 分頁填入：
   - `LINE_CHANNEL_SECRET`
   - `LINE_CHANNEL_ACCESS_TOKEN`
   - `DATABASE_URL`（建議用 Add Reference 連到剛建立的 Postgres，不要手動複製貼上）
5. 部署完成後，到 web service 的 Settings → Networking 產生網址，並設定 LINE Webhook URL：
   `https://your-app.up.railway.app/webhook`

> ⚠️ 注意 Python 版本相容性：`sqlalchemy` 需要 `2.0.31` 以上才支援 Python 3.13，版本太舊會在啟動時噴 `TypeError: Can't replace canonical symbol for '__firstlineno__'`。

## 取得 LINE Bot 金鑰

1. 前往 [LINE Developers Console](https://developers.line.biz/)
2. 建立 Provider → 建立 Messaging API Channel
3. 在 Basic settings 取得 `Channel Secret`
4. 在 Messaging API 取得 `Channel Access Token`
5. 將 Webhook URL 設為你的部署網址 + `/webhook`，並開啟 **Use webhook**
6. 關閉 **Auto-reply messages**，並開啟 **允許加入群組聊天（Allow bot to join group chats）**

## 使用流程

```
1. 將機器人加入群組
2. 輸入 /setadmin 設定管理員（最多 3 位，任何人都可以設定自己，額滿為止）
3. 上傳菜單 .txt 檔案
4. 輸入 /openmenu 開放點餐（也可用 /openmenu <歷史編號> 套用之前點過的品項）
5. 大家輸入 /order <編號> <編號> ... [備註] 點餐
6. 管理員輸入 /done 結單，自動顯示清單與個人應付金額
```

## 注意事項

- **每個群組的資料完全獨立**：菜單、開單狀態、歷史紀錄、管理員名單都用 LINE 的 `group_id` 區分，把機器人拉進新群組等於是全新的一份資料，管理員需要重新用 `/setadmin` 設定
- 管理員身分沒有額外限制，只要名額（3 位）沒滿，任何人都能自己 `/setadmin` 加入
- 目前**沒有導入資料庫 migration 工具（如 Alembic）**，未來若修改 `models.py` 新增或調整欄位，正式環境的資料庫不會自動跟著更新，需要手動下 `ALTER TABLE` 或透過 migration 工具處理，否則會出現 `no such column` 的錯誤