import os
import re
import time
import logging
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from readability import Document
import html2text

BASE_URL = "https://faq-ru.kaiten.site"
OUTPUT_DIR = "out"

# --- настройки ---

DELAY_BETWEEN_REQUESTS = 0.2  # секунды, чтобы не долбить сайт
SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "KaitenFAQExporter/1.0 (+https://kaiten.ru)"
})

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s"
)

# --- вспомогательные функции ---

def is_same_domain(url: str) -> bool:
    """Проверяем, что ссылка внутри faq-ru.kaiten.site."""
    try:
        return urlparse(url).netloc == urlparse(BASE_URL).netloc
    except Exception:
        return False


def looks_like_binary(url: str) -> bool:
    """Отфильтровываем картинки, видео и т.п."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    # расширения, которые пропускаем (добавь свои при необходимости)
    bad_ext = [
        ".png", ".jpg", ".jpeg", ".gif", ".svg",
        ".webp", ".ico", ".mp4", ".mov", ".avi",
        ".pdf", ".zip", ".rar", ".7z"
    ]
    return any(path.endswith(ext) for ext in bad_ext)


def make_slug(text: str) -> str:
    """Человекопонятный слаг из заголовка."""
    text = text.strip()
    # заменяем всё кроме букв/цифр на дефисы
    text = re.sub(r"[^0-9A-Za-zА-Яа-я]+", "-", text)
    text = re.sub(r"-{2,}", "-", text)
    return text.strip("-") or "page"


def fetch(url: str) -> str:
    logging.info(f"GET {url}")
    resp = SESSION.get(url, timeout=15)
    resp.raise_for_status()
    return resp.text


def extract_article_text(html: str) -> tuple[str, str]:
    """
    Используем Readability для выделения основного контента,
    затем html2text для конвертации в markdown/текст.
    Возвращает (title, body_md).
    """
    doc = Document(html)
    title = doc.short_title() or "Без названия"
    article_html = doc.summary(html_partial=True)

    h = html2text.HTML2Text()
    h.ignore_images = True
    h.ignore_emphasis = False
    h.ignore_links = False
    h.body_width = 0  # не ломать строки по ширине

    body_md = h.handle(article_html)
    return title, body_md


def save_article(title: str, body_md: str):
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    slug = make_slug(title)
    filename = os.path.join(OUTPUT_DIR, f"{slug}.md")
    logging.info(f"Saving article: {filename}")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(f"# {title}\n\n{body_md}")


# --- основной обход ---

def crawl():
    to_visit = [BASE_URL]
    visited = set()

    while to_visit:
        url = to_visit.pop(0)

        # убираем якоря/дубликаты
        url = url.split("#", 1)[0]

        if url in visited:
            continue
        visited.add(url)

        # фильтр на бинарные ресурсы
        if looks_like_binary(url):
            continue

        try:
            html = fetch(url)
        except Exception as e:
            logging.warning(f"Failed to fetch {url}: {e}")
            continue

        # если это не главная, считаем, что это «страница с контентом» и вытаскиваем текст
        if url != BASE_URL:
            try:
                title, body_md = extract_article_text(html)

                # маленький фильтр на «шум»: если текста совсем мало, можно пропустить
                if len(body_md.strip()) > 20:  # порог символов, подстрой под себя
                    save_article(title, body_md)
                else:
                    logging.info(f"Skip {url}: too short content")
            except Exception as e:
                logging.warning(f"Failed to parse article {url}: {e}")

        # Парсим ссылки для дальнейшего обхода
        try:
            soup = BeautifulSoup(html, "html.parser")
        except Exception as e:
            logging.warning(f"Failed to parse HTML for links {url}: {e}")
            continue

        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            # нормализуем относительные ссылки
            abs_url = urljoin(BASE_URL, href)

            if not is_same_domain(abs_url):
                continue
            if looks_like_binary(abs_url):
                continue
            if abs_url not in visited and abs_url not in to_visit:
                to_visit.append(abs_url)

        time.sleep(DELAY_BETWEEN_REQUESTS)

    logging.info(f"Done. Visited {len(visited)} pages.")


if __name__ == "__main__":
    crawl()
