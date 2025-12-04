#!/usr/bin/env python3
import argparse
import subprocess
from pathlib import Path
import sys


def convert_md_dir(src_dir: Path, dst_dir: Path):
    if not src_dir.exists() or not src_dir.is_dir():
        raise ValueError(f"Исходная директория не найдена или это не директория: {src_dir}")

    dst_dir.mkdir(parents=True, exist_ok=True)

    md_files = list(src_dir.rglob("*.md"))
    if not md_files:
        print(f"В директории {src_dir} не найдено файлов .md")
        return

    for md_path in md_files:
        # относительный путь внутри исходной директории
        rel_path = md_path.relative_to(src_dir)
        # путь к pdf в выходной директории (с сохранением подпапок)
        pdf_path = dst_dir / rel_path.with_suffix(".pdf")
        pdf_path.parent.mkdir(parents=True, exist_ok=True)

        print(f"Конвертирую: {md_path} -> {pdf_path}")
        try:
            subprocess.run(
                ["pandoc", str(md_path), "-o", str(pdf_path)],
                check=True,
            )
        except subprocess.CalledProcessError as e:
            print(f"Ошибка при конвертации файла {md_path}: {e}", file=sys.stderr)


def main():
    parser = argparse.ArgumentParser(
        description="Конвертер всех .md файлов в директории в .pdf в соседнюю директорию."
    )
    parser.add_argument(
        "src_dir",
        type=str,
        help="Путь к исходной директории с .md файлами",
    )
    parser.add_argument(
        "--out",
        type=str,
        default=None,
        help="Необязательно: путь к выходной директории. "
             "Если не указан, будет создана соседняя директория с суффиксом _pdf.",
    )

    args = parser.parse_args()

    src_dir = Path(args.src_dir).resolve()

    if args.out:
        dst_dir = Path(args.out).resolve()
    else:
        # "Соседняя" директория: <родитель>/<имя_папки>_pdf
        dst_dir = src_dir.parent / f"{src_dir.name}_pdf"

    print(f"Исходная директория: {src_dir}")
    print(f"Выходная директория:  {dst_dir}")

    try:
        convert_md_dir(src_dir, dst_dir)
    except Exception as e:
        print(f"Ошибка: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
