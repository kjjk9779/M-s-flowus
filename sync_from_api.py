import os
import sys
import time
import requests
import re


API_KEY = os.environ.get("FLOWUS_API_KEY", "").strip()
PAGE_ID = os.environ.get("FLOWUS_PAGE_ID", "").strip()
BASE_URL = "https://api.flowus.cn"

HEADERS = {
    "Authorization": f"Bearer {API_KEY}",
    "Content-Type": "application/json",
}

NOTES_DIR = "notes"
os.makedirs(NOTES_DIR, exist_ok=True)


def slugify(text):
    text = text.strip()
    text = re.sub(r'[\\/:*?"<>|]', "_", text)
    text = re.sub(r'\s+', "_", text)
    return text[:80]


def check_403(resp, context=""):
    if resp.status_code == 403:
        print(f"  [ERROR] {context} 返回 403 Forbidden")
        print(f"  [ERROR] 你的 API Token 没有权限访问该页面。")
        print(f"  [ERROR] 请确保在 FlowUs 页面右上角「分享」中，已将页面授权给你的 Bot/应用。")
        print(f"  [ERROR] 响应内容: {resp.text[:300]}")
        return True
    return False


def get_page(page_id):
    url = f"{BASE_URL}/v1/pages/{page_id}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    check_403(resp, f"get_page({page_id})")
    if resp.status_code != 403:
        print(f"  [WARN] get_page({page_id}) failed: {resp.status_code} {resp.text[:200]}")
    return None


def get_block(block_id):
    url = f"{BASE_URL}/v1/blocks/{block_id}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    if not check_403(resp, f"get_block({block_id})"):
        print(f"  [WARN] get_block({block_id}) failed: {resp.status_code}")
    return None


def get_block_children(block_id, start_cursor=None):
    url = f"{BASE_URL}/v1/blocks/{block_id}/children?page_size=100"
    if start_cursor:
        url += f"&start_cursor={start_cursor}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    if not check_403(resp, f"get_block_children({block_id})"):
        print(f"  [WARN] get_block_children({block_id}) failed: {resp.status_code}")
    return {"results": [], "has_more": False}


def fetch_all_children(block_id, use_internal_api=False):
    if use_internal_api:
        return fetch_all_children_internal(block_id)
    all_results = []
    cursor = None
    while True:
        data = get_block_children(block_id, cursor)
        all_results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return all_results


def fetch_page_internal(page_id):
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "FlowUs X",
        "app_version_name": "1.51.0",
    }
    urls_to_try = [
        f"https://flowus.cn/api/docs/{page_id}",
        f"https://flowus.cn/api/share/{page_id}",
    ]
    for url in urls_to_try:
        resp = requests.get(url, headers=headers)
        if resp.status_code == 200:
            raw = resp.json()
            code = raw.get("code")
            if code in (0, 200):
                content = raw.get("data", {})
                blocks = content.get("blocks", {})
                print(f"  [INFO] Internal API ({url}) returned {len(blocks)} blocks")
                if not blocks:
                    print(f"  [DEBUG] Raw response (first 500 chars): {str(raw)[:500]}")
                title = extract_internal_title(blocks) or "FlowUs Notes"
                return {"title": title, "blocks": blocks}
            else:
                print(f"  [WARN] Internal API ({url}) returned code={code}: {str(raw)[:200]}")
        else:
            print(f"  [WARN] Internal API ({url}) failed: {resp.status_code}")
    return None


def extract_internal_title(blocks):
    for bid, block in blocks.items():
        if block.get("type") == 0:
            return block.get("title", "") or segments_to_md(block.get("data", {}).get("segments", []))
    return None


def fetch_all_children_internal(page_id):
    data = fetch_page_internal(page_id)
    if not data:
        return []
    return data.get("blocks", {})


