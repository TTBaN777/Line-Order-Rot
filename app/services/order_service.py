from sqlalchemy.orm import Session
from sqlalchemy import desc
from app.models.models import Group, Menu, MenuItem, Order, OrderItem
from typing import Optional
from datetime import timezone, datetime
from zoneinfo import ZoneInfo
from collections import defaultdict, Counter

TAIPEI_TZ = ZoneInfo("Asia/Taipei")


def to_taipei(dt: Optional[datetime]) -> Optional[datetime]:
    """把資料庫存的 UTC 時間轉成台北時間（+8）顯示用。
    若讀出來的 datetime 沒有 tzinfo（例如某些環境下 SQLite 的行為），視為 UTC 處理。"""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(TAIPEI_TZ)


# ── 群組 ──────────────────────────────────────────────

def get_or_create_group(db: Session, group_id: str) -> Group:
    group = db.query(Group).filter(Group.group_id == group_id).first()
    if not group:
        group = Group(group_id=group_id, admin_ids=[])
        db.add(group)
        db.commit()
        db.refresh(group)
    return group


def is_admin(db: Session, group_id: str, user_id: str) -> bool:
    group = db.query(Group).filter(Group.group_id == group_id).first()
    if not group:
        return False
    return user_id in (group.admin_ids or [])


def add_admin(db: Session, group_id: str, user_id: str):
    group = get_or_create_group(db, group_id)
    admins = list(group.admin_ids or [])
    if user_id not in admins:
        admins.append(user_id)
        group.admin_ids = admins
        db.commit()

def get_admin_ids(db: Session, group_id: str) -> list:
    group = db.query(Group).filter(Group.group_id == group_id).first()
    if not group:
        return []
    return group.admin_ids or []


def remove_admin(db: Session, group_id: str, target_user_id: str) -> bool:
    """移除指定使用者的管理員身分。回傳 False 代表對方本來就不是管理員。"""
    group = get_or_create_group(db, group_id)
    admins = list(group.admin_ids or [])
    if target_user_id not in admins:
        return False
    admins.remove(target_user_id)
    group.admin_ids = admins
    db.commit()
    return True

# ── 菜單 ──────────────────────────────────────────────

def create_menu(db: Session, group_id: str, store_name: str, items: list[dict]) -> Menu:
    """上傳新菜單，保留舊菜單（不覆蓋），新的設為 is_active"""
    get_or_create_group(db, group_id)

    # 停用目前的 active 菜單
    db.query(Menu).filter(Menu.group_id == group_id, Menu.is_active == True).update({"is_active": False})

    menu = Menu(group_id=group_id, store_name=store_name)
    db.add(menu)
    db.flush()

    for item_data in items:
        item = MenuItem(
            menu_id=menu.menu_id,
            number=item_data["number"],
            name=item_data["name"],
            price=item_data["price"],
            category=item_data.get("category"),
        )
        db.add(item)

    db.commit()
    db.refresh(menu)
    return menu


def get_active_menu(db: Session, group_id: str) -> Optional[Menu]:
    return (
        db.query(Menu)
        .filter(Menu.group_id == group_id, Menu.is_active == True)
        .order_by(desc(Menu.created_at))
        .first()
    )


def get_all_menus(db: Session, group_id: str) -> list[Menu]:
    return (
        db.query(Menu)
        .filter(Menu.group_id == group_id)
        .order_by(desc(Menu.created_at))
        .all()
    )


def format_menu_text(menu: Menu) -> str:
    """格式化菜單，支援分類顯示"""
    lines = [f"📋 {menu.store_name} 菜單\n"]
    items = sorted(menu.items, key=lambda x: x.number)

    # 檢查是否有分類
    has_category = any(item.category for item in items)

    if has_category:
        current_cat = None
        for item in items:
            if item.category != current_cat:
                current_cat = item.category
                if current_cat:
                    lines.append(f"\n【{current_cat}】")
            lines.append(f"  {item.number}. {item.name}  ${item.price}")
    else:
        for item in items:
            lines.append(f"  {item.number}. {item.name}  ${item.price}")

    lines.append("\n輸入 /order <編號> 來點餐")
    return "\n".join(lines)


