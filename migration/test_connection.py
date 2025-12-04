#!/usr/bin/env python3
"""
Скрипт для проверки подключения к Kaiten API
Использовать перед запуском миграции
"""

import requests
import sys


def test_connection(domain: str, token: str) -> bool:
    """Проверка подключения к Kaiten API"""
    base_url = f"https://{domain}.kaiten.ru/api/v1"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }

    print(f"\n🔍 Проверка подключения к {domain}.kaiten.ru...")

    try:
        # Пробуем получить список пространств
        response = requests.get(f"{base_url}/spaces", headers=headers, timeout=10)

        if response.status_code == 401:
            print("❌ ОШИБКА: Неверный API токен (401 Unauthorized)")
            return False

        if response.status_code == 403:
            print("❌ ОШИБКА: Нет прав доступа (403 Forbidden)")
            return False

        if response.status_code == 404:
            print("❌ ОШИБКА: Неверный домен или эндпоинт (404 Not Found)")
            return False

        response.raise_for_status()
        spaces = response.json()

        print(f"✅ Подключение успешно!")
        print(f"   Домен: {domain}.kaiten.ru")
        print(f"   Пространств: {len(spaces)}")

        # Дополнительная информация
        if 'X-RateLimit-Remaining' in response.headers:
            print(f"   Rate limit remaining: {response.headers['X-RateLimit-Remaining']}")

        # Получаем статистику
        cards_response = requests.get(
            f"{base_url}/cards",
            headers=headers,
            params={'limit': 1},
            timeout=10
        )
        if cards_response.status_code == 200:
            print(f"   API работает корректно")

        return True

    except requests.exceptions.ConnectionError:
        print(f"❌ ОШИБКА: Не удалось подключиться к {domain}.kaiten.ru")
        print("   Проверьте правильность домена и интернет-соединение")
        return False

    except requests.exceptions.Timeout:
        print("❌ ОШИБКА: Таймаут подключения")
        return False

    except requests.exceptions.RequestException as e:
        print(f"❌ ОШИБКА: {e}")
        return False


def main():
    print("=" * 70)
    print("ПРОВЕРКА ПОДКЛЮЧЕНИЯ К KAITEN API")
    print("=" * 70)

    # Проверка исходного аккаунта
    print("\n📤 ИСХОДНЫЙ АККАУНТ:")
    source_domain = input("   Домен (например, 'company'): ").strip()
    source_token = input("   API Token: ").strip()

    source_ok = test_connection(source_domain, source_token)

    # Проверка целевого аккаунта
    print("\n📥 ЦЕЛЕВОЙ АККАУНТ:")
    target_domain = input("   Домен (например, 'newcompany'): ").strip()
    target_token = input("   API Token: ").strip()

    target_ok = test_connection(target_domain, target_token)

    # Итог
    print("\n" + "=" * 70)
    print("РЕЗУЛЬТАТ ПРОВЕРКИ")
    print("=" * 70)

    if source_ok and target_ok:
        print("✅ Оба аккаунта доступны!")
        print("✅ Можно запускать миграцию: python3 kaiten_migration.py")
        return 0
    else:
        print("❌ Исправьте ошибки подключения перед запуском миграции")
        return 1


if __name__ == "__main__":
    sys.exit(main())
