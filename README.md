# TrainWaited

Telegram-бот для отслеживания билетов Белорусской железной дороги на `pass.rw.by`. Бот получает обновления через Telegram long polling и использует Playwright для чтения расписания. Входящий HTTP-порт не нужен; для регулярных проверок процесс должен постоянно работать.

## Возможности и ограничения

- Поиск поездов по станциям, дате и выбранному рейсу.
- Подписки на любые билеты, места в плацкарте или купе.
- В плацкарте можно выбрать нижние, верхние, боковые, нижние боковые или верхние боковые места.
- Уведомление отправляется при обнаружении подходящих билетов; бот не резервирует и не покупает их.
- Наличие считывается с `pass.rw.by` и может измениться до перехода к покупке. Сайт может временно показывать страницу проверки или изменить разметку; в таком случае сканирование будет недоступно.

## Команды Telegram

- `/start` — открыть главное меню.
- `/search` — создать подписку на поезд и места.
- `/my` — посмотреть, проверить или удалить свои подписки.
- `/help` — справка по боту.
- `/cancel` — отменить текущий шаг поиска.

## Требования

- Python 3.10 или новее для локального запуска.
- Для контейнерного запуска — Docker Desktop с работающим Linux Engine или Docker Engine и Docker Compose.
- Telegram-бот и его токен, созданные через BotFather.
- Исходящий HTTPS-доступ к Telegram и `pass.rw.by`. Публичный порт не требуется.

## Локальный запуск в Windows

В PowerShell из папки проекта создайте `.env` из примера, только если своего файла ещё нет:

```powershell
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

Укажите `BOT_TOKEN` в `.env`. Не публикуйте и не отправляйте токен. Если `.env` уже существует, не копируйте поверх него пример — отредактируйте имеющийся файл.

Создайте виртуальное окружение, установите зависимости и браузер Firefox для локального Playwright:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install firefox
.\.venv\Scripts\python.exe index.py
```

Локальная конфигурация по умолчанию также выбирает Firefox. Для запуска тестов в другом окне PowerShell используйте:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

## Запуск через Docker Compose

1. Убедитесь, что Docker Desktop запущен и Linux Engine готов.
2. Создайте `.env` из `.env.example`, только если файла ещё нет, и укажите `BOT_TOKEN`:

   ```powershell
   if (-not (Test-Path .env)) { Copy-Item .env.example .env }
   notepad .env
   ```

3. Из папки проекта проверьте конфигурацию и соберите/запустите worker:

   ```powershell
   docker compose config --quiet
   docker compose up -d --build
   docker compose ps
   ```

4. Просматривайте логи:

   ```powershell
   docker compose logs -f trainwaited-bot
   ```

Docker-образ устанавливает Firefox и его системные зависимости. Compose принудительно задаёт `BROWSER=firefox`, `HEADLESS=true` и путь хранилища внутри контейнера. Первый запуск скачивает образ, зависимости и браузер, поэтому может занять несколько минут.

Управление worker:

```powershell
docker compose stop
docker compose start
docker compose down
```

Для запуска Docker Desktop вместе с Windows включите соответствующую настройку **Start Docker Desktop when you sign in**. Политика `restart: unless-stopped` перезапускает контейнер, но сам Docker Engine тоже должен быть запущен.

**Важно:** при старте программа вызывает `run_polling(drop_pending_updates=True)`. Обновления Telegram, накопившиеся, пока бот был остановлен, будут отброшены.

## Хранение и резервные копии

Compose хранит подписки в постоянном Docker volume `trainwaited-data`. Запускайте только одну реплику: JSON-хранилище рассчитано на один процесс и не поддерживает согласованную запись из нескольких экземпляров.

Чтобы сохранить резервную копию в текущую папку PowerShell:

```powershell
docker compose cp trainwaited-bot:/app/data/subscriptions.json .\subscriptions-backup.json
```

Чтобы восстановить её в существующий контейнер:

```powershell
docker compose cp .\subscriptions-backup.json trainwaited-bot:/app/data/subscriptions.json
docker compose restart trainwaited-bot
```

`docker compose down` сохраняет named volume. **Не используйте `docker compose down -v`**, если хотите сохранить подписки: ключ `-v` удаляет volume.

### Переход со старого bind mount

Если в старой Compose-конфигурации хранилище было подключено как `.\data:/app/data`, до первого запуска новой конфигурации сохраните старый файл:

```powershell
Copy-Item .\data\subscriptions.json .\subscriptions-backup.json
```

Затем создайте/запустите контейнер с новой конфигурацией, восстановите файл в named volume и перезапустите worker:

```powershell
docker compose up -d
docker compose cp .\subscriptions-backup.json trainwaited-bot:/app/data/subscriptions.json
docker compose restart trainwaited-bot
```

После рестарта проверьте логи и список подписок в боте, прежде чем удалять резервную копию.

## Деплой и работа без платы за хостинг

Вариант без платы за хостинг — Docker на уже имеющемся компьютере или домашнем сервере, который включён и подключён к интернету. Электричество и интернет всё равно могут иметь стоимость. Бесплатные облачные тарифы меняются, могут требовать платёжную карту или приостанавливать простаивающие процессы; усыплённый worker не сможет проверять билеты.

Храните `BOT_TOKEN` в локальном `.env` или в системе секретов хостинга, а не в Git. `.env` и локальный `subscriptions.json` внесены в `.gitignore`; перед коммитом всё равно проверяйте staged-файлы. Деплой через `Procfile` должен запускать процесс типа worker и отдельно обеспечивать системные зависимости и Firefox Playwright; один `Procfile` браузер не устанавливает. Для простого самостоятельного деплоя используйте Docker Compose.

## Конфигурация

| Переменная | Значение по умолчанию | Описание |
| --- | --- | --- |
| `BOT_TOKEN` | — | Обязательный токен Telegram-бота |
| `CHECK_INTERVAL` | `60` | Интервал фоновой проверки в секундах; минимум 10 |
| `SUBSCRIPTIONS_FILE` | `subscriptions.json`, если переменная не задана | Путь к JSON-файлу подписок; `.env.example` задаёт `data/subscriptions.json`, Compose — `/app/data/subscriptions.json` |
| `MAX_CONCURRENT_CHECKS` | `2` | Максимум параллельных проверок сайта; минимум 1 |
| `CACHE_TTL` | `45` | Время жизни кэшированного результата в секундах; минимум 0 |
| `HEADLESS` | `true` | Запуск браузера без окна |
| `BROWSER` | `firefox` | Playwright-браузер: `firefox` или `chromium`; в Docker установлен Firefox |

При неверных значениях интервала, числа параллельных проверок или TTL приложение завершится с ошибкой конфигурации.

## Эксплуатация

- Первичная проверка подписки планируется после её создания; остальные подписки проверяются периодической задачей.
- Штатное завершение закрывает ресурсы Playwright; Docker перезапускает контейнер после остановки, если его не остановили вручную.
- Следите за логами: сайт БЖД — внешняя зависимость и может временно ограничить запросы или изменить HTML-разметку.
- JSON-хранилище подходит для одного небольшого экземпляра. Перед масштабированием на несколько worker перенесите данные в SQLite/PostgreSQL и добавьте миграции, резервное копирование и мониторинг.