def get_menu_list(db: Session, group_id: str) -> str:
    """列出所有已儲存的菜單"""
    menus = get_all_menus(db, group_id)
    if not menus:
        return "尚未建立任何菜單"

    active = get_active_menu(db, group_id)
    lines = ["📚 已儲存的菜單：\n"]
    for idx, menu in enumerate(menus, start=1):
        active_str = "（目前使用中）" if active and menu.menu_id == active.menu_id else ""
        lines.append(f"  {idx}. {menu.store_name} {active_str}")

    lines.append("\n輸入 /switchmenu <編號> 切換菜單")
    return "\n".join(lines)


def switch_menu(db: Session, group_id: str, index: int) -> str:
    """切換到指定編號的菜單"""
    if get_open_order(db, group_id):
        return "⚠️ 目前正在開單中，無法切換菜單，請先 /done 結單後再切換"

    menus = get_all_menus(db, group_id)
    if not menus:
        return "尚未建立任何菜單"

    if index < 1 or index > len(menus):
        return f"編號 {index} 不存在，請用 /menulist 確認編號"

    target = menus[index - 1]

    # 停用目前 active，啟用目標
    db.query(Menu).filter(Menu.group_id == group_id, Menu.is_active == True).update({"is_active": False})
    target.is_active = True
    db.commit()
    db.refresh(target)

    return f"✅ 已切換到「{target.store_name}」\n\n{format_menu_text(target)}"


# ── 菜單手動編輯 ──────────────────────────────────────
# （/additem、/removeitem、/edititem、/clearmenu 已移除，
#   品項一律透過上傳 .txt 檔案匯入新菜單）


# （建立菜單唯一方式為上傳 .txt 檔案，/newmenu + create_empty_menu 已移除）


# ── 搜尋 ──────────────────────────────────────────────

def search(db: Session, group_id: str, keyword: str) -> str:
    results = []

    # 搜尋目前菜單品項（模糊比對）
    menu = get_active_menu(db, group_id)
    if menu:
        matched_items = [item for item in menu.items if keyword in item.name]
        if matched_items:
            results.append(f"📋 目前菜單（{menu.store_name}）：")
            for item in matched_items:
                cat_str = f"［{item.category}］" if item.category else ""
                results.append(f"  {item.number}. {item.name}{cat_str}  ${item.price}")

    # 搜尋歷史紀錄（店家名稱 + 品項名稱，模糊比對）
    past_orders = (
        db.query(Order)
        .filter(Order.group_id == group_id, Order.is_open == False)
        .order_by(desc(Order.closed_at))
        .all()
    )

    matched_orders = []
    for order in past_orders:
        date_str = to_taipei(order.closed_at).strftime("%m/%d %H:%M") if order.closed_at else "未知"
        store = db.query(Menu).filter(Menu.menu_id == order.menu_id).first()
        store_name = store.store_name if store else "未知店家"
        store_match = keyword in store_name
        item_matches = [oi for oi in order.order_items if keyword in oi.item.name]
        if store_match or item_matches:
            matched_orders.append((date_str, store_name, store_match, item_matches))

    if matched_orders:
        results.append("\n📚 歷史紀錄：")
        for date_str, store_name, store_match, item_matches in matched_orders:
            if store_match:
                results.append(f"  【{date_str}】{store_name}（店家名稱符合）")
            else:
                results.append(f"  【{date_str}】{store_name}")
                for oi in item_matches:
                    qty_str = f" x{oi.quantity}" if oi.quantity > 1 else ""
                    results.append(f"    • {oi.item.name}{qty_str}")

    if not results:
        return f"找不到與「{keyword}」相關的結果"

    return f"🔍 搜尋「{keyword}」的結果：\n\n" + "\n".join(results)


