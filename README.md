

## **1. Установка Docker**

**Windows / Mac / Linux:**
[https://docs.docker.com/get-docker/](https://docs.docker.com/get-docker/)

---

## **2. Запуск скрипта одной командой**

⚠️ Выполните в директории, где лежат `scrape_docs.py` и `requirements.txt`.

```bash
docker run --rm -it -v "$PWD":/app python /bin/bash -c "cd /app && pip install -r requirements.txt && python scrape_docs.py"
```

После выполнения все результаты останутся у вас в текущей папке (на хосте, не в контейнере).

---

## **3. Перейти в папку, куда скрипт положил данные (1 строка)**

```bash
cd путь/к/папке/со/скаппингом
```

(Если скрипт кладёт в `output/`, то просто `cd output`.)

---

## **4. Запуск Claude в директории проекта (1 строка)**

```bash
npx @anthropic-ai/claude-code
```

Документация:
[https://docs.anthropic.com/en/docs/claude-code](https://docs.anthropic.com/en/docs/claude-code)

---

## **5. Запуск OpenAI Codex / Code Interpreter в папке (1 строка)**

```bash
npx openai dev
```

Документация:
[https://platform.openai.com/docs/guides/dev](https://platform.openai.com/docs/guides/dev)

---

Готово! Теперь:

* Docker запускает всё **одной командой**
* Скрипт сохраняет результаты **в вашу локальную папку**
* Claude или OpenAI Codex могут работать **прямо внутри этой папки**, анализировать файлы, отвечать на вопросы и помогать вам дальше. Просто пишем вопросы как в поддержку и получаем ответы по функционалу


