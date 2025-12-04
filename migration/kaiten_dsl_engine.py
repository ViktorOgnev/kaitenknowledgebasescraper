#!/usr/bin/env python3
"""
Kaiten DSL Engine - декларативная настройка Kaiten через YAML
Позволяет описать всю конфигурацию Kaiten в YAML файле и автоматически применить через API

Пример использования:
    python3 kaiten_dsl_engine.py apply config.yaml
    python3 kaiten_dsl_engine.py validate config.yaml
    python3 kaiten_dsl_engine.py dry-run config.yaml
"""

import yaml
import sys
import os
import re
import time
import logging
from typing import Dict, List, Any, Optional
from pathlib import Path
import requests
from dataclasses import dataclass, field

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@dataclass
class ExecutionContext:
    """Контекст выполнения DSL"""
    dry_run: bool = False
    created_ids: Dict[str, Dict[str, int]] = field(default_factory=lambda: {
        'spaces': {},
        'boards': {},
        'columns': {},
        'lanes': {},
        'properties': {},
        'tags': {},
        'card_types': {},
    })
    variables: Dict[str, Any] = field(default_factory=dict)


class KaitenAPI:
    """Обёртка над Kaiten API"""

    def __init__(self, domain: str, token: str, dry_run: bool = False):
        self.domain = domain
        self.token = token
        self.dry_run = dry_run
        self.base_url = f"https://{domain}.kaiten.ru/api/v1"
        self.headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }
        self.request_times = []

    def _rate_limit(self):
        """Rate limiting: 5 запросов/сек"""
        now = time.time()
        self.request_times = [t for t in self.request_times if now - t < 1.0]

        if len(self.request_times) >= 5:
            sleep_time = 1.0 - (now - self.request_times[0]) + 0.05
            if sleep_time > 0:
                time.sleep(sleep_time)
                now = time.time()
                self.request_times = [t for t in self.request_times if now - t < 1.0]

        self.request_times.append(now)

    def request(self, method: str, endpoint: str, **kwargs) -> Optional[Dict]:
        """Выполнение API запроса"""
        if self.dry_run:
            logger.info(f"[DRY-RUN] {method} {endpoint}")
            # В dry-run режиме возвращаем mock данные
            return {'id': 999, 'title': 'mock', 'name': 'mock'}

        self._rate_limit()

        url = f"{self.base_url}{endpoint}"
        try:
            response = requests.request(method, url, headers=self.headers, **kwargs)

            if response.status_code == 429:
                logger.warning("Rate limit exceeded, waiting...")
                time.sleep(2)
                return self.request(method, endpoint, **kwargs)

            response.raise_for_status()
            return response.json() if response.text else {}

        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return None

    def get(self, endpoint: str, params: Optional[Dict] = None) -> Optional[Dict]:
        return self.request("GET", endpoint, params=params)

    def post(self, endpoint: str, data: Dict) -> Optional[Dict]:
        return self.request("POST", endpoint, json=data)

    def patch(self, endpoint: str, data: Dict) -> Optional[Dict]:
        return self.request("PATCH", endpoint, json=data)

    def delete(self, endpoint: str) -> Optional[Dict]:
        return self.request("DELETE", endpoint)