# ── 訂單 ──────────────────────────────────────────────

def get_open_order(db: Session, group_id: str) -> Optional[Order]:
    return (
        db.query(Order)
        .filter(Order.group_id == group_id, Order.is_open == True)
        .order_by(desc(Order.opened_at))
        .first()
    )


def open_order(db: Session, group_id: str) -> tuple[Order, bool]:
    existing = get_open_order(db, group_id)
    if existing:
        return existing, False

    menu = get_active_menu(db, group_id)
    if not menu:
        raise ValueError("尚未設定菜單，請先上傳 .txt 菜單檔案")

    order = Order(group_id=group_id, menu_id=menu.menu_id)
    db.add(order)
    db.commit()
    db.refresh(order)
    return order, True


def _get_order_item(db: Session, order_id: int, user_id: str, item_id: int) -> Optional[OrderItem]:
    return (
        db.query(OrderItem)
        .filter(OrderItem.order_id == order_id, OrderItem.user_id == user_id, OrderItem.item_id == item_id)
        .first()
    )


def place_order(db: Session, group_id: str, user_id: str, user_name: str,
                item_number: int, quantity: int = 1, note: Optional[str] = None) -> str:
    order = get_open_order(db, group_id)
    if not order:
        return "目前沒有開放點餐，請等管理員開單 (/openmenu)"

    item = db.query(MenuItem).filter(MenuItem.menu_id == order.menu_id, MenuItem.number == item_number).first()
    if not item:
        return f"找不到編號 {item_number} 的品項，請用 /menu 查看菜單"

    existing = _get_order_item(db, order.order_id, user_id, item.item_id)
    if existing:
        existing.quantity += quantity
        existing.note = note
        db.commit()
        note_str = f"（備註：{note}）" if note else ""
        return f"✅ {user_name} 的「{item.name}」累計 {existing.quantity} 份{note_str}"
    else:
        db.add(OrderItem(order_id=order.order_id, user_id=user_id, user_name=user_name,
                         item_id=item.item_id, quantity=quantity, note=note))
        db.commit()
        qty_str = f" x{quantity}" if quantity > 1 else ""
        note_str = f"（備註：{note}）" if note else ""
        return f"✅ {user_name} 點了「{item.name}」{qty_str} ${item.price * quantity}{note_str}"


def place_order_multi(db: Session, group_id: str, user_id: str, user_name: str,
                       item_numbers: list, note: Optional[str] = None) -> str:
    """新版 /order：一次傳入多個編號（可重複代表份數），共用同一個備註。
    例：item_numbers=[1, 1, 2] 代表編號1點2份、編號2點1份。"""
    order = get_open_order(db, group_id)
    if not order:
        return "目前沒有開放點餐，請等管理員開單 (/openmenu)"

    counts = Counter(item_numbers)

    # 先驗證所有編號都存在，避免部分成功部分失敗
    items_by_number = {}
    for number in counts:
        item = db.query(MenuItem).filter(MenuItem.menu_id == order.menu_id, MenuItem.number == number).first()
        if not item:
            return f"找不到編號 {number} 的品項，請用 /menu 查看菜單"
        items_by_number[number] = item

    result_lines = []
    total = 0
    for number, qty in counts.items():
        item = items_by_number[number]
        existing = _get_order_item(db, order.order_id, user_id, item.item_id)
        if existing:
            existing.quantity += qty
            existing.note = note
            final_qty = existing.quantity
        else:
            db.add(OrderItem(order_id=order.order_id, user_id=user_id, user_name=user_name,
                             item_id=item.item_id, quantity=qty, note=note))
            final_qty = qty
        total += item.price * qty
        note_str = f"（備註：{note}）" if note else ""
        result_lines.append(f"「{item.name}」累計 {final_qty} 份{note_str}")

    db.commit()
    return f"✅ {user_name} 點了：\n  " + "\n  ".join(result_lines) + f"\n本次小計：${total}"