def segments_to_md(segments):
    parts = []
    for seg in segments or []:
        text = seg.get("text", "")
        enhancer = seg.get("enhancer", {})
        if enhancer.get("code"):
            text = f"`{text}`"
        if enhancer.get("bold"):
            text = f"**{text}**"
        if enhancer.get("italic"):
            text = f"*{text}*"
        if enhancer.get("lineThrough"):
            text = f"~~{text}~~"
        seg_type = seg.get("type", 0)
        url = seg.get("url", "")
        if seg_type == 3 and url:
            text = f"[{text}]({url})"
        parts.append(text)
    return "".join(parts)


def convert_internal_block(block, blocks_dict, depth=0):
    btype = block.get("type", -1)
    data = block.get("data", {})
    sub_nodes = block.get("subNodes", [])
    indent = "  " * depth
    md = ""

    if btype == 0:
        return "", False

    elif btype == 1:
        level = data.get("level", 0)
        text = segments_to_md(data.get("segments", []))
        if level == 0:
            if text.strip():
                md += f"{text}\n\n"
        else:
            prefix = "#" * min(level + 1, 6)
            md += f"{prefix} {text}\n\n"

    elif btype == 3:
        text = segments_to_md(data.get("segments", []))
        checked = data.get("checked", False)
        cb = "[x]" if checked else "[ ]"
        if text.strip():
            md += f"{indent}- {cb} {text}\n"

    elif btype == 4:
        text = segments_to_md(data.get("segments", []))
        if text.strip():
            md += f"{indent}- {text}\n"

    elif btype == 5:
        text = segments_to_md(data.get("segments", []))
        if text.strip():
            md += f"{indent}1. {text}\n"

    elif btype == 6:
        text = segments_to_md(data.get("segments", []))
        md += f"{indent}<details>\n<summary>{text}</summary>\n\n"
        for child_uuid in sub_nodes:
            child = blocks_dict.get(child_uuid)
            if child:
                child_md, _ = convert_internal_block(child, blocks_dict, depth + 1)
                md += child_md
        md += f"{indent}</details>\n\n"
        return md, True

    elif btype == 7:
        text = segments_to_md(data.get("segments", []))
        if text.strip():
            md += f"# {text}\n\n"

    elif btype == 9:
        md += f"{indent}---\n\n"

    elif btype == 12:
        text = segments_to_md(data.get("segments", []))
        if text.strip():
            md += f"{indent}> {text}\n\n"

    elif btype == 13:
        text = segments_to_md(data.get("segments", []))
        if text.strip():
            md += f"{text}\n\n"

    elif btype == 14:
        display = data.get("display", "")
        oss_name = data.get("ossName", "")
        if display == "image" and oss_name:
            url = f"https://flowus.cn/api/file/{oss_name}"
            md += f"{indent}![Image]({url})\n\n"
        elif oss_name:
            url = f"https://flowus.cn/api/file/{oss_name}"
            caption = block.get("title", "File")
            md += f"{indent}[{caption}]({url})\n\n"

    elif btype == 16:
        ref = data.get("ref", {})
        ref_uuid = ref.get("uuid", "")
        title = block.get("title", "Linked Page")
        md += f"{indent}[{title}](https://flowus.cn/page/{ref_uuid})\n\n"

    elif btype == 18:
        title = block.get("title", "Database")
        md += f"{indent}## Database: {title}\n\n"

    elif btype == 20:
        link = data.get("link", "")
        md += f"{indent}[Embedded Page]({link})\n\n"

    elif btype == 21:
        link = data.get("link", "")
        text = segments_to_md(data.get("linkInfo", []))
        display = text or link
        md += f"{indent}[{display}]({link})\n\n"

    elif btype == 23:
        text = segments_to_md(data.get("segments", []))
        md += f"{indent}$${text}$$\n\n"

    elif btype == 25:
        text = segments_to_md(data.get("segments", []))
        lang = data.get("format", {}).get("language", "")
        md += f"{indent}```{lang}\n{text}\n```\n\n"

    elif btype == 27:
        md += f"{indent}<!-- table -->\n"
        for child_uuid in sub_nodes:
            child = blocks_dict.get(child_uuid)
            if child and child.get("type") == 28:
                row_data = child.get("data", {})
                coll_props = row_data.get("collectionProperties", {})
                cells = []
                for col_key in sorted(coll_props.keys()):
                    decorations = coll_props[col_key]
                    cell_text = segments_to_md(decorations)
                    cells.append(cell_text)
                md += f"{indent}| {' | '.join(cells)} |\n"
        md += "\n"
        return md, True

    elif btype == 38:
        text = segments_to_md(data.get("segments", []))
        md += f"{indent}<details>\n<summary>{text}</summary>\n\n"
        for child_uuid in sub_nodes:
            child = blocks_dict.get(child_uuid)
            if child:
                child_md, _ = convert_internal_block(child, blocks_dict, depth + 1)
                md += child_md
        md += f"{indent}</details>\n\n"
        return md, True

    elif btype == 36 or btype == 37:
        md += f"{indent}<!-- mindmap -->\n"
        for child_uuid in sub_nodes:
            child = blocks_dict.get(child_uuid)
            if child:
                child_md, _ = convert_internal_block(child, blocks_dict, depth + 1)
                md += child_md
        return md, True

    else:
        text = block.get("title", "")
        if text:
            md += f"{text}\n\n"

    return md, False