class KaitenDSLEngine:
    """Движок для выполнения Kaiten DSL"""

    def __init__(self, api: KaitenAPI, context: ExecutionContext):
        self.api = api
        self.context = context

    def execute(self, config: Dict) -> bool:
        """Выполнение конфигурации"""
        logger.info("=" * 70)
        logger.info("НАЧАЛО ПРИМЕНЕНИЯ КОНФИГУРАЦИИ KAITEN")
        logger.info("=" * 70)

        try:
            # Валидация конфигурации
            if not self.validate_config(config):
                logger.error("Конфигурация невалидна")
                return False

            # Применение в правильном порядке (с учётом зависимостей)
            steps = [
                ('custom_properties', self.apply_custom_properties),
                ('tags', self.apply_tags),
                ('card_types', self.apply_card_types),
                ('spaces', self.apply_spaces),
                # Доски создаются внутри пространств
                ('automations', self.apply_automations),
                ('cards', self.apply_cards),
            ]

            for step_name, step_func in steps:
                if step_name in config:
                    logger.info(f"\n--- Применение: {step_name} ---")
                    step_func(config[step_name])

            logger.info("\n" + "=" * 70)
            logger.info("КОНФИГУРАЦИЯ УСПЕШНО ПРИМЕНЕНА")
            logger.info("=" * 70)
            return True

        except Exception as e:
            logger.error(f"Ошибка применения конфигурации: {e}", exc_info=True)
            return False

    def validate_config(self, config: Dict) -> bool:
        """Валидация конфигурации"""
        logger.info("Валидация конфигурации...")

        required_fields = ['version', 'kaiten']
        for field in required_fields:
            if field not in config:
                logger.error(f"Отсутствует обязательное поле: {field}")
                return False

        # Проверка версии
        if config['version'] not in ['1.0', 1.0]:
            logger.error(f"Неподдерживаемая версия DSL: {config['version']}")
            return False

        logger.info("✓ Конфигурация валидна")
        return True

    def resolve_variables(self, value: Any) -> Any:
        """Подстановка переменных вида ${VAR} и ${env:ENV_VAR}"""
        if not isinstance(value, str):
            return value

        # ${env:VAR_NAME} - переменная окружения
        env_pattern = r'\$\{env:([^}]+)\}'
        for match in re.finditer(env_pattern, value):
            var_name = match.group(1)
            env_value = os.environ.get(var_name, '')
            if not env_value:
                logger.warning(f"Переменная окружения {var_name} не установлена")
            value = value.replace(match.group(0), env_value)

        # ${VAR_NAME} - переменная из контекста
        ctx_pattern = r'\$\{([^}:]+)\}'
        for match in re.finditer(ctx_pattern, value):
            var_name = match.group(1)
            ctx_value = self.context.variables.get(var_name, '')
            value = value.replace(match.group(0), str(ctx_value))

        return value

    def apply_custom_properties(self, properties: List[Dict]):
        """Применение пользовательских полей"""
        for prop in properties:
            name = self.resolve_variables(prop['name'])
            prop_type = prop.get('type', 'string')

            logger.info(f"Создание поля: {name} (тип: {prop_type})")

            data = {
                'name': name,
                'type': self._map_property_type(prop_type),
            }

            # Дополнительные настройки
            if 'settings' in prop:
                data['settings'] = prop['settings']

            if 'catalog_fields' in prop:
                # Для типа "справочник"
                data['catalog_fields'] = prop['catalog_fields']

            result = self.api.post("/custom-properties", data)
            if result and 'id' in result:
                self.context.created_ids['properties'][name] = result['id']
                logger.info(f"  ✓ Поле создано: {name} (ID: {result['id']})")
            else:
                logger.error(f"  ✗ Не удалось создать поле: {name}")

    def apply_tags(self, tags: List[Dict]):
        """Применение меток"""
        for tag in tags:
            name = self.resolve_variables(tag['name'])
            color = tag.get('color', '#808080')

            logger.info(f"Создание метки: {name}")

            data = {
                'name': name,
                'color': color,
            }

            result = self.api.post("/tags", data)
            if result and 'id' in result:
                self.context.created_ids['tags'][name] = result['id']
                logger.info(f"  ✓ Метка создана: {name}")
            else:
                logger.error(f"  ✗ Не удалось создать метку: {name}")

    def apply_card_types(self, card_types: List[Dict]):
        """Применение типов карточек"""
        for card_type in card_types:
            name = self.resolve_variables(card_type['name'])
            color = card_type.get('color', '#808080')

            logger.info(f"Создание типа карточки: {name}")

            data = {
                'title': name,
                'color': color,
            }

            result = self.api.post("/card-types", data)
            if result and 'id' in result:
                self.context.created_ids['card_types'][name] = result['id']
                logger.info(f"  ✓ Тип создан: {name}")
            else:
                logger.error(f"  ✗ Не удалось создать тип: {name}")

    def apply_spaces(self, spaces: List[Dict]):
        """Применение пространств"""
        for space in spaces:
            space_name = self.resolve_variables(space['name'])
            access = space.get('access', 'private')

            logger.info(f"Создание пространства: {space_name}")

            data = {
                'title': space_name,
                'access': access,
            }

            result = self.api.post("/spaces", data)
            if result and 'id' in result:
                space_id = result['id']
                self.context.created_ids['spaces'][space_name] = space_id
                logger.info(f"  ✓ Пространство создано: {space_name} (ID: {space_id})")

                # Создание досок в пространстве
                if 'boards' in space:
                    self.apply_boards(space['boards'], space_id, space_name)
            else:
                logger.error(f"  ✗ Не удалось создать пространство: {space_name}")

    def apply_boards(self, boards: List[Dict], space_id: int, space_name: str):
        """Применение досок"""
        for board in boards:
            board_name = self.resolve_variables(board['name'])
            description = self.resolve_variables(board.get('description', ''))

            logger.info(f"  Создание доски: {board_name}")

            data = {
                'title': board_name,
                'description': description,
                'space_id': space_id,
            }

            result = self.api.post("/boards", data)
            if result and 'id' in result:
                board_id = result['id']
                board_key = f"{space_name}.{board_name}"
                self.context.created_ids['boards'][board_key] = board_id
                logger.info(f"    ✓ Доска создана: {board_name} (ID: {board_id})")

                # Создание колонок
                if 'columns' in board:
                    self.apply_columns(board['columns'], board_id, board_key)

                # Создание дорожек
                if 'lanes' in board:
                    self.apply_lanes(board['lanes'], board_id, board_key)
            else:
                logger.error(f"    ✗ Не удалось создать доску: {board_name}")

    def apply_columns(self, columns: List[Dict], board_id: int, board_key: str):
        """Применение колонок"""
        for i, column in enumerate(columns):
            col_name = self.resolve_variables(column['name'])
            col_type = self._map_column_type(column.get('type', 'queue'))

            logger.info(f"      Создание колонки: {col_name}")

            data = {
                'board_id': board_id,
                'title': col_name,
                'type': col_type,
                'sort_order': i,
            }

            if 'wip_limit' in column:
                data['wip_limit'] = column['wip_limit']

            result = self.api.post("/columns", data)
            if result and 'id' in result:
                col_key = f"{board_key}.{col_name}"
                self.context.created_ids['columns'][col_key] = result['id']
                logger.info(f"        ✓ Колонка создана: {col_name}")
            else:
                logger.error(f"        ✗ Не удалось создать колонку: {col_name}")

    def apply_lanes(self, lanes: List[Dict], board_id: int, board_key: str):
        """Применение дорожек"""
        for i, lane in enumerate(lanes):
            lane_name = self.resolve_variables(lane['name'])

            logger.info(f"      Создание дорожки: {lane_name}")

            data = {
                'board_id': board_id,
                'title': lane_name,
                'sort_order': i,
            }

            result = self.api.post("/lanes", data)
            if result and 'id' in result:
                lane_key = f"{board_key}.{lane_name}"
                self.context.created_ids['lanes'][lane_key] = result['id']
                logger.info(f"        ✓ Дорожка создана: {lane_name}")
            else:
                logger.error(f"        ✗ Не удалось создать дорожку: {lane_name}")

    def apply_automations(self, automations: List[Dict]):
        """Применение автоматизаций"""
        for auto in automations:
            name = self.resolve_variables(auto['name'])
            space_name = self.resolve_variables(auto['space'])

            space_id = self.context.created_ids['spaces'].get(space_name)
            if not space_id:
                logger.warning(f"Пространство {space_name} не найдено, пропуск автоматизации {name}")
                continue

            logger.info(f"Создание автоматизации: {name}")

            # Формирование данных автоматизации
            data = {
                'space_id': space_id,
                'title': name,
                'trigger': self._build_trigger(auto),
                'actions': self._build_actions(auto.get('actions', [])),
            }

            if 'conditions' in auto:
                data['conditions'] = self._build_conditions(auto['conditions'])

            result = self.api.post("/automations", data)
            if result:
                logger.info(f"  ✓ Автоматизация создана: {name}")
            else:
                logger.error(f"  ✗ Не удалось создать автоматизацию: {name}")

    def apply_cards(self, cards: List[Dict]):
        """Применение карточек"""
        for card in cards:
            title = self.resolve_variables(card['title'])
            board_ref = self.resolve_variables(card['board'])
            column_ref = self.resolve_variables(card['column'])

            board_id = self.context.created_ids['boards'].get(board_ref)
            column_id = self.context.created_ids['columns'].get(f"{board_ref}.{column_ref}")

            if not board_id or not column_id:
                logger.warning(f"Доска или колонка не найдены для карточки {title}")
                continue

            logger.info(f"Создание карточки: {title}")

            data = {
                'title': title,
                'board_id': board_id,
                'column_id': column_id,
            }

            if 'description' in card:
                data['description'] = self.resolve_variables(card['description'])

            if 'properties' in card:
                properties = {}
                for key, value in card['properties'].items():
                    prop_id = self.context.created_ids['properties'].get(key)
                    if prop_id:
                        properties[f'id_{prop_id}'] = self.resolve_variables(value)
                data['properties'] = properties

            result = self.api.post("/cards", data)
            if result:
                logger.info(f"  ✓ Карточка создана: {title}")
            else:
                logger.error(f"  ✗ Не удалось создать карточку: {title}")

    def _map_property_type(self, dsl_type: str) -> str:
        """Маппинг типов полей из DSL в API"""
        mapping = {
            'string': 'string',
            'text': 'string',
            'number': 'number',
            'date': 'date',
            'email': 'email',
            'phone': 'phone',
            'select': 'select',
            'multiselect': 'multiselect',
            'catalog': 'catalog',
            'user': 'user',
            'checkbox': 'checkbox',
        }
        return mapping.get(dsl_type, 'string')

    def _map_column_type(self, dsl_type: str) -> int:
        """Маппинг типов колонок из DSL в API"""
        mapping = {
            'queue': 1,
            'in_progress': 2,
            'done': 3,
        }
        return mapping.get(dsl_type, 1)

    def _build_trigger(self, auto: Dict) -> Dict:
        """Построение триггера автоматизации"""
        trigger_type = auto.get('trigger', 'card_moved_to')

        trigger_map = {
            'card_moved_to': 'card_moved_to',
            'card_created': 'card_created',
            'comment_added': 'comment_added',
            'field_changed': 'field_changed',
        }

        return {
            'type': trigger_map.get(trigger_type, trigger_type),
            **auto.get('trigger_params', {})
        }

    def _build_actions(self, actions: List[Dict]) -> List[Dict]:
        """Построение действий автоматизации"""
        result = []
        for action in actions:
            if isinstance(action, dict):
                result.append(action)
            elif isinstance(action, str):
                # Упрощённый формат: "set_owner: event_author"
                parts = action.split(':', 1)
                if len(parts) == 2:
                    result.append({
                        'type': parts[0].strip(),
                        'value': parts[1].strip()
                    })
        return result

    def _build_conditions(self, conditions: Dict) -> Dict:
        """Построение условий автоматизации"""
        return conditions