def cancel_order(db: Session, group_id: str, user_id: str, user_name: str, item_number: int) -> str:
    order = get_open_order(db, group_id)
    if not order:
        return "目前沒有開放點餐"

    item = db.query(MenuItem).filter(MenuItem.menu_id == order.menu_id, MenuItem.number == item_number).first()
    if not item:
        return f"找不到編號 {item_number} 的品項，請用 /menu 查看菜單"

    existing = _get_order_item(db, order.order_id, user_id, item.item_id)
    if not existing:
        return f"{user_name} 尚未點「{item.name}」"

    db.delete(existing)
    db.commit()
    return f"❌ {user_name} 已取消「{item.name}」"


def reduce_order(db: Session, group_id: str, user_id: str, user_name: str, item_number: int) -> str:
    order = get_open_order(db, group_id)
    if not order:
        return "目前沒有開放點餐"

    item = db.query(MenuItem).filter(MenuItem.menu_id == order.menu_id, MenuItem.number == item_number).first()
    if not item:
        return f"找不到編號 {item_number} 的品項，請用 /menu 查看菜單"

    existing = _get_order_item(db, order.order_id, user_id, item.item_id)
    if not existing:
        return f"{user_name} 尚未點「{item.name}」"

    if existing.quantity <= 1:
        db.delete(existing)
        db.commit()
        return f"❌ {user_name} 已取消「{item.name}」（最後一份）"
    else:
        existing.quantity -= 1
        db.commit()
        return f"✅ {user_name} 的「{item.name}」減為 {existing.quantity} 份"


def cancel_order_multi(db: Session, group_id: str, user_id: str, user_name: str, item_numbers: list) -> str:
    """一次取消多個品項（整筆刪除，不分數量；重複編號視為同一筆）。"""
    order = get_open_order(db, group_id)
    if not order:
        return "目前沒有開放點餐"

    seen = []
    for number in item_numbers:
        if number not in seen:
            seen.append(number)

    results = []
    for number in seen:
        item = db.query(MenuItem).filter(MenuItem.menu_id == order.menu_id, MenuItem.number == number).first()
        if not item:
            results.append(f"找不到編號 {number} 的品項")
            continue
        existing = _get_order_item(db, order.order_id, user_id, item.item_id)
        if not existing:
            results.append(f"尚未點「{item.name}」")
            continue
        db.delete(existing)
        results.append(f"❌ 已取消「{item.name}」")

    db.commit()
    return f"{user_name}：\n  " + "\n  ".join(results)


def reduce_order_multi(db: Session, group_id: str, user_id: str, user_name: str, item_numbers: list) -> str:
    """一次減少多個品項各 1 份，重複編號代表減少多份（如 [1, 1] 代表編號1減2份）。"""
    order = get_open_order(db, group_id)
    if not order:
        return "目前沒有開放點餐"

    counts = Counter(item_numbers)
    results = []
    for number, times in counts.items():
        item = db.query(MenuItem).filter(MenuItem.menu_id == order.menu_id, MenuItem.number == number).first()
        if not item:
            results.append(f"找不到編號 {number} 的品項")
            continue
        existing = _get_order_item(db, order.order_id, user_id, item.item_id)
        if not existing:
            results.append(f"尚未點「{item.name}」")
            continue
        for _ in range(times):
            if existing.quantity <= 1:
                db.delete(existing)
                results.append(f"❌「{item.name}」已取消（最後一份）")
                existing = None
                break
            existing.quantity -= 1
        else:
            results.append(f"✅「{item.name}」減為 {existing.quantity} 份")

    db.commit()
    return f"{user_name}：\n  " + "\n  ".join(results)


