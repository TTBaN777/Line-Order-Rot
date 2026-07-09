import os
import re
from fastapi import APIRouter, Request, HTTPException
from linebot.v3 import WebhookHandler
from linebot.v3.exceptions import InvalidSignatureError
from linebot.v3.messaging import (
    Configuration, ApiClient, MessagingApi, MessagingApiBlob,
    ReplyMessageRequest, TextMessage, PushMessageRequest,
)
from linebot.v3.webhooks import (
    MessageEvent, TextMessageContent, FileMessageContent,
)
from sqlalchemy.orm import Session
from app.models.database import SessionLocal
from app.services import order_service
from app.services.menu_parser import parse_menu_from_txt

router = APIRouter()

configuration = Configuration(access_token=os.getenv("LINE_CHANNEL_ACCESS_TOKEN"))
handler = WebhookHandler(os.getenv("LINE_CHANNEL_SECRET"))

# 待確認的刪除操作（記憶體暫存，重啟服務會清空）
# 結構： { group_id: {"action": "deletemenu" | "deletehistory", "index": int, "user_id": str} }
pending_confirm: dict = {}


def get_db() -> Session:
    return SessionLocal()


def reply(reply_token: str, text: str):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).reply_message(
            ReplyMessageRequest(reply_token=reply_token, messages=[TextMessage(text=text)])
        )


def push(group_id: str, text: str):
    with ApiClient(configuration) as api_client:
        MessagingApi(api_client).push_message(
            PushMessageRequest(to=group_id, messages=[TextMessage(text=text)])
        )


@router.post("/webhook")
async def webhook(request: Request):
    signature = request.headers.get("X-Line-Signature", "")
    body = await request.body()
    try:
        handler.handle(body.decode(), signature)
    except InvalidSignatureError:
        raise HTTPException(status_code=400, detail="Invalid signature")
    return {"status": "ok"}


# ── 文字訊息處理 ──────────────────────────────────────