def load_config(config_path: str) -> Optional[Dict]:
    """Загрузка YAML конфигурации"""
    try:
        with open(config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)
        logger.info(f"Конфигурация загружена из {config_path}")
        return config
    except Exception as e:
        logger.error(f"Ошибка загрузки конфигурации: {e}")
        return None


def main():
    if len(sys.argv) < 3:
        print("Использование:")
        print("  python3 kaiten_dsl_engine.py apply config.yaml")
        print("  python3 kaiten_dsl_engine.py validate config.yaml")
        print("  python3 kaiten_dsl_engine.py dry-run config.yaml")
        sys.exit(1)

    command = sys.argv[1]
    config_path = sys.argv[2]

    # Загрузка конфигурации
    config = load_config(config_path)
    if not config:
        sys.exit(1)

    # Получение credentials из конфигурации или окружения
    kaiten_config = config.get('kaiten', {})
    domain = kaiten_config.get('domain') or os.environ.get('KAITEN_DOMAIN')
    token = kaiten_config.get('token') or os.environ.get('KAITEN_TOKEN')

    # Подстановка переменных окружения в токене
    if token and token.startswith('${env:'):
        var_name = token[6:-1]
        token = os.environ.get(var_name)

    if not domain or not token:
        logger.error("Не указаны domain и token")
        logger.error("Укажите в config.yaml или установите KAITEN_DOMAIN и KAITEN_TOKEN")
        sys.exit(1)

    # Определение режима
    dry_run = command in ['dry-run', 'validate']

    # Создание API и контекста
    api = KaitenAPI(domain, token, dry_run=dry_run)
    context = ExecutionContext(dry_run=dry_run)
    engine = KaitenDSLEngine(api, context)

    # Выполнение команды
    if command == 'validate':
        if engine.validate_config(config):
            print("✓ Конфигурация валидна")
            sys.exit(0)
        else:
            print("✗ Конфигурация невалидна")
            sys.exit(1)

    elif command in ['apply', 'dry-run']:
        if dry_run:
            logger.info("РЕЖИМ DRY-RUN (изменения НЕ применяются)")

        success = engine.execute(config)
        sys.exit(0 if success else 1)

    else:
        logger.error(f"Неизвестная команда: {command}")
        sys.exit(1)


if __name__ == "__main__":
    main()
