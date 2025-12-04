#!/usr/bin/env python3
"""
Скрипт экспорта карточек из пространства Kaiten в отдельные Markdown файлы
Каждая карточка сохраняется как отдельный .md файл с полной информацией
"""

import requests
import time
import os
import re
from typing import Dict, List, Optional
from datetime import datetime
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class KaitenExporter:
    """Класс для экспорта карточек из Kaiten в Markdown"""

    def __init__(self, domain: str, token: str):
        self.domain = domain
        self.token = token
        self.base_url = f"https://{domain}.kaiten.ru/api/v1"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.request_times = []

    def _rate_limit(self):
        """Контроль rate limit: максимум 5 запросов в секунду"""
        now = time.time()
        self.request_times = [t for t in self.request_times if now - t < 1.0]

        if len(self.request_times) >= 5:
            sleep_time = 1.0 - (now - self.request_times[0]) + 0.05
            if sleep_time > 0:
                time.sleep(sleep_time)
                now = time.time()
                self.request_times = [t for t in self.request_times if now - t < 1.0]

        self.request_times.append(now)

    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        """Базовый метод для выполнения запросов"""
        self._rate_limit()

        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(method, url, headers=self.headers, **kwargs)

            if response.status_code == 429:
                logger.warning("Rate limit exceeded, waiting...")
                time.sleep(2)
                return self._request(method, endpoint, **kwargs)

            response.raise_for_status()

            if not response.text:
                return {}

            return response.json()

        except requests.exceptions.RequestException as e:
            logger.error(f"Request failed: {e}")
            return None

    def get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """GET запрос"""
        return self._request("GET", endpoint, params=params)

    def get_paginated(self, endpoint: str, params: Optional[Dict] = None, limit: int = 100) -> List[Dict]:
        """Получение всех данных с пагинацией"""
        all_data = []
        offset = 0
        params = params or {}

        while True:
            params['limit'] = limit
            params['offset'] = offset

            response = self.get(endpoint, params)

            if response is None:
                break

            if isinstance(response, list):
                data = response
            elif isinstance(response, dict) and 'data' in response:
                data = response['data']
            else:
                data = [response] if response else []

            if not data:
                break

            all_data.extend(data)

            if len(data) < limit:
                break

            offset += limit

        return all_data

    def sanitize_filename(self, filename: str) -> str:
        """Очистка имени файла от недопустимых символов"""
        # Удаляем/заменяем недопустимые символы
        filename = re.sub(r'[<>:"/\\|?*]', '-', filename)
        # Ограничиваем длину
        if len(filename) > 200:
            filename = filename[:200]
        return filename.strip()

    def format_card_to_markdown(self, card: Dict, comments: List[Dict], checklists: List[Dict]) -> str:
        """Форматирование карточки в Markdown"""
        lines = []

        # Заголовок
        title = card.get('title', 'Без названия')
        lines.append(f"# {title}")
        lines.append("")

        # Метаданные
        lines.append("## 📋 Информация")
        lines.append("")
        lines.append(f"- **ID карточки:** {card.get('id')}")
        lines.append(f"- **Создана:** {self._format_date(card.get('created'))}")
        lines.append(f"- **Обновлена:** {self._format_date(card.get('updated'))}")

        # Статус
        state_map = {1: 'В очереди', 2: 'В работе', 3: 'Выполнено'}
        state = state_map.get(card.get('state'), 'Неизвестно')
        lines.append(f"- **Статус:** {state}")

        # Срок
        if card.get('due_date'):
            due_date = self._format_date(card.get('due_date'))
            asap = "🔥 " if card.get('asap') else ""
            lines.append(f"- **Срок:** {asap}{due_date}")

        # Ответственный
        if card.get('owner'):
            owner = card['owner'].get('full_name', 'Неизвестно')
            lines.append(f"- **Ответственный:** {owner}")

        # Размер
        if card.get('size_text'):
            lines.append(f"- **Размер:** {card['size_text']}")

        # Тип карточки
        if card.get('type'):
            card_type = card['type'].get('title', 'Неизвестно')
            lines.append(f"- **Тип:** {card_type}")

        lines.append("")

        # Описание
        description = card.get('description') or ''
        description = description.strip() if isinstance(description, str) else ''
        if description:
            lines.append("## 📝 Описание")
            lines.append("")
            lines.append(description)
            lines.append("")

        # Пользовательские поля
        properties = card.get('properties', {})
        if properties:
            lines.append("## 🔖 Дополнительные поля")
            lines.append("")
            for key, value in properties.items():
                if value:
                    field_name = key.replace('id_', 'Поле ')
                    lines.append(f"- **{field_name}:** {value}")
            lines.append("")

        # Метки
        tags = card.get('tags', [])
        if tags:
            lines.append("## 🏷️ Метки")
            lines.append("")
            tag_names = [f"`{tag.get('name')}`" for tag in tags]
            lines.append(" ".join(tag_names))
            lines.append("")

        # Чек-листы
        if checklists:
            lines.append("## ☑️ Чек-листы")
            lines.append("")
            for checklist in checklists:
                checklist_name = checklist.get('name', 'Чек-лист')
                lines.append(f"### {checklist_name}")
                lines.append("")

                items = checklist.get('items', [])
                for item in items:
                    checked = "x" if item.get('checked') else " "
                    text = item.get('text', '')
                    lines.append(f"- [{checked}] {text}")

                lines.append("")

        # Комментарии
        if comments:
            lines.append("## 💬 Комментарии")
            lines.append("")
            for comment in comments:
                author = comment.get('author', {}).get('full_name', 'Неизвестно')
                created = self._format_date(comment.get('created'))
                text = comment.get('text', '')

                lines.append(f"### {author} • {created}")
                lines.append("")
                lines.append(text)
                lines.append("")

        # Ссылки
        external_links = card.get('external_links', [])
        if external_links:
            lines.append("## 🔗 Внешние ссылки")
            lines.append("")
            for link in external_links:
                url = link.get('url', '')
                title = link.get('title', url)
                lines.append(f"- [{title}]({url})")
            lines.append("")

        # Связанные карточки
        if card.get('children_count', 0) > 0:
            lines.append("## 🔗 Связанные карточки")
            lines.append("")
            lines.append(f"- Дочерних карточек: {card.get('children_count')}")
            lines.append("")

        # Футер с метаданными
        lines.append("---")
        lines.append("")
        lines.append(f"*Экспортировано из Kaiten {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}*")

        return "\n".join(lines)

    def _format_date(self, date_str: Optional[str]) -> str:
        """Форматирование даты для читаемости"""
        if not date_str:
            return "Не указано"

        try:
            # Пробуем распарсить ISO формат
            dt = datetime.fromisoformat(date_str.replace('Z', '+00:00'))
            return dt.strftime('%d.%m.%Y %H:%M')
        except:
            return date_str

    def export_space_cards(self, space_id: int, output_dir: str = "exported_cards"):
        """Экспорт всех карточек из пространства"""
        logger.info(f"Начало экспорта карточек из пространства {space_id}")

        # Создаём директорию для экспорта
        os.makedirs(output_dir, exist_ok=True)

        # Получаем информацию о пространстве
        space = self.get(f"/spaces/{space_id}")
        if not space:
            logger.error(f"Не удалось получить информацию о пространстве {space_id}")
            return

        space_title = space.get('title', f'Space_{space_id}')
        logger.info(f"Пространство: {space_title}")

        # Создаём поддиректорию для этого пространства
        space_dir = os.path.join(output_dir, self.sanitize_filename(space_title))
        os.makedirs(space_dir, exist_ok=True)

        # Получаем все карточки из пространства
        logger.info("Получение списка карточек...")
        cards = self.get_paginated("/cards", {
            'space_id': space_id,
            'additional_card_fields': 'description',
            'condition': 1  # только активные
        })

        logger.info(f"Найдено карточек: {len(cards)}")

        # Экспортируем каждую карточку
        for i, card in enumerate(cards, 1):
            card_id = card.get('id')
            card_title = card.get('title', f'Card_{card_id}')

            logger.info(f"[{i}/{len(cards)}] Экспорт: {card_title}")

            # Получаем комментарии
            comments = self.get_paginated(f"/cards/{card_id}/comments")

            # Чек-листы уже есть в объекте карточки
            checklists = card.get('checklists', [])

            # Форматируем в Markdown
            markdown = self.format_card_to_markdown(card, comments, checklists)

            # Формируем имя файла
            filename = f"{card_id}_{self.sanitize_filename(card_title)}.md"
            filepath = os.path.join(space_dir, filename)

            # Сохраняем
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(markdown)

            logger.info(f"  ✓ Сохранено: {filename}")

        logger.info("=" * 70)
        logger.info(f"ЭКСПОРТ ЗАВЕРШЁН")
        logger.info(f"Карточек экспортировано: {len(cards)}")
        logger.info(f"Директория: {space_dir}")
        logger.info("=" * 70)

        # Создаём индексный файл
        self._create_index_file(space_dir, space_title, cards)

    def _create_index_file(self, directory: str, space_title: str, cards: List[Dict]):
        """Создание индексного файла со списком всех карточек"""
        index_path = os.path.join(directory, "INDEX.md")

        lines = [
            f"# Экспорт карточек: {space_title}",
            "",
            f"Дата экспорта: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
            "",
            f"Всего карточек: {len(cards)}",
            "",
            "---",
            "",
            "## Список карточек",
            ""
        ]

        # Группируем по статусам
        state_map = {1: '🟡 В очереди', 2: '🔵 В работе', 3: '🟢 Выполнено'}

        for state_id, state_name in state_map.items():
            state_cards = [c for c in cards if c.get('state') == state_id]
            if state_cards:
                lines.append(f"### {state_name} ({len(state_cards)})")
                lines.append("")

                for card in sorted(state_cards, key=lambda x: x.get('id', 0)):
                    card_id = card.get('id')
                    card_title = card.get('title', 'Без названия')
                    filename = f"{card_id}_{self.sanitize_filename(card_title)}.md"

                    # Дополнительная информация
                    info_parts = []
                    if card.get('asap'):
                        info_parts.append("🔥 Срочно")
                    if card.get('due_date'):
                        info_parts.append(f"📅 {self._format_date(card.get('due_date'))}")
                    if card.get('owner'):
                        info_parts.append(f"👤 {card['owner'].get('full_name')}")

                    info = " • ".join(info_parts)
                    info_str = f" — {info}" if info else ""

                    lines.append(f"- [{card_title}](./{filename}){info_str}")

                lines.append("")

        with open(index_path, 'w', encoding='utf-8') as f:
            f.write("\n".join(lines))

        logger.info(f"Индексный файл создан: {index_path}")