def extract_rich_text(rich_text_list):
    parts = []
    for item in rich_text_list or []:
        text = item.get("plainText") or ""
        if not text:
            if item.get("type") == "text":
                text = (item.get("text") or {}).get("content") or ""
            else:
                text = item.get("plainText") or ""

        annotations = item.get("annotations") or {}
        if annotations.get("code"):
            text = f"`{text}`"
        if annotations.get("bold"):
            text = f"**{text}**"
        if annotations.get("italic"):
            text = f"*{text}*"
        if annotations.get("strikethrough"):
            text = f"~~{text}~~"

        href = item.get("href")
        if not href:
            text_obj = (item.get("text") or {})
            link = text_obj.get("link")
            if link:
                href = link.get("url")

        if href:
            text = f"[{text}]({href})"

        parts.append(text)

    return "".join(parts)


def extract_plain_text(rich_text_list):
    parts = []
    for item in rich_text_list or []:
        text = item.get("plainText") or ""
        if not text:
            if item.get("type") == "text":
                text = (item.get("text") or {}).get("content") or ""
        parts.append(text)
    return "".join(parts)


def is_empty_block(block):
    if block.get("hasChildren"):
        return False
    data = block.get("data") or {}
    rich_text = data.get("richText") or []
    if not rich_text:
        return True
    text = extract_plain_text(rich_text)
    return text.strip() == ""


