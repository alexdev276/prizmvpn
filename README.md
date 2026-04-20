# Prizm VPN Client

FastAPI-клиент для VPN-сервиса поверх Remnawave: регистрация по email и паролю без обязательного подтверждения, вход, сброс пароля, личный кабинет, баланс, устройства, VLESS-конфигурации, платежи YooKassa/CryptoCloud и простая админ-панель.

## Запуск

1. Скопируйте настройки:

```bash
cp .env.example .env
```

2. Заполните `SECRET_KEY`, `DATABASE_URL`, SMTP, Remnawave и платежные ключи.

Рекомендуемый Python: 3.12 или 3.13. На Python 3.14 пакет `remnawave` пока может не собираться из-за зависимости `pydantic-core`, поэтому в `requirements.txt` SDK подключен только для Python <3.14; сам клиент Remnawave в приложении изолирован и работает через Remna API.

3. Установите зависимости:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip3 install -r requirements.txt
```

4. Примените миграции:

```bash
alembic upgrade head
```

5. Запустите приложение:

```bash
uvicorn app.main:app --reload
```

## Remnawave

По умолчанию `REMNA_MOCK_MODE=true`, чтобы локально проверить регистрацию, вход и кабинет без реальной панели. Для боевого режима задайте:

```env
REMNA_MOCK_MODE=false
REMNA_BASE_URL=https://your-remnawave-panel.example
REMNA_TOKEN=...
```

Регистрация сразу активирует аккаунт на клиентском сайте. Каждый новый пункт в разделе "Устройства" создает отдельного пользователя в Remnawave с username вида `{email}-{device_id}` и сохраняет его `uuid`/subscription URL в записи устройства. Для устройств в кабинете генерируются отдельные subscription-ссылки вида `/subscription/{public_id}/{config_uuid}.txt`; кнопку "Заменить настройки устройства" можно использовать для обновления ссылки.

## Кабинет

- `/account` показывает баланс, устройства, пополнение, историю и инструкции.
- `/account/top-up` принимает сумму и запускает тестовое/боевое пополнение через YooKassa или CryptoCloud.
- `/account/history` показывает пополнения, списания и служебные движения по счету.
- Каждое устройство стоит 100 рублей в месяц. Списание считается лениво при заходе в кабинет/историю: `100 / 30 / 24` рублей за полный час.
- Каждое устройство соответствует отдельному пользователю в Remnawave. Публичная ссылка `/subscription/{public_id}/{config_uuid}.txt` проксирует subscription этого Remnawave-пользователя.
- Новое устройство нельзя удалить первые 24 часа. После удаления оно пропадает из списка и больше не участвует в списаниях.

## Фронтенд

Переданные SVG-макеты лежат в `app/static/landing`. Главная страница использует их как публичную основу сайта; формы входа/регистрации и кабинет сверстаны Jinja2-шаблонами в стиле мобильных JPG-референсов и адаптированы под десктоп.

## Тесты

```bash
pytest
```

SMTP и Remnawave в тестах мокируются, реальные письма и внешние запросы не отправляются.

## Деплой на пустой сервер

Для one-server развертывания добавлен скрипт:

```bash
deploy/prizmvpn-deploy.sh
```

Что делает скрипт на Ubuntu/Debian сервере:

- устанавливает Docker и Docker Compose plugin;
- клонирует клиентскую часть из `https://github.com/alexdev276/prizmvpn.git`;
- поднимает Remnawave Panel, PostgreSQL/Valkey для Remnawave, PostgreSQL для клиента, клиентское FastAPI-приложение и Caddy;
- выпускает HTTPS-сертификаты через Caddy для `quantvpn.mooo.com` и `prizmvpn.space`;
- соединяет клиент и Remnawave в одной Docker-сети: клиент ходит к панели по `http://remnawave:3000`;
- создает helper-скрипты для установки Remnawave API token и Remnawave Node.