def main():
    print("=" * 70)
    print("ЭКСПОРТ КАРТОЧЕК ИЗ KAITEN В MARKDOWN")
    print("=" * 70)
    print()

    # Ввод данных
    domain = input("Домен Kaiten (например, 'company'): ").strip()
    token = input("API Token: ").strip()
    print()

    # Создаём экспортёр
    exporter = KaitenExporter(domain, token)

    # Получаем список пространств
    print("Получение списка пространств...")
    spaces = exporter.get_paginated("/spaces")

    if not spaces:
        print("❌ Не удалось получить список пространств")
        return

    print()
    print("Доступные пространства:")
    print()

    for i, space in enumerate(spaces, 1):
        space_id = space.get('id')
        space_title = space.get('title', 'Без названия')
        archived = " [АРХИВ]" if space.get('archived') else ""
        print(f"  {i}. {space_title} (ID: {space_id}){archived}")

    print()
    choice = input("Выберите номер пространства (или введите ID): ").strip()

    # Определяем ID пространства
    try:
        if choice.isdigit() and int(choice) <= len(spaces):
            space_id = spaces[int(choice) - 1]['id']
        else:
            space_id = int(choice)
    except:
        print("❌ Неверный выбор")
        return

    # Опционально: директория для экспорта
    print()
    output_dir = input("Директория для экспорта (Enter = 'exported_cards'): ").strip()
    if not output_dir:
        output_dir = "exported_cards"

    print()
    print("Начинаю экспорт...")
    print()

    # Запускаем экспорт
    exporter.export_space_cards(space_id, output_dir)

    print()
    print("✅ Готово!")


if __name__ == "__main__":
    main()
