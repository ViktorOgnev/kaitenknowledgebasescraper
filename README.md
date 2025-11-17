

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


### Установить claude-code или openai codex:

https://code.claude.com/docs/en 
https://developers.openai.com/codex/cli/

Готово! Теперь:

* Docker запускает всё **одной командой**
* Скрипт сохраняет результаты **в вашу локальную папку**
* Claude или OpenAI Codex могут работать **прямо внутри этой папки**, анализировать файлы, отвечать на вопросы и помогать вам дальше. Просто пишем вопросы как в поддержку и получаем ответы по функционалу