def process_block(block, depth=0):
    block_type = block.get("type", "paragraph")
    data = block.get("data") or {}
    has_children = block.get("hasChildren", False)
    block_id = block.get("id", "")

    indent = "  " * depth
    md = ""

    if block_type == "paragraph":
        text = extract_rich_text(data.get("richText") or [])
        if text.strip():
            md += f"{text}\n\n"

    elif block_type == "heading_1":
        text = extract_rich_text(data.get("richText") or [])
        if text.strip():
            md += f"# {text}\n\n"

    elif block_type == "heading_2":
        text = extract_rich_text(data.get("richText") or [])
        if text.strip():
            md += f"## {text}\n\n"

    elif block_type == "heading_3":
        text = extract_rich_text(data.get("richText") or [])
        if text.strip():
            md += f"### {text}\n\n"

    elif block_type == "bulleted_list_item":
        text = extract_rich_text(data.get("richText") or [])
        if text.strip():
            md += f"{indent}- {text}\n"

    elif block_type == "numbered_list_item":
        text = extract_rich_text(data.get("richText") or [])
        if text.strip():
            md += f"{indent}1. {text}\n"

    elif block_type == "to_do":
        text = extract_rich_text(data.get("richText") or [])
        checked = data.get("checked", False)
        checkbox = "[x]" if checked else "[ ]"
        if text.strip():
            md += f"{indent}- {checkbox} {text}\n"

    elif block_type == "quote":
        text = extract_rich_text(data.get("richText") or [])
        if text.strip():
            lines = text.split("\n")
            for line in lines:
                md += f"{indent}> {line}\n"
            md += "\n"

    elif block_type == "code":
        text = extract_plain_text(data.get("richText") or [])
        language = data.get("language", "")
        md += f"{indent}```{language}\n{text}\n```\n\n"

    elif block_type == "divider":
        md += f"{indent}---\n\n"

    elif block_type == "image":
        url = data.get("url") or ""
        caption = extract_plain_text(data.get("caption") or [])
        if caption:
            md += f"{indent}![{caption}]({url})\n\n"
        elif url:
            md += f"{indent}![Image]({url})\n\n"

    elif block_type == "file":
        url = data.get("url") or ""
        text = extract_plain_text(data.get("richText") or [])
        display = text or "File"
        if url:
            md += f"{indent}[{display}]({url})\n\n"

    elif block_type == "bookmark":
        url = data.get("url") or ""
        text = extract_plain_text(data.get("richText") or [])
        display = text or url
        if url:
            md += f"{indent}[{display}]({url})\n\n"

    elif block_type == "callout":
        icon = ""
        icon_data = data.get("icon")
        if icon_data:
            icon = icon_data.get("emoji") or icon_data.get("external", {}).get("url") or ""
        text = extract_rich_text(data.get("richText") or [])
        md += f"{indent}> {icon} {text}\n\n"

    elif block_type == "toggle":
        text = extract_rich_text(data.get("richText") or [])
        md += f"{indent}<details>\n<summary>{text}</summary>\n\n"
        if has_children:
            children = fetch_all_children(block_id)
            for child in children:
                md += process_block(child, depth + 1)
        md += f"{indent}</details>\n\n"
        # already processed children, skip the generic children handling below
        return md, True

    elif block_type == "column_list":
        md += f"{indent}<!-- columns start -->\n\n"
        if has_children:
            children = fetch_all_children(block_id)
            for child in children:
                md += process_block(child, depth)
        md += f"{indent}<!-- columns end -->\n\n"
        return md, True

    elif block_type == "column":
        if has_children:
            children = fetch_all_children(block_id)
            for child in children:
                md += process_block(child, depth)

    elif block_type == "table":
        md += f"{indent}<!-- table start -->\n\n"
        if has_children:
            children = fetch_all_children(block_id)
            for child in children:
                md += process_block(child, depth)
        md += f"{indent}<!-- table end -->\n\n"
        return md, True

    elif block_type == "table_row":
        cells = data.get("cells") or []
        row_parts = []
        for cell in cells:
            cell_text = extract_rich_text(cell or [])
            row_parts.append(cell_text)
        md += f"{indent}| {' | '.join(row_parts)} |\n"

    elif block_type == "child_page":
        title = data.get("title") or "Untitled"
        child_page_id = block_id
        if child_page_id:
            print(f"  Processing child page: {title} ({child_page_id})")
            process_full_page(child_page_id, title)
        md += f"{indent}[{title}]({slugify(title)}.md)\n\n"

    elif block_type == "child_database":
        title = data.get("title") or "Untitled Database"
        md += f"{indent}## Database: {title}\n\n"

    elif block_type == "equation":
        expression = data.get("expression") or ""
        md += f"{indent}$${expression}$$\n\n"

    elif block_type == "link_to_page":
        page_id = data.get("pageId") or ""
        md += f"{indent}[Link to page](https://flowus.cn/page/{page_id})\n\n"

    elif block_type == "synced_block":
        if has_children:
            children = fetch_all_children(block_id)
            for child in children:
                md += process_block(child, depth)

    else:
        text = extract_rich_text(data.get("richText") or [])
        if text.strip():
            md += f"{text}\n\n"

    return md, False