На сервере:

```bash
scp deploy/prizmvpn-deploy.sh root@SERVER_IP:/root/
ssh root@SERVER_IP
bash /root/prizmvpn-deploy.sh
```

Перед запуском убедитесь, что A-записи доменов указывают на сервер:

- `quantvpn.mooo.com` -> IP сервера;
- `prizmvpn.space` -> IP сервера.

После запуска:

1. Откройте `https://quantvpn.mooo.com` и создайте первого администратора Remnawave.
2. Создайте API token в Remnawave.
3. Подключите клиентскую часть к панели:

```bash
sudo /opt/prizmvpn/bin/set-remna-token.sh <REMNA_API_TOKEN>
```

4. Добавьте Remnawave Node в панели. Если node будет на этом же сервере, используйте helper:

```bash
sudo /opt/prizmvpn/bin/install-remnanode.sh <SECRET_KEY_FROM_NODE_CARD>
```

Платежные ключи и SMTP можно передать в скрипт переменными окружения, например:

```bash
ADMIN_EMAILS=admin@prizmvpn.space \
SMTP_HOST=smtp.example.com \
SMTP_USERNAME=user \
SMTP_PASSWORD=password \
YOOKASSA_SHOP_ID=... \
YOOKASSA_SECRET_KEY=... \
bash /root/prizmvpn-deploy.sh
```

Если Caddy не стартует с ошибкой `Bind for 0.0.0.0:80 failed: port is already allocated`, значит на сервере уже запущен другой HTTP/HTTPS сервер. Проверьте:

```bash
sudo ss -ltnp 'sport = :80 or sport = :443'
sudo docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'
```

На пустом сервере обычно достаточно остановить лишний nginx/apache/caddy/traefik и повторить запуск:

```bash
sudo systemctl stop nginx apache2 caddy traefik 2>/dev/null || true
sudo docker stop <container_name_using_80_or_443>
bash /root/prizmvpn-deploy.sh
```

## Отправка писем через Outlook Microsoft Graph

Если обычный Outlook SMTP возвращает `SmtpClientAuthentication is disabled for the Mailbox`, используйте Microsoft Graph OAuth вместо SMTP.

1. Создайте приложение в Microsoft Entra:

- откройте `https://entra.microsoft.com`;
- `Applications` -> `App registrations` -> `New registration`;
- для личного Outlook выберите аккаунты Microsoft personal, если этот вариант доступен, или режим с personal Microsoft accounts;
- скопируйте `Application (client) ID`;
- в `API permissions` добавьте Microsoft Graph delegated permission `Mail.Send`;
- в `Authentication` включите `Allow public client flows`.

2. Получите refresh token на сервере:

```bash
cd /opt/prizmvpn/client
sudo python3 scripts/ms_graph_oauth.py \
  --client-id <APPLICATION_CLIENT_ID> \
  --tenant consumers \
  --write-env /opt/prizmvpn/env/prizmvpn.env
```

Скрипт покажет код и ссылку Microsoft. Откройте ссылку, войдите в Outlook-аккаунт отправителя и подтвердите доступ.

3. Пересоздайте контейнер клиента:

```bash
cd /opt/prizmvpn
sudo docker compose up -d --force-recreate prizmvpn-client
sudo docker compose logs -f --tail=100 prizmvpn-client
```

В env-файле это выглядит так:

```env
EMAIL_PROVIDER=graph
MS_GRAPH_TENANT=consumers
MS_GRAPH_CLIENT_ID=<APPLICATION_CLIENT_ID>
MS_GRAPH_REFRESH_TOKEN=<REFRESH_TOKEN_FROM_SCRIPT>
MS_GRAPH_SAVE_TO_SENT_ITEMS=true
SMTP_FROM_NAME=Prizm VPN
```

Для бизнес-аккаунта Microsoft 365 вместо `consumers` можно использовать `organizations` или tenant ID.
