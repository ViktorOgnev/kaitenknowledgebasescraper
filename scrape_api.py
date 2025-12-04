import os
import re
import time
import logging
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from readability import Document
import html2text
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeoutError

BASE_URL = "https://developers.kaiten.ru"
OUTPUT_DIR = "out_developers"
DELAY_BETWEEN_PAGES = 0.3  # секунд

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)


def is_same_domain(url: str) -> bool:
    try:
        return urlparse(url).netloc == urlparse(BASE_URL).netloc
    except Exception:
        return False


def looks_like_binary(url: str) -> bool:
    path = urlparse(url).path.lower()
    bad_ext = [
        ".png", ".jpg", ".jpeg", ".gif", ".svg",
        ".webp", ".ico", ".mp4", ".mov", ".avi",
        ".pdf", ".zip", ".rar", ".7z",
        ".css", ".js", ".map", ".woff", ".woff2", ".ttf"
    ]
    return any(path.endswith(ext) for ext in bad_ext)


def make_slug(text: str) -> str:
    text = text.strip()
    text = re.sub(r"[^0-9A-Za-zА-Яа-я]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-") or "page"


def extract_article_text(html: str) -> tuple[str, str]:
    doc = Document(html)
    title = doc.short_title() or "Без названия"
    article_html = doc.summary(html_partial=True)

    h = html2text.HTML2Text()
    h.ignore_images = True
    h.ignore_emphasis = False
    h.ignore_links = False
    h.body_width = 0

    body_md = h.handle(article_html)
    return title, body_md


def make_path_from_url(url: str, title: str) -> str:
    parsed = urlparse(url)
    path = parsed.path.strip("/")

    if not path:
        dir_path = OUTPUT_DIR
        os.makedirs(dir_path, exist_ok=True)
        return os.path.join(dir_path, "index.md")

    parts = [p for p in path.split("/") if p]
    ends_with_slash = parsed.path.endswith("/")

    if ends_with_slash:
        dir_parts = parts
        file_stem = "index"
    else:
        if len(parts) == 1:
            dir_parts = []
            file_stem = parts[0]
        else:
            dir_parts = parts[:-1]
            file_stem = parts[-1]

    if "." in file_stem:
        file_stem = file_stem.rsplit(".", 1)[0]

    if not file_stem:
        file_stem = make_slug(title)

    file_stem = re.sub(r"[^\w\-А-Яа-я]", "_", file_stem)
    dir_path = os.path.join(OUTPUT_DIR, *dir_parts) if dir_parts else OUTPUT_DIR
    os.makedirs(dir_path, exist_ok=True)

    return os.path.join(dir_path, f"{file_stem}.md")


def save_article(url: str, title: str, body_md: str):
    filepath = make_path_from_url(url, title)
    logging.info(f"Saving article: {filepath}")
    with open(filepath, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{body_md}")


def crawl():
    to_visit = [BASE_URL]
    visited = set()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent="KaitenDevelopersScraper/1.0")

        while to_visit:
            url = to_visit.pop(0)
            url = url.split("#", 1)[0]

            if url in visited:
                continue
            visited.add(url)

            if looks_like_binary(url):
                continue

            logging.info(f"GOTO {url}")
            try:
                page.goto(url, wait_until="load", timeout=30000)
                # чуть подождать, чтобы JS дорисовал всё
                page.wait_for_timeout(500)
                html = page.content()
            except PlaywrightTimeoutError as e:
                logging.warning(f"Timeout when loading {url}: {e}")
                continue
            except Exception as e:
                logging.warning(f"Failed to load {url}: {e}")
                continue

            # вытаскиваем основной текст
            try:
                title, body_md = extract_article_text(html)
                if body_md.strip():
                    save_article(url, title, body_md)
                else:
                    logging.info(f"Skip {url}: empty content after extraction")
            except Exception as e:
                logging.warning(f"Failed to parse article {url}: {e}")

            # собираем ссылки (уже из "живого" DOM после JS)
            try:
                soup = BeautifulSoup(html, "html.parser")
            except Exception as e:
                logging.warning(f"Failed to parse HTML for links {url}: {e}")
                continue

            for a in soup.find_all("a", href=True):
                href = a["href"].strip()
                abs_url = urljoin(BASE_URL, href)

                if not is_same_domain(abs_url):
                    continue
                if looks_like_binary(abs_url):
                    continue
                if abs_url not in visited and abs_url not in to_visit:
                    to_visit.append(abs_url)

            time.sleep(DELAY_BETWEEN_PAGES)

        browser.close()

    logging.info(f"Done. Visited {len(visited)} pages.")


if __name__ == "__main__":
    crawl()
