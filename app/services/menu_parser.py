import re
from typing import Optional

STORE_CATEGORIES = ["飲料", "餐點", "其他"]


def parse_menu_from_txt(content: str) -> Optional[dict]:
    lines = [line.strip() for line in content.splitlines()]
    lines = [l for l in lines if l]

    if not lines:
        return None

    store_name = "未知店家"
    item_start = 0

    first_line = lines[0]
    store_match = re.match(r"^店名[：:]\s*(.+)$", first_line)
    if store_match:
        store_name = store_match.group(1).strip()
        item_start = 1
    elif not re.search(r"\d+\s*$", first_line) and not first_line.startswith("#"):
        store_name = first_line
        item_start = 1

    # 選填：店名下一行可以寫「分類：飲料」，標示這整間店屬於哪一類
    # 沒寫的話預設歸類到「其他」
    store_category = "其他"
    if item_start < len(lines):
        category_match = re.match(r"^分類[：:]\s*(.+)$", lines[item_start])
        if category_match:
            store_category = category_match.group(1).strip()
            item_start += 1

    items = []
    number = 1
    current_category = "其他"  # 沒有用 # 標分類的品項，預設歸類到「其他」

    for line in lines[item_start:]:
        if line.startswith("#"):
            current_category = line.lstrip("#").strip()
            continue

        match = re.match(r"^(.+?)\s+(\d+)\s*$", line)
        if not match:
            continue

        name = match.group(1).strip()
        price = int(match.group(2))
        items.append({
            "number": number,
            "name": name,
            "price": price,
            "category": current_category,
        })
        number += 1

    if not items:
        return None

    return {"store_name": store_name, "category": store_category, "items": items}