def apply_history_to_order(db: Session, group_id: str, order: Order, index: int, limit: int = 10) -> str:
    """把過去某次結單（/history 顯示的編號）的品項複製到目前開單，作為初始品項。
    若原品項已不存在於目前菜單（item_id 已被刪除的菜單移除），該筆會略過。"""
    past_orders = (
        db.query(Order)
        .filter(Order.group_id == group_id, Order.is_open == False)
        .order_by(desc(Order.closed_at))
        .limit(limit)
        .all()
    )
    if not past_orders:
        return "⚠️ 尚無歷史紀錄可套用"

    if index < 1 or index > len(past_orders):
        return f"⚠️ 歷史編號 {index} 不存在，套用失敗，請先用 /history 確認編號"

    past_order = past_orders[index - 1]
    copied = 0
    skipped = 0
    for oi in past_order.order_items:
        item = db.query(MenuItem).filter(MenuItem.item_id == oi.item_id).first()
        if not item:
            skipped += 1
            continue
        db.add(OrderItem(
            order_id=order.order_id,
            user_id=oi.user_id,
            user_name=oi.user_name,
            item_id=oi.item_id,
            quantity=oi.quantity,
            note=oi.note,
        ))
        copied += 1
    db.commit()

    msg = f"📋 已套用歷史紀錄，複製 {copied} 筆品項"
    if skipped:
        msg += f"（{skipped} 筆品項已不存在於菜單中，略過）"
    return msg


def get_order_status(db: Session, group_id: str) -> str:
    order = get_open_order(db, group_id)
    if not order:
        return "目前沒有進行中的點餐"

    items = sorted(order.order_items, key=lambda oi: oi.id)
    if not items:
        return "目前還沒有人點餐"

    # 序號依全部品項的順序連續編號，與下方 admin_cancel_order_item 對應
    index_map = {oi.id: idx + 1 for idx, oi in enumerate(items)}

    user_items: dict = defaultdict(list)
    for oi in items:
        user_items[oi.user_name].append(oi)

    lines = ["📊 目前點餐狀況：\n"]
    total = 0
    for user_name, ois in user_items.items():
        lines.append(f"  {user_name}：")
        for oi in ois:
            subtotal = oi.item.price * oi.quantity
            total += subtotal
            qty_str = f" x{oi.quantity}" if oi.quantity > 1 else ""
            note_str = f"（{oi.note}）" if oi.note else ""
            lines.append(f"    [{index_map[oi.id]}] {oi.item.name}{qty_str} ${subtotal}{note_str}")

    lines.append(f"\n💰 目前合計：${total}")
    lines.append("\n（管理員可用 /admincancel <序號> 取消他人品項）")
    return "\n".join(lines)


def admin_cancel_order_item(db: Session, group_id: str, index: int) -> str:
    """管理員依 /status 顯示的序號，取消任何人點的品項（整筆刪除，不分數量）。"""
    order = get_open_order(db, group_id)
    if not order:
        return "目前沒有進行中的點餐"

    items = sorted(order.order_items, key=lambda oi: oi.id)
    if not items:
        return "目前還沒有人點餐"

    if index < 1 or index > len(items):
        return f"序號 {index} 不存在，請先用 /status 確認序號"

    target = items[index - 1]
    name = target.item.name
    user_name = target.user_name
    db.delete(target)
    db.commit()
    return f"✅ 已取消 {user_name} 的「{name}」"


def clear_order_items(db: Session, group_id: str) -> str:
    """清空目前開單所有人的點餐品項，但不結單（點餐仍維持開放狀態）。"""
    order = get_open_order(db, group_id)
    if not order:
        return "目前沒有進行中的點餐"

    count = len(order.order_items)
    if count == 0:
        return "目前還沒有人點餐，無需清除"

    for oi in list(order.order_items):
        db.delete(oi)
    db.commit()
    return f"✅ 已清除本輪所有點餐品項（共 {count} 筆），點餐仍開放中"


