#!/usr/bin/env python3
"""
Скрипт миграции данных между аккаунтами Kaiten через API
Переносит: пространства, доски, карточки, комментарии, чек-листы, теги, пользовательские поля

Rate limit: 5 requests/second
"""

import requests
import time
import json
from typing import Dict, List, Optional, Any
from collections import defaultdict
import logging
from datetime import datetime

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(f'kaiten_migration_{datetime.now().strftime("%Y%m%d_%H%M%S")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


class KaitenAPI:
    """Класс для работы с Kaiten API"""

    def __init__(self, domain: str, token: str):
        self.domain = domain
        self.token = token
        self.base_url = f"https://{domain}.kaiten.ru/api/v1"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.request_count = 0
        self.request_times = []

    def _rate_limit(self):
        """Контроль rate limit: максимум 5 запросов в секунду"""
        now = time.time()
        # Убираем запросы старше 1 секунды
        self.request_times = [t for t in self.request_times if now - t < 1.0]

        if len(self.request_times) >= 5:
            # Ждём до момента, когда самый старый запрос выйдет из окна
            sleep_time = 1.0 - (now - self.request_times[0]) + 0.05  # +50ms для надёжности
            if sleep_time > 0:
                logger.debug(f"Rate limit: sleep {sleep_time:.2f}s")
                time.sleep(sleep_time)
                now = time.time()
                self.request_times = [t for t in self.request_times if now - t < 1.0]

        self.request_times.append(now)
        self.request_count += 1

    def _request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        """Базовый метод для выполнения запросов с обработкой ошибок"""
        self._rate_limit()

        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(method, url, headers=self.headers, **kwargs)

            # Логируем rate limit headers
            if 'X-RateLimit-Remaining' in response.headers:
                remaining = response.headers['X-RateLimit-Remaining']
                logger.debug(f"Rate limit remaining: {remaining}")

            if response.status_code == 429:
                logger.warning("Rate limit exceeded, waiting 2 seconds...")
                time.sleep(2)
                return self._request(method, endpoint, **kwargs)

            response.raise_for_status()

            # Некоторые эндпоинты возвращают пустой ответ
            if not response.text:
                return {}

            return response.json()

        except requests.exceptions.HTTPError as e:
            logger.error(f"{method} {endpoint} failed: {e}")
            logger.error(f"Response: {response.text if response else 'No response'}")
            return None
        except Exception as e:
            logger.error(f"Request failed: {e}")
            return None

    def get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        """GET запрос"""
        return self._request("GET", endpoint, params=params)

    def post(self, endpoint: str, data: Dict) -> Optional[Dict]:
        """POST запрос"""
        return self._request("POST", endpoint, json=data)

    def patch(self, endpoint: str, data: Dict) -> Optional[Dict]:
        """PATCH запрос"""
        return self._request("PATCH", endpoint, json=data)

    def delete(self, endpoint: str) -> Optional[Dict]:
        """DELETE запрос"""
        return self._request("DELETE", endpoint)

    def get_paginated(self, endpoint: str, params: Optional[Dict] = None, limit: int = 100) -> List[Dict]:
        """Получение всех данных с пагинацией"""
        all_data = []
        offset = 0
        params = params or {}

        while True:
            params['limit'] = limit
            params['offset'] = offset

            logger.debug(f"Fetching {endpoint} with offset={offset}")
            response = self.get(endpoint, params)

            if response is None:
                break

            # API может вернуть массив или объект с полем 'data'
            if isinstance(response, list):
                data = response
            elif isinstance(response, dict) and 'data' in response:
                data = response['data']
            else:
                data = [response] if response else []

            if not data:
                break

            all_data.extend(data)

            # Если получили меньше чем limit, значит это последняя страница
            if len(data) < limit:
                break

            offset += limit

        logger.info(f"Fetched {len(all_data)} items from {endpoint}")
        return all_data


class KaitenMigration:
    """Класс для миграции данных между аккаунтами Kaiten"""

    def __init__(self, source_domain: str, source_token: str,
                 target_domain: str, target_token: str):
        self.source = KaitenAPI(source_domain, source_token)
        self.target = KaitenAPI(target_domain, target_token)

        # Маппинг ID между источником и целью
        self.id_map: Dict[str, Dict[int, int]] = defaultdict(dict)

        # Статистика
        self.stats = {
            'spaces': {'total': 0, 'migrated': 0, 'failed': 0},
            'boards': {'total': 0, 'migrated': 0, 'failed': 0},
            'cards': {'total': 0, 'migrated': 0, 'failed': 0},
            'comments': {'total': 0, 'migrated': 0, 'failed': 0},
            'checklists': {'total': 0, 'migrated': 0, 'failed': 0},
            'tags': {'total': 0, 'migrated': 0, 'failed': 0},
            'custom_properties': {'total': 0, 'migrated': 0, 'failed': 0},
        }

    def migrate_all(self):
        """Полная миграция всех данных"""
        logger.info("=" * 80)
        logger.info("НАЧАЛО МИГРАЦИИ")
        logger.info("=" * 80)

        start_time = time.time()

        try:
            # 1. Пользовательские поля (нужны до создания карточек)
            self.migrate_custom_properties()

            # 2. Теги
            self.migrate_tags()

            # 3. Пространства и доски
            self.migrate_spaces_and_boards()

            # 4. Карточки
            self.migrate_cards()

            # 5. Комментарии к карточкам
            self.migrate_comments()

            # 6. Чек-листы
            self.migrate_checklists()

            # 7. Связи между карточками (родительские/дочерние)
            self.migrate_card_relations()

        except Exception as e:
            logger.error(f"Migration failed with error: {e}", exc_info=True)

        elapsed = time.time() - start_time

        logger.info("=" * 80)
        logger.info("МИГРАЦИЯ ЗАВЕРШЕНА")
        logger.info(f"Время выполнения: {elapsed:.2f} секунд")
        logger.info("=" * 80)

        self.print_stats()

    def migrate_custom_properties(self):
        """Миграция пользовательских полей"""
        logger.info("\n--- Миграция пользовательских полей ---")

        properties = self.source.get_paginated("/custom-properties")
        self.stats['custom_properties']['total'] = len(properties)

        for prop in properties:
            prop_id = prop['id']
            prop_name = prop.get('name', f'Property {prop_id}')

            # Подготовка данных для создания
            new_prop = {
                'name': prop_name,
                'type': prop.get('type'),
                'settings': prop.get('settings', {}),
            }

            # Убираем системные поля
            for key in ['id', 'created', 'updated', 'company_id']:
                new_prop.pop(key, None)

            logger.info(f"Создание пользовательского поля: {prop_name}")
            result = self.target.post("/custom-properties", new_prop)

            if result and 'id' in result:
                self.id_map['properties'][prop_id] = result['id']
                self.stats['custom_properties']['migrated'] += 1
                logger.info(f"✓ Поле создано: {prop_name} (ID: {prop_id} -> {result['id']})")
            else:
                self.stats['custom_properties']['failed'] += 1
                logger.error(f"✗ Не удалось создать поле: {prop_name}")

    def migrate_tags(self):
        """Миграция меток"""
        logger.info("\n--- Миграция меток ---")

        tags = self.source.get_paginated("/tags")
        self.stats['tags']['total'] = len(tags)

        for tag in tags:
            tag_id = tag['id']
            tag_name = tag.get('name', f'Tag {tag_id}')

            new_tag = {
                'name': tag_name,
                'color': tag.get('color'),
            }

            logger.info(f"Создание метки: {tag_name}")
            result = self.target.post("/tags", new_tag)

            if result and 'id' in result:
                self.id_map['tags'][tag_id] = result['id']
                self.stats['tags']['migrated'] += 1
                logger.info(f"✓ Метка создана: {tag_name}")
            else:
                self.stats['tags']['failed'] += 1
                logger.error(f"✗ Не удалось создать метку: {tag_name}")

    def migrate_spaces_and_boards(self):
        """Миграция пространств и досок"""
        logger.info("\n--- Миграция пространств и досок ---")

        spaces = self.source.get_paginated("/spaces")
        self.stats['spaces']['total'] = len(spaces)

        for space in spaces:
            if space.get('archived'):
                logger.info(f"Пропуск архивного пространства: {space.get('title')}")
                continue

            # Создание пространства
            space_id = space['id']
            space_title = space.get('title', f'Space {space_id}')

            new_space = {
                'title': space_title,
                'access': space.get('access', 'private'),
            }

            logger.info(f"Создание пространства: {space_title}")
            result = self.target.post("/spaces", new_space)

            if not result or 'id' not in result:
                self.stats['spaces']['failed'] += 1
                logger.error(f"✗ Не удалось создать пространство: {space_title}")
                continue

            new_space_id = result['id']
            self.id_map['spaces'][space_id] = new_space_id
            self.stats['spaces']['migrated'] += 1
            logger.info(f"✓ Пространство создано: {space_title} (ID: {space_id} -> {new_space_id})")

            # Миграция досок в этом пространстве
            self.migrate_boards_in_space(space_id, new_space_id)

    def migrate_boards_in_space(self, old_space_id: int, new_space_id: int):
        """Миграция досок внутри пространства"""
        boards = self.source.get_paginated(f"/spaces/{old_space_id}/boards")
        self.stats['boards']['total'] += len(boards)

        for board in boards:
            board_id = board['id']
            board_title = board.get('title', f'Board {board_id}')

            new_board = {
                'title': board_title,
                'description': board.get('description', ''),
                'space_id': new_space_id,
            }

            logger.info(f"  Создание доски: {board_title}")
            result = self.target.post("/boards", new_board)

            if result and 'id' in result:
                self.id_map['boards'][board_id] = result['id']
                self.stats['boards']['migrated'] += 1
                logger.info(f"  ✓ Доска создана: {board_title} (ID: {board_id} -> {result['id']})")

                # Получаем детали доски для миграции колонок и дорожек
                board_details = self.source.get(f"/boards/{board_id}")
                if board_details:
                    self.migrate_columns_and_lanes(board_id, result['id'], board_details)
            else:
                self.stats['boards']['failed'] += 1
                logger.error(f"  ✗ Не удалось создать доску: {board_title}")

    def migrate_columns_and_lanes(self, old_board_id: int, new_board_id: int, board_data: Dict):
        """Миграция колонок и дорожек"""
        # Колонки
        columns = board_data.get('columns', [])
        for col in columns:
            col_id = col['id']
            new_col = {
                'board_id': new_board_id,
                'title': col.get('title', ''),
                'type': col.get('type', 1),
                'sort_order': col.get('sort_order', 0),
            }

            result = self.target.post("/columns", new_col)
            if result and 'id' in result:
                self.id_map['columns'][col_id] = result['id']
                logger.debug(f"    Колонка создана: {col.get('title')}")

        # Дорожки
        lanes = board_data.get('lanes', [])
        for lane in lanes:
            lane_id = lane['id']
            new_lane = {
                'board_id': new_board_id,
                'title': lane.get('title', ''),
                'sort_order': lane.get('sort_order', 0),
            }

            result = self.target.post("/lanes", new_lane)
            if result and 'id' in result:
                self.id_map['lanes'][lane_id] = result['id']
                logger.debug(f"    Дорожка создана: {lane.get('title')}")

    def migrate_cards(self):
        """Миграция карточек"""
        logger.info("\n--- Миграция карточек ---")

        # Получаем все карточки
        cards = self.source.get_paginated("/cards", {
            'additional_card_fields': 'description',
            'condition': 1  # только активные карточки
        })

        self.stats['cards']['total'] = len(cards)
        logger.info(f"Найдено карточек: {len(cards)}")

        for card in cards:
            self.migrate_single_card(card)

    def migrate_single_card(self, card: Dict):
        """Миграция одной карточки"""
        card_id = card['id']
        card_title = card.get('title', f'Card {card_id}')

        # Маппинг board_id, column_id, lane_id
        old_board_id = card.get('board_id')
        new_board_id = self.id_map['boards'].get(old_board_id)

        if not new_board_id:
            logger.warning(f"  Пропуск карточки {card_title}: доска не найдена")
            self.stats['cards']['failed'] += 1
            return

        old_column_id = card.get('column_id')
        new_column_id = self.id_map['columns'].get(old_column_id)

        old_lane_id = card.get('lane_id')
        new_lane_id = self.id_map['lanes'].get(old_lane_id) if old_lane_id else None

        if not new_column_id:
            logger.warning(f"  Пропуск карточки {card_title}: колонка не найдена")
            self.stats['cards']['failed'] += 1
            return

        new_card = {
            'title': card_title,
            'description': card.get('description'),
            'board_id': new_board_id,
            'column_id': new_column_id,
            'lane_id': new_lane_id,
            'asap': card.get('asap', False),
            'due_date': card.get('due_date'),
            'size_text': card.get('size_text'),
        }

        # Пользовательские поля
        properties = card.get('properties', {})
        if properties:
            new_properties = {}
            for key, value in properties.items():
                # Формат: id_123 -> нужно найти новый ID
                if key.startswith('id_'):
                    old_prop_id = int(key.split('_')[1])
                    new_prop_id = self.id_map['properties'].get(old_prop_id)
                    if new_prop_id:
                        new_properties[f'id_{new_prop_id}'] = value

            if new_properties:
                new_card['properties'] = new_properties

        logger.info(f"  Создание карточки: {card_title}")
        result = self.target.post("/cards", new_card)

        if result and 'id' in result:
            self.id_map['cards'][card_id] = result['id']
            self.stats['cards']['migrated'] += 1
            logger.info(f"  ✓ Карточка создана: {card_title} (ID: {card_id} -> {result['id']})")

            # Миграция тегов карточки
            self.migrate_card_tags(card_id, result['id'], card.get('tags', []))
        else:
            self.stats['cards']['failed'] += 1
            logger.error(f"  ✗ Не удалось создать карточку: {card_title}")

    def migrate_card_tags(self, old_card_id: int, new_card_id: int, tags: List[Dict]):
        """Добавление тегов к карточке"""
        for tag in tags:
            old_tag_id = tag.get('id')
            new_tag_id = self.id_map['tags'].get(old_tag_id)

            if new_tag_id:
                self.target.post(f"/cards/{new_card_id}/tags", {'tag_id': new_tag_id})

    def migrate_comments(self):
        """Миграция комментариев"""
        logger.info("\n--- Миграция комментариев ---")

        for old_card_id, new_card_id in self.id_map['cards'].items():
            comments = self.source.get_paginated(f"/cards/{old_card_id}/comments")
            self.stats['comments']['total'] += len(comments)

            for comment in comments:
                new_comment = {
                    'text': comment.get('text', ''),
                }

                result = self.target.post(f"/card-comments/add-comment", {
                    'card_id': new_card_id,
                    **new_comment
                })

                if result:
                    self.stats['comments']['migrated'] += 1
                else:
                    self.stats['comments']['failed'] += 1

        logger.info(f"Комментариев перенесено: {self.stats['comments']['migrated']}/{self.stats['comments']['total']}")

    def migrate_checklists(self):
        """Миграция чек-листов"""
        logger.info("\n--- Миграция чек-листов ---")

        for old_card_id, new_card_id in self.id_map['cards'].items():
            checklists = self.source.get_paginated(f"/cards/{old_card_id}/checklists")
            self.stats['checklists']['total'] += len(checklists)

            for checklist in checklists:
                new_checklist = {
                    'card_id': new_card_id,
                    'name': checklist.get('name', ''),
                }

                result = self.target.post("/card-checklists", new_checklist)

                if result and 'id' in result:
                    new_checklist_id = result['id']
                    self.stats['checklists']['migrated'] += 1

                    # Миграция пунктов чек-листа
                    items = checklist.get('items', [])
                    for item in items:
                        new_item = {
                            'checklist_id': new_checklist_id,
                            'text': item.get('text', ''),
                            'checked': item.get('checked', False),
                        }
                        self.target.post("/card-checklist-items", new_item)
                else:
                    self.stats['checklists']['failed'] += 1

        logger.info(f"Чек-листов перенесено: {self.stats['checklists']['migrated']}/{self.stats['checklists']['total']}")

    def migrate_card_relations(self):
        """Миграция связей между карточками (родительские/дочерние)"""
        logger.info("\n--- Миграция связей карточек ---")

        migrated = 0
        failed = 0

        for old_card_id, new_card_id in self.id_map['cards'].items():
            children = self.source.get_paginated(f"/cards/{old_card_id}/children")

            for child in children:
                old_child_id = child.get('id')
                new_child_id = self.id_map['cards'].get(old_child_id)

                if new_child_id:
                    result = self.target.post(f"/cards/{new_card_id}/children", {
                        'child_id': new_child_id
                    })

                    if result:
                        migrated += 1
                    else:
                        failed += 1

        logger.info(f"Связей перенесено: {migrated} (ошибок: {failed})")

    def print_stats(self):
        """Вывод статистики миграции"""
        logger.info("\n" + "=" * 80)
        logger.info("СТАТИСТИКА МИГРАЦИИ")
        logger.info("=" * 80)

        for entity, counts in self.stats.items():
            total = counts['total']
            migrated = counts['migrated']
            failed = counts['failed']

            if total > 0:
                success_rate = (migrated / total) * 100
                logger.info(f"{entity.upper():.<30} {migrated}/{total} ({success_rate:.1f}%) [Ошибок: {failed}]")

        logger.info("=" * 80)

        # Маппинг ID
        logger.info("\nМАППИНГ ID (для справки):")
        for entity_type, mapping in self.id_map.items():
            if mapping:
                logger.info(f"{entity_type}: {len(mapping)} записей")


def main():
    """Точка входа"""
    print("=" * 80)
    print("МИГРАЦИЯ ДАННЫХ МЕЖДУ АККАУНТАМИ KAITEN")
    print("=" * 80)
    print()

    # Ввод данных источника
    print("ИСХОДНЫЙ АККАУНТ:")
    source_domain = input("  Домен (например, 'company'): ").strip()
    source_token = input("  API Token: ").strip()
    print()

    # Ввод данных цели
    print("ЦЕЛЕВОЙ АККАУНТ:")
    target_domain = input("  Домен (например, 'newcompany'): ").strip()
    target_token = input("  API Token: ").strip()
    print()

    # Подтверждение
    print("ВНИМАНИЕ!")
    print(f"Данные будут скопированы из '{source_domain}' в '{target_domain}'")
    confirm = input("Продолжить? (yes/no): ").strip().lower()

    if confirm != 'yes':
        print("Миграция отменена.")
        return

    print()

    # Запуск миграции
    migration = KaitenMigration(
        source_domain=source_domain,
        source_token=source_token,
        target_domain=target_domain,
        target_token=target_token
    )

    migration.migrate_all()

    print()
    print("Лог файл сохранён: kaiten_migration_*.log")
    print("Готово!")


if __name__ == "__main__":
    main()