@handler.add(MessageEvent, message=TextMessageContent)
def handle_text(event: MessageEvent):
    text = event.message.text.strip()
    reply_token = event.reply_token
    source = event.source
    group_id = getattr(source, "group_id", None)
    user_id = source.user_id

    if not group_id:
        reply(reply_token, "此機器人僅支援群組使用")
        return

    db = get_db()

    try:
        with ApiClient(configuration) as api_client:
            profile = MessagingApi(api_client).get_group_member_profile(group_id, user_id)
            user_name = profile.display_name
    except Exception:
        user_name = "未知用戶"

    try:
        # /menu
        if text == "/menu":
            menu = order_service.get_active_menu(db, group_id)
            if not menu:
                reply(reply_token, "尚未設定菜單，請管理員上傳 .txt 菜單檔案")
            else:
                reply(reply_token, order_service.format_menu_text(menu))

        # /order <編號> <編號> ... [備註文字]
        elif text.startswith("/order"):
            rest = text[len("/order"):].strip()
            if not rest:
                reply(reply_token, "格式錯誤，請使用：/order <編號> <編號> ... [備註]\n例：/order 1 2 3 微糖微冰")
                return

            tokens = rest.split()
            item_numbers = []
            i = 0
            while i < len(tokens) and tokens[i].isdigit():
                item_numbers.append(int(tokens[i]))
                i += 1

            if not item_numbers:
                reply(reply_token, "格式錯誤，請使用：/order <編號> <編號> ... [備註]\n例：/order 1 2 3 微糖微冰")
                return

            note = " ".join(tokens[i:]) if i < len(tokens) else None
            msg = order_service.place_order_multi(db, group_id, user_id, user_name, item_numbers, note)
            reply(reply_token, msg)

        # /cancel <編號> <編號> ...
        elif text.startswith("/cancel"):
            rest = text[len("/cancel"):].strip()
            number_tokens = rest.split()
            if not number_tokens or not all(tok.isdigit() for tok in number_tokens):
                reply(reply_token, "格式錯誤，請使用：/cancel <編號> <編號> ...\n例：/cancel 1 2")
                return
            item_numbers = [int(tok) for tok in number_tokens]
            msg = order_service.cancel_order_multi(db, group_id, user_id, user_name, item_numbers)
            reply(reply_token, msg)

        # /reduce <編號> <編號> ...
        elif text.startswith("/reduce"):
            rest = text[len("/reduce"):].strip()
            number_tokens = rest.split()
            if not number_tokens or not all(tok.isdigit() for tok in number_tokens):
                reply(reply_token, "格式錯誤，請使用：/reduce <編號> <編號> ...\n例：/reduce 1 1 2")
                return
            item_numbers = [int(tok) for tok in number_tokens]
            msg = order_service.reduce_order_multi(db, group_id, user_id, user_name, item_numbers)
            reply(reply_token, msg)

        # /status
        elif text == "/status":
            reply(reply_token, order_service.get_order_status(db, group_id))

        # /admincancel <序號>（管理員取消任何人點的品項，序號來自 /status）
        elif text.startswith("/admincancel"):
            if not order_service.is_admin(db, group_id, user_id):
                reply(reply_token, "⚠️ 只有管理員可以取消他人品項")
                return
            match = re.match(r"/admincancel\s+(\d+)$", text)
            if not match:
                reply(reply_token, "格式錯誤，請使用：/admincancel <序號>\n例：/admincancel 3\n請先用 /status 確認序號")
                return
            reply(reply_token, order_service.admin_cancel_order_item(db, group_id, int(match.group(1))))

        # /myhistory
        elif text == "/myhistory":
            reply(reply_token, order_service.get_user_history(db, group_id, user_id, user_name))

        # /history 或 /history <編號>（查看單筆詳情）
        elif text.startswith("/history"):
            match = re.match(r"^/history(?:\s+(\d+))?$", text)
            if not match:
                reply(reply_token, "格式錯誤，請使用：/history 或 /history <編號> 查看詳情\n例：/history 2")
                return
            if match.group(1):
                reply(reply_token, order_service.get_group_history_detail(db, group_id, int(match.group(1))))
            else:
                reply(reply_token, order_service.get_group_history(db, group_id))

        # /menulist
        elif text == "/menulist":
            reply(reply_token, order_service.get_menu_list(db, group_id))

        # /switchmenu <編號>
        elif text.startswith("/switchmenu"):
            if not order_service.is_admin(db, group_id, user_id):
                reply(reply_token, "⚠️ 只有管理員可以切換菜單")
                return
            match = re.match(r"/switchmenu\s+(\d+)$", text)
            if not match:
                reply(reply_token, "格式錯誤，請使用：/switchmenu <編號>\n例：/switchmenu 2\n請先用 /menulist 確認編號")
                return
            reply(reply_token, order_service.switch_menu(db, group_id, int(match.group(1))))

        # /setcategory <編號> <飲料|餐點|其他>
        elif text.startswith("/setcategory"):
            if not order_service.is_admin(db, group_id, user_id):
                reply(reply_token, "⚠️ 只有管理員可以調整菜單分類")
                return
            match = re.match(r"/setcategory\s+(\d+)\s+(.+)$", text)
            if not match:
                reply(reply_token, "格式錯誤，請使用：/setcategory <編號> <分類>\n例：/setcategory 1 飲料\n請先用 /menulist 確認編號")
                return
            index = int(match.group(1))
            category = match.group(2).strip()
            reply(reply_token, order_service.set_menu_category(db, group_id, index, category))

        # ── 管理員指令 ──────────────────────────────

        # /search <關鍵字>
        elif text.startswith("/search"):
            match = re.match(r"/search\s+(.+)$", text)
            if not match:
                reply(reply_token, "格式錯誤，請使用：/search <關鍵字>\n例：/search 奶茶")
                return
            reply(reply_token, order_service.search(db, group_id, match.group(1).strip()))

        # /setadmin（最多可設定 3 位管理員）
        elif text == "/setadmin":
            group = order_service.get_or_create_group(db, group_id)
            admins = group.admin_ids or []
            MAX_ADMINS = 3
            if user_id in admins:
                reply(reply_token, f"{user_name} 已經是管理員了")
            elif len(admins) >= MAX_ADMINS:
                reply(reply_token, f"⚠️ 管理員已達上限（{MAX_ADMINS} 位），無法再新增")
            else:
                order_service.add_admin(db, group_id, user_id)
                remaining = MAX_ADMINS - len(admins) - 1
                reply(reply_token, f"✅ {user_name} 已設為管理員（還可再設定 {remaining} 位）")

        # /adminlist
        elif text == "/adminlist":
            if not order_service.is_admin(db, group_id, user_id):
                reply(reply_token, "⚠️ 只有管理員可以查看管理員名單")
                return
            admin_ids = order_service.get_admin_ids(db, group_id)
            if not admin_ids:
                reply(reply_token, "目前尚無管理員")
                return
            lines = ["👑 目前管理員名單：\n"]
            with ApiClient(configuration) as api_client:
                messaging_api = MessagingApi(api_client)
                for idx, admin_id in enumerate(admin_ids, start=1):
                    try:
                        profile = messaging_api.get_group_member_profile(group_id, admin_id)
                        name = profile.display_name
                    except Exception:
                        name = "（已離開群組或無法取得名稱）"
                    lines.append(f"  {idx}. {name}")
            reply(reply_token, "\n".join(lines))

        # /removeadmin <編號>（需 /confirm 二次確認，編號見 /adminlist）
        elif text.startswith("/removeadmin"):
            if not order_service.is_admin(db, group_id, user_id):
                reply(reply_token, "⚠️ 只有管理員可以移除管理員")
                return
            match = re.match(r"/removeadmin\s+(\d+)$", text)
            if not match:
                reply(reply_token, "格式錯誤，請使用：/removeadmin <編號>\n例：/removeadmin 2\n請先用 /adminlist 確認編號")
                return
            index = int(match.group(1))
            admin_ids = order_service.get_admin_ids(db, group_id)
            if index < 1 or index > len(admin_ids):
                reply(reply_token, f"編號 {index} 不存在，請用 /adminlist 確認編號")
                return
            target_id = admin_ids[index - 1]
            pending_confirm[group_id] = {"action": "removeadmin", "target_id": target_id, "user_id": user_id}
            reply(reply_token, f"⚠️ 確定要移除編號 {index} 這位管理員的身分嗎？\n請輸入 /confirm 確認")

        # /openmenu 或 /openmenu <歷史編號>（套用該次歷史紀錄的品項）
        elif text.startswith("/openmenu"):
            if not order_service.is_admin(db, group_id, user_id):
                reply(reply_token, "⚠️ 只有管理員可以開單")
                return
            match = re.match(r"^/openmenu(?:\s+(\d+))?$", text)
            if not match:
                reply(reply_token, "格式錯誤，請使用：/openmenu 或 /openmenu <歷史編號>\n例：/openmenu 2\n請先用 /history 確認編號")
                return
            history_index = int(match.group(1)) if match.group(1) else None
            try:
                order, is_new = order_service.open_order(db, group_id)
                if is_new:
                    menu = order_service.get_active_menu(db, group_id)
                    msg = f"✅ 點餐開始！\n\n{order_service.format_menu_text(menu)}"
                    if history_index:
                        apply_msg = order_service.apply_history_to_order(db, group_id, order, history_index)
                        msg += f"\n\n{apply_msg}\n輸入 /status 查看目前品項"
                    reply(reply_token, msg)
                else:
                    reply(reply_token, "點餐已在進行中，輸入 /status 查看狀況")
            except ValueError as e:
                reply(reply_token, str(e))

        # /deletemenu <編號>（需 /confirm 二次確認）
        elif text.startswith("/deletemenu"):
            if not order_service.is_admin(db, group_id, user_id):
                reply(reply_token, "⚠️ 只有管理員可以刪除菜單")
                return
            match = re.match(r"/deletemenu\s+(\d+)$", text)
            if not match:
                reply(reply_token, "格式錯誤，請使用：/deletemenu <編號>\n例：/deletemenu 2\n請先用 /menulist 確認編號")
                return
            index = int(match.group(1))
            pending_confirm[group_id] = {"action": "deletemenu", "index": index, "user_id": user_id}
            reply(reply_token, f"⚠️ 確定要刪除編號 {index} 的菜單嗎？此動作無法復原。\n請輸入 /confirm 確認")

        # /deletehistory <編號>（需 /confirm 二次確認）
        elif text.startswith("/deletehistory"):
            if not order_service.is_admin(db, group_id, user_id):
                reply(reply_token, "⚠️ 只有管理員可以刪除歷史紀錄")
                return
            match = re.match(r"/deletehistory\s+(\d+)$", text)
            if not match:
                reply(reply_token, "格式錯誤，請使用：/deletehistory <編號>\n例：/deletehistory 1\n請先用 /history 確認編號")
                return
            index = int(match.group(1))
            pending_confirm[group_id] = {"action": "deletehistory", "index": index, "user_id": user_id}
            reply(reply_token, f"⚠️ 確定要刪除第 {index} 筆歷史紀錄嗎？此動作無法復原。\n請輸入 /confirm 確認")

        # /clearorder（需 /confirm 二次確認）
        elif text == "/clearorder":
            if not order_service.is_admin(db, group_id, user_id):
                reply(reply_token, "⚠️ 只有管理員可以清除點餐品項")
                return
            pending_confirm[group_id] = {"action": "clearorder", "index": None, "user_id": user_id}
            reply(reply_token, "⚠️ 確定要清除本輪所有人的點餐品項嗎？此動作無法復原（點餐仍會維持開放）。\n請輸入 /confirm 確認")

        # /confirm
        elif text == "/confirm":
            pending = pending_confirm.get(group_id)
            if not pending:
                reply(reply_token, "目前沒有待確認的操作")
                return
            if pending["user_id"] != user_id:
                reply(reply_token, "⚠️ 請由發起指令的管理員本人輸入 /confirm")
                return
            del pending_confirm[group_id]
            if pending["action"] == "deletemenu":
                reply(reply_token, order_service.delete_menu(db, group_id, pending["index"]))
            elif pending["action"] == "deletehistory":
                reply(reply_token, order_service.delete_history(db, group_id, pending["index"]))
            elif pending["action"] == "clearorder":
                reply(reply_token, order_service.clear_order_items(db, group_id))
            elif pending["action"] == "removeadmin":
                ok = order_service.remove_admin(db, group_id, pending["target_id"])
                reply(reply_token, "✅ 已移除該管理員身分" if ok else "⚠️ 該使用者已不是管理員，無需移除")

        # /done
        elif text == "/done":
            if not order_service.is_admin(db, group_id, user_id):
                reply(reply_token, "⚠️ 只有管理員可以結單")
                return
            reply(reply_token, order_service.close_order(db, group_id))

        elif text == "/help":
            reply(reply_token, (
                "📖 點餐機器人指令說明\n\n"
                "一般指令：\n"
                "  /menu — 查看菜單\n"
                "  /order <編號> <編號> ... [備註] — 點餐（重複編號代表多份，重複點會累加）\n"
                "  /cancel <編號> <編號> ... — 取消品項整筆\n"
                "  /reduce <編號> <編號> ... — 減少品項份數（重複編號代表減多份）\n"
                "  /status — 查看目前點餐狀況\n"
                "  /myhistory — 我的點餐歷史\n"
                "  /history — 群組點餐歷史清單\n"
                "  /history <編號> — 查看該次結單詳情\n"
                "  /menulist — 列出所有已儲存的菜單\n"
                "  /search <關鍵字> — 搜尋菜單與歷史紀錄\n\n"
                "管理員指令：\n"
                "  /setadmin — 設定自己為管理員（最多可設定 3 位）\n"
                "  /adminlist — 查看目前管理員名單\n"
                "  /removeadmin <編號> — 移除指定管理員身分（需 /confirm 確認）\n"
                "  上傳 .txt 檔案 — 匯入菜單（保留舊菜單）\n"
                "  /switchmenu <編號> — 切換使用中的菜單（開單中無法切換）\n"
                "  /setcategory <編號> <分類> — 調整菜單分類（飲料／餐點／其他）\n"
                "  /deletemenu <編號> — 刪除指定菜單（需 /confirm 確認）\n"
                "  /deletehistory <編號> — 刪除歷史紀錄（需 /confirm 確認）\n"
                "  /admincancel <序號> — 取消他人點的品項（序號見 /status）\n"
                "  /clearorder — 清除本輪所有點餐品項，但不結單（需 /confirm 確認）\n"
                "  /openmenu — 開放點餐\n"
                "  /openmenu <歷史編號> — 開單並套用該次歷史紀錄的品項（編號見 /history）\n"
                "  /done — 結單"
            ))

    except Exception:
        import traceback
        traceback.print_exc()  # 印到 Railway log，方便查真正的錯誤原因
        reply(reply_token, "⚠️ 系統發生錯誤，請稍後再試或聯絡管理員")

    finally:
        db.close()