def process_full_page(page_id, page_title=None, top_level=False, use_internal_api=False):
    if not page_title:
        if use_internal_api:
            internal_data = fetch_page_internal(page_id)
            if internal_data:
                page_title = internal_data.get("title", "Untitled")
        if not page_title:
            page_data = get_page(page_id)
            if page_data:
                props = page_data.get("properties", {})
                title_prop = props.get("title", {})
                title_list = title_prop.get("title", [])
                page_title = extract_plain_text(title_list) or "Untitled"
            else:
                page_title = "Untitled"

    safe_name = slugify(page_title)
    if top_level:
        file_path = os.path.join(NOTES_DIR, f"{safe_name}.md")
    else:
        sub_dir = os.path.join(NOTES_DIR, slugify(page_title) if not top_level else "")
        os.makedirs(sub_dir, exist_ok=True)
        file_path = os.path.join(sub_dir, f"{safe_name}.md")

    print(f"  -> Generating: {file_path}")

    if use_internal_api:
        internal_data = fetch_page_internal(page_id)
        if internal_data:
            blocks = internal_data.get("blocks", {})
            full_md = f"# {page_title}\n\n"
            root_block = blocks.get(page_id)
            if not root_block:
                for bid, b in blocks.items():
                    if b.get("type") == 0:
                        root_block = b
                        break
            if root_block:
                sub_nodes = root_block.get("subNodes", [])
                for child_uuid in sub_nodes:
                    child = blocks.get(child_uuid)
                    if child:
                        md_text, _ = convert_internal_block(child, blocks)
                        full_md += md_text
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(full_md)
            print(f"  [OK] Saved: {file_path}")
            return file_path
        else:
            print("  [ERROR] Internal API also failed.")
            return None

    full_md = f"# {page_title}\n\n"

    children = fetch_all_children(page_id)
    i = 0
    while i < len(children):
        block = children[i]
        if is_empty_block(block) and not block.get("hasChildren"):
            i += 1
            continue

        block_type = block.get("type", "paragraph")

        md_text, skip_children = process_block(block)
        full_md += md_text

        if block_type in ("numbered_list_item",):
            while i + 1 < len(children):
                next_block = children[i + 1]
                if next_block.get("type") == "numbered_list_item":
                    md_text, _ = process_block(next_block)
                    full_md += md_text
                    i += 1
                else:
                    break
            full_md += "\n"

        i += 1

    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as f:
        f.write(full_md)

    print(f"  [OK] Saved: {file_path}")
    return file_path


def main():
    if not API_KEY:
        print("ERROR: FLOWUS_API_KEY environment variable not set")
        sys.exit(1)
    if not PAGE_ID:
        print("ERROR: FLOWUS_PAGE_ID environment variable not set")
        sys.exit(1)

    print(f"Fetching FlowUs page: {PAGE_ID}")

    page_data = get_page(PAGE_ID)
    if page_data:
        props = page_data.get("properties", {})
        title_prop = props.get("title", {})
        title_list = title_prop.get("title", [])
        page_title = extract_plain_text(title_list) or "FlowUs Notes"
        print(f"Page title: {page_title}")
        process_full_page(PAGE_ID, page_title, top_level=True)
        print("Done! All notes synced.")
    else:
        print("[INFO] 官方 API 鉴权失败，尝试使用内部 API（无需鉴权）获取公开页面...")
        internal_data = fetch_page_internal(PAGE_ID)
        if internal_data:
            page_title = internal_data.get("title", "FlowUs Notes")
            print(f"Page title: {page_title}")
            process_full_page(PAGE_ID, page_title, top_level=True, use_internal_api=True)
            print("Done! All notes synced (via internal API).")
        else:
            print("[ERROR] 内部 API 也失败了，无法获取页面内容。")
            print("[HELP] 请检查：")
            print("[HELP] 1. FLOWUS_API_KEY 是否正确（在 FlowUs 开发者后台创建应用获取）")
            print("[HELP] 2. 该页面是否已授权给你的 Bot（在页面右上角「分享」中添加你的应用）")
            print("[HELP] 3. PAGE_ID 是否为页面真实的 UUID（可在分享链接中获得）")
            sys.exit(1)


if __name__ == "__main__":
    main()