def _format_order_summary(order: Order, store: Optional[Menu] = None) -> str:
    """格式化一次結單的摘要，供 close_order 和 history 詳細查詢共用"""
    store_name = store.store_name if store else "未知店家"
    date_str = to_taipei(order.closed_at).strftime("%m/%d %H:%M") if order.closed_at else "未知"

    items = order.order_items
    if not items:
        return f"🧾 {store_name}（{date_str}）\n無點餐紀錄"

    lines = [f"🧾 {store_name}（{date_str}）\n"]
    total = 0
    personal: dict = defaultdict(int)
    user_items: dict = defaultdict(list)

    for oi in items:
        user_items[oi.user_name].append(oi)

    for user_name, ois in user_items.items():
        lines.append(f"  {user_name}：")
        for oi in ois:
            subtotal = oi.item.price * oi.quantity
            total += subtotal
            personal[user_name] += subtotal
            qty_str = f" x{oi.quantity}" if oi.quantity > 1 else ""
            note_str = f"（{oi.note}）" if oi.note else ""
            lines.append(f"    • {oi.item.name}{qty_str} ${subtotal}{note_str}")

    lines.append(f"\n💰 總計：${total}\n")
    lines.append("📬 個人應付：")
    for name, amount in personal.items():
        lines.append(f"  {name}：${amount}")

    return "\n".join(lines)


def close_order(db: Session, group_id: str) -> str:
    from datetime import datetime
    order = get_open_order(db, group_id)
    if not order:
        return "目前沒有進行中的點餐"

    order.is_open = False
    order.closed_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(order)

    store = db.query(Menu).filter(Menu.menu_id == order.menu_id).first()
    return "✅ 已結單！\n\n" + _format_order_summary(order, store)


# ── 歷史紀錄 ──────────────────────────────────────────

def get_group_history(db: Session, group_id: str, limit: int = 10) -> str:
    """列出最近 10 次結單清單，可用編號查詳情"""
    orders = (
        db.query(Order)
        .filter(Order.group_id == group_id, Order.is_open == False)
        .order_by(desc(Order.closed_at))
        .limit(limit)
        .all()
    )
    if not orders:
        return "尚無歷史紀錄"

    lines = [f"📚 最近 {limit} 次點餐紀錄：\n"]
    for idx, order in enumerate(orders, start=1):
        date_str = to_taipei(order.closed_at).strftime("%m/%d %H:%M") if order.closed_at else "未知"
        store = db.query(Menu).filter(Menu.menu_id == order.menu_id).first()
        store_name = store.store_name if store else "未知店家"
        total = sum(oi.item.price * oi.quantity for oi in order.order_items)
        lines.append(f"  {idx}. {date_str}｜{store_name}｜合計 ${total}")

    lines.append("\n輸入 /history <編號> 查看詳細結單摘要")
    return "\n".join(lines)


def get_group_history_detail(db: Session, group_id: str, index: int, limit: int = 10) -> str:
    """查看某次結單的詳細摘要"""
    orders = (
        db.query(Order)
        .filter(Order.group_id == group_id, Order.is_open == False)
        .order_by(desc(Order.closed_at))
        .limit(limit)
        .all()
    )
    if not orders:
        return "尚無歷史紀錄"

    if index < 1 or index > len(orders):
        return f"編號 {index} 不存在，請用 /history 確認編號"

    order = orders[index - 1]
    store = db.query(Menu).filter(Menu.menu_id == order.menu_id).first()
    return _format_order_summary(order, store)


