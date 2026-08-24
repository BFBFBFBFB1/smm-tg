#!/bin/bash
# Запускать ТОЛЬКО на сервере Timeweb (Linux), НЕ в Windows PowerShell.
set -euo pipefail

cd ~

echo "=== 1. Распаковка ==="
rm -rf ~/smm-tg
mkdir -p ~/smm-tg
tar -xzf ~/smm-tg-deploy.tgz -C ~/smm-tg
cd ~/smm-tg

echo "=== 2. Проверка (должно быть no-index и ~65 wheels) ==="
if ! grep -q 'no-index' Dockerfile; then
  echo "ОШИБКА: в Dockerfile нет no-index. Архив старый/битый."
  exit 1
fi
WHEEL_COUNT=$(ls wheels | wc -l)
echo "wheels: $WHEEL_COUNT"
if [ "$WHEEL_COUNT" -lt 50 ]; then
  echo "ОШИБКА: мало wheels ($WHEEL_COUNT)."
  exit 1
fi
grep no-index Dockerfile

echo "=== 3. .env ==="
if [ ! -f .env ]; then
  cat > .env << 'EOF'
BOT_TOKEN=
ADMIN_IDS=
PANEL_API_URL=https://smmpanelus.com/api/v2
PANEL_API_KEY=
YOOKASSA_SHOP_ID=
YOOKASSA_SECRET_KEY=
YOOKASSA_RETURN_URL=https://t.me/nakrutkatelebot
CRYPTOBOT_TOKEN=
CRYPTOBOT_API_URL=https://pay.crypt.bot/api
WEBHOOK_HOST=
WEBHOOK_PATH=/webhook/yookassa
WEBHOOK_SECRET=
MARKUP_PERCENT=30
MIN_TOPUP_RUB=100
ORDER_TIMEOUT_MINUTES=30
LOCAL_MODE=false
POSTGRES_HOST=postgres
POSTGRES_PORT=5432
POSTGRES_DB=smm_bot
POSTGRES_USER=smm
POSTGRES_PASSWORD=change_me_strong_password
REDIS_HOST=redis
REDIS_PORT=6379
REDIS_DB=0
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/1
LOG_LEVEL=INFO
EOF
  echo "Создан пустой .env — ЗАПОЛНИ токены: nano ~/smm-tg/.env"
  echo "После заполнения снова запусти: bash ~/smm-tg/server-deploy.sh"
  exit 0
fi

if grep -q 'LOCAL_MODE=true' .env; then
  echo "ОШИБКА: LOCAL_MODE=true. Нужно LOCAL_MODE=false"
  exit 1
fi
if grep -q 'POSTGRES_HOST=localhost' .env; then
  echo "ОШИБКА: POSTGRES_HOST=localhost. Нужно POSTGRES_HOST=postgres"
  exit 1
fi
if ! grep -q '^BOT_TOKEN=.\+' .env; then
  echo "ОШИБКА: BOT_TOKEN пустой. Заполни .env"
  exit 1
fi

echo "=== 4. Docker build (offline, без PyPI) ==="
docker compose down || true
docker compose build --no-cache

echo "=== 5. Запуск ==="
docker compose up -d

echo "=== 6. Статус ==="
sleep 3
docker compose ps
echo ""
echo "Логи бота (Ctrl+C чтобы выйти):"
docker compose logs --tail=80 bot