# ── 檔案訊息處理（.txt 菜單匯入）────────────────────

@handler.add(MessageEvent, message=FileMessageContent)
def handle_file(event: MessageEvent):
    reply_token = event.reply_token
    source = event.source
    group_id = getattr(source, "group_id", None)
    user_id = source.user_id

    if not group_id:
        return

    db = get_db()
    try:
        if not order_service.is_admin(db, group_id, user_id):
            return  # 非管理員傳檔，靜默忽略

        file_name = event.message.file_name or ""
        if not file_name.endswith(".txt"):
            reply(reply_token, "⚠️ 只支援 .txt 格式，請上傳正確的菜單檔案")
            return

        # 下載檔案內容
        with ApiClient(configuration) as api_client:
            blob_api = MessagingApiBlob(api_client)
            raw_bytes = blob_api.get_message_content(event.message.id)

        text_content = raw_bytes.decode("utf-8", errors="ignore")

        result = parse_menu_from_txt(text_content)
        if not result:
            reply(reply_token, (
                "❌ 菜單格式有誤，請確認格式如下：\n\n"
                "店名：清心福全\n\n"
                "珍珠奶茶 55\n"
                "烏龍茶 45\n"
                "紅茶 35"
            ))
            return

        menu = order_service.create_menu(
            db, group_id, result["store_name"], result["items"], category=result.get("category", "其他")
        )
        # 用 push 回傳，因為 reply_token 可能已被消耗
        push(group_id, f"✅ 菜單已匯入！\n\n{order_service.format_menu_text(menu)}")

    except Exception:
        import traceback
        traceback.print_exc()
        push(group_id, "⚠️ 匯入菜單時發生錯誤，請確認檔案格式或稍後再試")

    finally:
        db.close()