def get_user_history(db: Session, group_id: str, user_id: str, user_name: str, limit: int = 10) -> str:
    """依「訂單」分組顯示使用者的點餐歷史，同一次結單的品項會列在一起，
    而不是像品項清單一樣把每個品項拆開各佔一行。"""
    orders = (
        db.query(Order)
        .join(OrderItem, OrderItem.order_id == Order.order_id)
        .filter(Order.group_id == group_id, OrderItem.user_id == user_id, Order.is_open == False)
        .order_by(desc(Order.closed_at))
        .distinct()
        .limit(limit)
        .all()
    )
    if not orders:
        return f"{user_name} 尚無點餐紀錄"

    lines = [f"📖 {user_name} 的最近 {len(orders)} 筆點餐紀錄：\n"]
    for order in orders:
        date_str = to_taipei(order.closed_at).strftime("%m/%d %H:%M") if order.closed_at else "未知"
        store = db.query(Menu).filter(Menu.menu_id == order.menu_id).first()
        store_name = store.store_name if store else "未知店家"
        user_items = [oi for oi in order.order_items if oi.user_id == user_id]

        lines.append(f"  {date_str}｜{store_name}")
        subtotal_total = 0
        for oi in user_items:
            qty_str = f" x{oi.quantity}" if oi.quantity > 1 else ""
            note_str = f"（{oi.note}）" if oi.note else ""
            subtotal = oi.item.price * oi.quantity
            subtotal_total += subtotal
            lines.append(f"    {oi.item.name}{qty_str} ${subtotal}{note_str}")
        lines.append(f"    小計：${subtotal_total}\n")

    return "\n".join(lines)


# ── 刪除（菜單／歷史紀錄）────────────────────────────

def delete_menu(db: Session, group_id: str, index: int) -> str:
    """刪除指定編號的菜單，會連同該菜單底下所有的點餐紀錄（含歷史）一併刪除。
    若該菜單目前有「開單中」尚未結單的訂單，會先擋下來，避免誤刪進行中的點餐。
    若刪除的是目前使用中的菜單，會自動切換到清單中下一份最新的菜單。"""
    menus = get_all_menus(db, group_id)
    if not menus:
        return "尚未建立任何菜單"

    if index < 1 or index > len(menus):
        return f"編號 {index} 不存在，請用 /menulist 確認編號"

    target = menus[index - 1]

    open_order = db.query(Order).filter(Order.menu_id == target.menu_id, Order.is_open == True).first()
    if open_order:
        return f"❌「{target.store_name}」目前有開單中的點餐，請先 /done 結單後再刪除"

    orders = db.query(Order).filter(Order.menu_id == target.menu_id).all()
    order_count = len(orders)
    for order in orders:
        db.delete(order)  # OrderItem 設有 cascade="all, delete-orphan"，會一併刪除

    was_active = target.is_active
    store_name = target.store_name
    db.delete(target)
    db.commit()

    msg = f"✅ 已刪除「{store_name}」"
    if order_count:
        msg += f"，並一併刪除 {order_count} 筆相關點餐紀錄（含歷史）"

    if was_active:
        remaining = get_all_menus(db, group_id)
        if remaining:
            remaining[0].is_active = True
            db.commit()
            msg += f"\n已自動切換至「{remaining[0].store_name}」"
        else:
            msg += "\n目前沒有其他菜單，請上傳 .txt 檔案建立"

    return msg


def delete_history(db: Session, group_id: str, index: int, limit: int = 10) -> str:
    """刪除指定編號的歷史結單紀錄（編號對應 /history 清單顯示的編號）。"""
    orders = (
        db.query(Order)
        .filter(Order.group_id == group_id, Order.is_open == False)
        .order_by(desc(Order.closed_at))
        .limit(limit)
        .all()
    )
    if not orders:
        return "尚無歷史紀錄"

    if index < 1 or index > len(orders):
        return f"編號 {index} 不存在，請用 /history 確認編號"

    target = orders[index - 1]
    store = db.query(Menu).filter(Menu.menu_id == target.menu_id).first()
    store_name = store.store_name if store else "未知店家"
    date_str = to_taipei(target.closed_at).strftime("%m/%d %H:%M") if target.closed_at else "未知"

    db.delete(target)  # OrderItem 設有 cascade="all, delete-orphan"，會一併刪除
    db.commit()

    return f"✅ 已刪除歷史紀錄：{date_str}｜{store_name}"