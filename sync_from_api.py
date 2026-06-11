import os
import sys
import time
import requests
import re


API_KEY = os.environ.get("FLOWUS_API_KEY")
PAGE_ID = os.environ.get("FLOWUS_PAGE_ID")
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


def get_page(page_id):
    url = f"{BASE_URL}/v1/pages/{page_id}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    print(f"  [WARN] get_page({page_id}) failed: {resp.status_code} {resp.text[:200]}")
    return None


def get_block(block_id):
    url = f"{BASE_URL}/v1/blocks/{block_id}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    print(f"  [WARN] get_block({block_id}) failed: {resp.status_code}")
    return None


def get_block_children(block_id, start_cursor=None):
    url = f"{BASE_URL}/v1/blocks/{block_id}/children?page_size=100"
    if start_cursor:
        url += f"&start_cursor={start_cursor}"
    resp = requests.get(url, headers=HEADERS)
    if resp.status_code == 200:
        return resp.json()
    print(f"  [WARN] get_block_children({block_id}) failed: {resp.status_code}")
    return {"results": [], "has_more": False}


def fetch_all_children(block_id):
    all_results = []
    cursor = None
    while True:
        data = get_block_children(block_id, cursor)
        all_results.extend(data.get("results", []))
        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")
    return all_results


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


def process_full_page(page_id, page_title=None, top_level=False):
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
    else:
        page_title = "FlowUs Notes"

    print(f"Page title: {page_title}")
    process_full_page(PAGE_ID, page_title, top_level=True)
    print("Done! All notes synced.")


if __name__ == "__main__":
    main()
