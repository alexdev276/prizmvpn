#!/usr/bin/env bash
set -Eeuo pipefail

PANEL_DOMAIN="${PANEL_DOMAIN:-quantvpn.mooo.com}"
CLIENT_DOMAIN="${CLIENT_DOMAIN:-prizmvpn.space}"
CLIENT_REPO_URL="${CLIENT_REPO_URL:-https://github.com/alexdev276/prizmvpn.git}"
CLIENT_BRANCH="${CLIENT_BRANCH:-main}"
INSTALL_DIR="${INSTALL_DIR:-/opt/prizmvpn}"
ACME_EMAIL="${ACME_EMAIL:-}"

CLIENT_DIR="${INSTALL_DIR}/client"
ENV_DIR="${INSTALL_DIR}/env"
BIN_DIR="${INSTALL_DIR}/bin"
REMNA_ENV="${ENV_DIR}/remnawave.env"
CLIENT_ENV="${ENV_DIR}/prizmvpn.env"
CLIENT_DB_ENV="${ENV_DIR}/prizmvpn-db.env"

usage() {
    cat <<USAGE
Prizm VPN one-server deploy script.

Run on a clean Ubuntu/Debian server:
  sudo bash prizmvpn-deploy.sh

Optional environment variables:
  PANEL_DOMAIN=quantvpn.mooo.com
  CLIENT_DOMAIN=prizmvpn.space
  CLIENT_REPO_URL=https://github.com/alexdev276/prizmvpn.git
  CLIENT_BRANCH=main
  INSTALL_DIR=/opt/prizmvpn
  ACME_EMAIL=admin@example.com
  ADMIN_EMAILS=admin@example.com
  REMNA_TOKEN=token-from-remnawave

SMTP and payment variables can also be passed with their app env names:
  SMTP_HOST, SMTP_PORT, SMTP_USERNAME, SMTP_PASSWORD, SMTP_FROM
  YOOKASSA_SHOP_ID, YOOKASSA_SECRET_KEY, YOOKASSA_WEBHOOK_SECRET
  CRYPTOCLOUD_API_KEY, CRYPTOCLOUD_SHOP_ID, CRYPTOCLOUD_WEBHOOK_SECRET
USAGE
}

log() {
    printf '\n[%s] %s\n' "$(date '+%H:%M:%S')" "$*"
}

die() {
    printf '\nERROR: %s\n' "$*" >&2
    exit 1
}

random_hex() {
    openssl rand -hex "${1:-32}"
}

get_env_value() {
    local file="$1"
    local key="$2"
    [[ -f "$file" ]] || return 0
    awk -v key="$key" '
        index($0, key "=") == 1 {
            sub("^[^=]*=", "")
            print
            exit
        }
    ' "$file"
}

set_env_value() {
    local file="$1"
    local key="$2"
    local value="$3"
    local tmp

    mkdir -p "$(dirname "$file")"
    touch "$file"
    tmp="$(mktemp)"
    awk -v key="$key" -v value="$value" '
        index($0, key "=") == 1 {
            if (!done) {
                print key "=" value
                done = 1
            }
            next
        }
        { print }
        END {
            if (!done) {
                print key "=" value
            }
        }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
}

set_env_default() {
    local file="$1"
    local key="$2"
    local value="$3"
    local current

    current="$(get_env_value "$file" "$key" || true)"
    if [[ -z "$current" ]]; then
        set_env_value "$file" "$key" "$value"
    fi
}

set_env_from_host_or_default() {
    local file="$1"
    local key="$2"
    local value="${!key-}"
    local default_value="${3:-}"

    if [[ -n "$value" ]]; then
        set_env_value "$file" "$key" "$value"
    else
        set_env_default "$file" "$key" "$default_value"
    fi
}

compose() {
    docker compose --project-directory "$INSTALL_DIR" -f "${INSTALL_DIR}/docker-compose.yml" "$@"
}

require_root() {
    if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
        usage
        exit 0
    fi

    if [[ "${EUID}" -ne 0 ]]; then
        exec sudo -E bash "$0" "$@"
    fi
}

install_packages() {
    log "Installing base packages"
    if ! command -v apt-get >/dev/null 2>&1; then
        die "This script supports Debian/Ubuntu servers with apt-get."
    fi

    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    apt-get install -y ca-certificates curl git iproute2 openssl
}

install_docker() {
    if ! command -v docker >/dev/null 2>&1; then
        log "Installing Docker"
        curl -fsSL https://get.docker.com | sh
    fi

    systemctl enable --now docker >/dev/null 2>&1 || true

    if ! docker compose version >/dev/null 2>&1; then
        log "Installing Docker Compose plugin"
        apt-get install -y docker-compose-plugin
    fi
}

prepare_layout() {
    log "Preparing ${INSTALL_DIR}"
    mkdir -p "$INSTALL_DIR" "$ENV_DIR" "$BIN_DIR"
    chmod 700 "$ENV_DIR"
}

sync_client_repo() {
    log "Fetching client repository ${CLIENT_REPO_URL}"
    if [[ -d "${CLIENT_DIR}/.git" ]]; then
        git -C "$CLIENT_DIR" fetch origin "$CLIENT_BRANCH"
        git -C "$CLIENT_DIR" checkout "$CLIENT_BRANCH"
        git -C "$CLIENT_DIR" pull --ff-only origin "$CLIENT_BRANCH"
        return
    fi

    if [[ -e "$CLIENT_DIR" ]]; then
        die "${CLIENT_DIR} already exists and is not a git repository."
    fi

    git clone --depth=1 --branch "$CLIENT_BRANCH" "$CLIENT_REPO_URL" "$CLIENT_DIR"
}

ensure_client_container_files() {
    if [[ ! -f "${CLIENT_DIR}/Dockerfile" ]]; then
        log "Adding fallback Dockerfile to client repository checkout"
        cat > "${CLIENT_DIR}/Dockerfile" <<'DOCKERFILE'
FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --upgrade pip \
    && pip install -r requirements.txt

COPY . .

RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips", "*"]
DOCKERFILE
    fi

    if [[ ! -f "${CLIENT_DIR}/.dockerignore" ]]; then
        cat > "${CLIENT_DIR}/.dockerignore" <<'DOCKERIGNORE'
.git
.pytest_cache
__pycache__
*.py[cod]
.DS_Store
.env
.env.*
!.env.example
.venv
venv
prizm_vpn.db
tests
DOCKERIGNORE
    fi
}

write_remnawave_env() {
    local db_password

    db_password="$(get_env_value "$REMNA_ENV" POSTGRES_PASSWORD || true)"
    [[ -n "$db_password" ]] || db_password="$(random_hex 24)"

    set_env_value "$REMNA_ENV" APP_PORT "3000"
    set_env_value "$REMNA_ENV" METRICS_PORT "3001"
    set_env_value "$REMNA_ENV" API_INSTANCES "1"
    set_env_value "$REMNA_ENV" DATABASE_URL "\"postgresql://postgres:${db_password}@remnawave-db:5432/postgres\""
    set_env_value "$REMNA_ENV" REDIS_SOCKET "/var/run/valkey/valkey.sock"
    set_env_default "$REMNA_ENV" JWT_AUTH_SECRET "$(random_hex 64)"
    set_env_default "$REMNA_ENV" JWT_API_TOKENS_SECRET "$(random_hex 64)"
    set_env_value "$REMNA_ENV" IS_TELEGRAM_NOTIFICATIONS_ENABLED "false"
    set_env_default "$REMNA_ENV" TELEGRAM_BOT_TOKEN "change_me"
    set_env_default "$REMNA_ENV" TELEGRAM_NOTIFY_USERS "change_me"
    set_env_default "$REMNA_ENV" TELEGRAM_NOTIFY_NODES "change_me"
    set_env_default "$REMNA_ENV" TELEGRAM_NOTIFY_CRM "change_me"
    set_env_default "$REMNA_ENV" TELEGRAM_NOTIFY_SERVICE "change_me"
    set_env_default "$REMNA_ENV" TELEGRAM_NOTIFY_TBLOCKER "change_me"
    set_env_value "$REMNA_ENV" PANEL_DOMAIN "$PANEL_DOMAIN"
    set_env_value "$REMNA_ENV" FRONT_END_DOMAIN "$PANEL_DOMAIN"
    set_env_value "$REMNA_ENV" SUB_PUBLIC_DOMAIN "${PANEL_DOMAIN}/api/sub"
    set_env_value "$REMNA_ENV" SWAGGER_PATH "/docs"
    set_env_value "$REMNA_ENV" SCALAR_PATH "/scalar"
    set_env_value "$REMNA_ENV" IS_DOCS_ENABLED "false"
    set_env_default "$REMNA_ENV" METRICS_USER "admin"
    set_env_default "$REMNA_ENV" METRICS_PASS "$(random_hex 64)"
    set_env_value "$REMNA_ENV" WEBHOOK_ENABLED "false"
    set_env_default "$REMNA_ENV" WEBHOOK_URL "https://example.com/webhook"
    set_env_default "$REMNA_ENV" WEBHOOK_SECRET_HEADER "$(random_hex 32)"
    set_env_value "$REMNA_ENV" BANDWIDTH_USAGE_NOTIFICATIONS_ENABLED "false"
    set_env_value "$REMNA_ENV" BANDWIDTH_USAGE_NOTIFICATIONS_THRESHOLD "[60,80]"
    set_env_value "$REMNA_ENV" NOT_CONNECTED_USERS_NOTIFICATIONS_ENABLED "false"
    set_env_value "$REMNA_ENV" NOT_CONNECTED_USERS_NOTIFICATIONS_AFTER_HOURS "[6,24,48]"
    set_env_value "$REMNA_ENV" POSTGRES_USER "postgres"
    set_env_value "$REMNA_ENV" POSTGRES_PASSWORD "$db_password"
    set_env_value "$REMNA_ENV" POSTGRES_DB "postgres"
}

write_client_env() {
    local db_password

    db_password="$(get_env_value "$CLIENT_DB_ENV" POSTGRES_PASSWORD || true)"
    [[ -n "$db_password" ]] || db_password="$(random_hex 24)"

    set_env_value "$CLIENT_DB_ENV" POSTGRES_USER "prizmvpn"
    set_env_value "$CLIENT_DB_ENV" POSTGRES_PASSWORD "$db_password"
    set_env_value "$CLIENT_DB_ENV" POSTGRES_DB "prizmvpn"

    set_env_value "$CLIENT_ENV" APP_NAME "Prizm VPN"
    set_env_value "$CLIENT_ENV" APP_ENV "production"
    set_env_value "$CLIENT_ENV" DEBUG "false"
    set_env_value "$CLIENT_ENV" BASE_URL "https://${CLIENT_DOMAIN}"
    set_env_value "$CLIENT_ENV" DATABASE_URL "postgresql+asyncpg://prizmvpn:${db_password}@prizmvpn-db:5432/prizmvpn"
    set_env_default "$CLIENT_ENV" SECRET_KEY "$(random_hex 64)"
    set_env_default "$CLIENT_ENV" ADMIN_EMAILS "${ADMIN_EMAILS:-admin@example.com}"

    set_env_from_host_or_default "$CLIENT_ENV" SMTP_HOST ""
    set_env_from_host_or_default "$CLIENT_ENV" SMTP_PORT "587"
    set_env_from_host_or_default "$CLIENT_ENV" SMTP_USERNAME ""
    set_env_from_host_or_default "$CLIENT_ENV" SMTP_PASSWORD ""
    set_env_from_host_or_default "$CLIENT_ENV" SMTP_FROM "noreply@${CLIENT_DOMAIN}"
    set_env_from_host_or_default "$CLIENT_ENV" SMTP_FROM_NAME "Prizm VPN"
    set_env_from_host_or_default "$CLIENT_ENV" SMTP_STARTTLS "true"
    set_env_from_host_or_default "$CLIENT_ENV" SMTP_SSL_TLS "false"
    set_env_from_host_or_default "$CLIENT_ENV" EMAIL_PROVIDER "smtp"
    set_env_from_host_or_default "$CLIENT_ENV" MS_GRAPH_TENANT "consumers"
    set_env_from_host_or_default "$CLIENT_ENV" MS_GRAPH_CLIENT_ID ""
    set_env_from_host_or_default "$CLIENT_ENV" MS_GRAPH_CLIENT_SECRET ""
    set_env_from_host_or_default "$CLIENT_ENV" MS_GRAPH_REFRESH_TOKEN ""
    set_env_from_host_or_default "$CLIENT_ENV" MS_GRAPH_SAVE_TO_SENT_ITEMS "true"

    set_env_value "$CLIENT_ENV" REMNA_BASE_URL "http://remnawave:3000"
    set_env_from_host_or_default "$CLIENT_ENV" REMNA_TOKEN ""
    set_env_value "$CLIENT_ENV" REMNA_MOCK_MODE "false"
    set_env_value "$CLIENT_ENV" REMNA_DEFAULT_DAYS "30"
    set_env_value "$CLIENT_ENV" REMNA_TRAFFIC_LIMIT_BYTES "107374182400"
    set_env_value "$CLIENT_ENV" REMNA_SUBSCRIPTION_PATH_TEMPLATE "/api/sub/{uuid}"

    set_env_from_host_or_default "$CLIENT_ENV" YOOKASSA_SHOP_ID ""
    set_env_from_host_or_default "$CLIENT_ENV" YOOKASSA_SECRET_KEY ""
    set_env_from_host_or_default "$CLIENT_ENV" YOOKASSA_WEBHOOK_SECRET ""
    set_env_from_host_or_default "$CLIENT_ENV" YOOKASSA_TEST_MODE "true"
    set_env_from_host_or_default "$CLIENT_ENV" CRYPTOCLOUD_API_KEY ""
    set_env_from_host_or_default "$CLIENT_ENV" CRYPTOCLOUD_SHOP_ID ""
    set_env_from_host_or_default "$CLIENT_ENV" CRYPTOCLOUD_WEBHOOK_SECRET ""
    set_env_from_host_or_default "$CLIENT_ENV" CRYPTOCLOUD_TEST_MODE "true"

    chmod 600 "$REMNA_ENV" "$CLIENT_ENV" "$CLIENT_DB_ENV"
}

write_compose_file() {
    log "Writing Docker Compose stack"
    cat > "${INSTALL_DIR}/docker-compose.yml" <<'COMPOSE'
x-common: &common
  ulimits:
    nofile:
      soft: 1048576
      hard: 1048576
  restart: always
  networks:
    - remnawave-network

x-logging: &logging
  logging:
    driver: json-file
    options:
      max-size: 100m
      max-file: "5"

services:
  remnawave:
    image: remnawave/backend:2
    container_name: remnawave
    hostname: remnawave
    <<: [*common, *logging]
    env_file:
      - ./env/remnawave.env
    volumes:
      - valkey-socket:/var/run/valkey
    ports:
      - 127.0.0.1:3000:3000
      - 127.0.0.1:3001:3001
    healthcheck:
      test: ["CMD-SHELL", "curl -f http://localhost:$${METRICS_PORT:-3001}/health"]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s
    depends_on:
      remnawave-db:
        condition: service_healthy
      remnawave-redis:
        condition: service_healthy

  remnawave-db:
    image: postgres:17.6
    container_name: remnawave-db
    hostname: remnawave-db
    <<: [*common, *logging]
    env_file:
      - ./env/remnawave.env
    environment:
      TZ: UTC
    ports:
      - 127.0.0.1:6767:5432
    volumes:
      - remnawave-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 3s
      timeout: 10s
      retries: 3

  remnawave-redis:
    image: valkey/valkey:9-alpine
    container_name: remnawave-redis
    hostname: remnawave-redis
    <<: [*common, *logging]
    volumes:
      - valkey-socket:/var/run/valkey
    command: >
      valkey-server --save "" --appendonly no --maxmemory-policy noeviction
      --loglevel warning --unixsocket /var/run/valkey/valkey.sock
      --unixsocketperm 777 --port 0
    healthcheck:
      test: ["CMD", "valkey-cli", "-s", "/var/run/valkey/valkey.sock", "ping"]
      interval: 3s
      timeout: 3s
      retries: 3

  prizmvpn-db:
    image: postgres:17-alpine
    container_name: prizmvpn-db
    hostname: prizmvpn-db
    <<: [*common, *logging]
    env_file:
      - ./env/prizmvpn-db.env
    volumes:
      - prizmvpn-db-data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 3s
      timeout: 10s
      retries: 5

  prizmvpn-client:
    build:
      context: ./client
      dockerfile: Dockerfile
    image: prizmvpn-client:local
    container_name: prizmvpn-client
    hostname: prizmvpn-client
    <<: [*common, *logging]
    env_file:
      - ./env/prizmvpn.env
    command: >
      sh -c "alembic upgrade head &&
      uvicorn app.main:app --host 0.0.0.0 --port 8000
      --proxy-headers --forwarded-allow-ips='*'"
    depends_on:
      prizmvpn-db:
        condition: service_healthy
      remnawave:
        condition: service_started
    healthcheck:
      test: ["CMD-SHELL", "python -c \"import socket; s = socket.create_connection(('127.0.0.1', 8000), 5); s.close()\""]
      interval: 30s
      timeout: 5s
      retries: 3
      start_period: 30s

  caddy:
    image: caddy:2.9
    container_name: prizmvpn-caddy
    hostname: prizmvpn-caddy
    <<: [*common, *logging]
    ports:
      - 80:80
      - 443:443
    volumes:
      - ./Caddyfile:/etc/caddy/Caddyfile:ro
      - caddy-data:/data
      - caddy-config:/config
    depends_on:
      remnawave:
        condition: service_started
      prizmvpn-client:
        condition: service_started

networks:
  remnawave-network:
    name: remnawave-network
    driver: bridge
    external: false

volumes:
  remnawave-db-data:
    name: remnawave-db-data
    driver: local
    external: false
  valkey-socket:
    name: valkey-socket
    driver: local
    external: false
  prizmvpn-db-data:
    name: prizmvpn-db-data
    driver: local
    external: false
  caddy-data:
    name: prizmvpn-caddy-data
    driver: local
    external: false
  caddy-config:
    name: prizmvpn-caddy-config
    driver: local
    external: false
COMPOSE
}

write_caddyfile() {
    log "Writing Caddy reverse proxy config"
    if [[ -n "$ACME_EMAIL" ]]; then
        cat > "${INSTALL_DIR}/Caddyfile" <<CADDY
{
    email ${ACME_EMAIL}
}

${PANEL_DOMAIN} {
    encode zstd gzip
    header Strict-Transport-Security "max-age=31536000"
    reverse_proxy remnawave:3000
}

${CLIENT_DOMAIN} {
    encode zstd gzip
    header Strict-Transport-Security "max-age=31536000"
    reverse_proxy prizmvpn-client:8000
}
CADDY
    else
        cat > "${INSTALL_DIR}/Caddyfile" <<CADDY
${PANEL_DOMAIN} {
    encode zstd gzip
    header Strict-Transport-Security "max-age=31536000"
    reverse_proxy remnawave:3000
}

${CLIENT_DOMAIN} {
    encode zstd gzip
    header Strict-Transport-Security "max-age=31536000"
    reverse_proxy prizmvpn-client:8000
}
CADDY
    fi
}

write_helper_scripts() {
    cat > "${BIN_DIR}/set-remna-token.sh" <<'TOKEN_HELPER'
#!/usr/bin/env bash
set -Eeuo pipefail

INSTALL_DIR="${INSTALL_DIR:-/opt/prizmvpn}"
ENV_FILE="${INSTALL_DIR}/env/prizmvpn.env"
TOKEN="${1:-${REMNA_TOKEN:-}}"

if [[ -z "$TOKEN" ]]; then
    echo "Usage: sudo ${INSTALL_DIR}/bin/set-remna-token.sh <REMNA_API_TOKEN>" >&2
    exit 1
fi

set_env_value() {
    local file="$1"
    local key="$2"
    local value="$3"
    local tmp

    tmp="$(mktemp)"
    awk -v key="$key" -v value="$value" '
        index($0, key "=") == 1 {
            if (!done) {
                print key "=" value
                done = 1
            }
            next
        }
        { print }
        END {
            if (!done) {
                print key "=" value
            }
        }
    ' "$file" > "$tmp"
    mv "$tmp" "$file"
}

set_env_value "$ENV_FILE" REMNA_TOKEN "$TOKEN"
set_env_value "$ENV_FILE" REMNA_MOCK_MODE "false"
chmod 600 "$ENV_FILE"
docker compose --project-directory "$INSTALL_DIR" -f "${INSTALL_DIR}/docker-compose.yml" up -d prizmvpn-client
echo "REMNA_TOKEN updated and prizmvpn-client restarted."
TOKEN_HELPER

    cat > "${BIN_DIR}/install-remnanode.sh" <<'NODE_HELPER'
#!/usr/bin/env bash
set -Eeuo pipefail

NODE_DIR="${NODE_DIR:-/opt/remnanode}"
NODE_PORT="${NODE_PORT:-2222}"
SECRET_KEY="${1:-${SECRET_KEY:-}}"

SECRET_KEY="${SECRET_KEY#SECRET_KEY=}"
SECRET_KEY="${SECRET_KEY%\"}"
SECRET_KEY="${SECRET_KEY#\"}"

if [[ -z "$SECRET_KEY" ]]; then
    cat >&2 <<USAGE
Usage:
  sudo /opt/prizmvpn/bin/install-remnanode.sh <SECRET_KEY_FROM_REMNAWAVE_NODE_CARD>

You get SECRET_KEY after adding a node in Remnawave:
  Nodes -> Management -> + -> copy SECRET_KEY from the generated compose.
USAGE
    exit 1
fi

mkdir -p "$NODE_DIR"
cat > "${NODE_DIR}/docker-compose.yml" <<NODE_COMPOSE
services:
  remnanode:
    image: remnawave/node:latest
    container_name: remnanode
    hostname: remnanode
    network_mode: host
    restart: always
    cap_add:
      - NET_ADMIN
    ulimits:
      nofile:
        soft: 1048576
        hard: 1048576
    environment:
      - NODE_PORT=${NODE_PORT}
      - SECRET_KEY=${SECRET_KEY}
NODE_COMPOSE

docker compose --project-directory "$NODE_DIR" -f "${NODE_DIR}/docker-compose.yml" up -d
echo "Remnawave Node started on NODE_PORT=${NODE_PORT}."
echo "Firewall reminder: allow NODE_PORT only from the Remnawave panel IP."
NODE_HELPER

    chmod +x "${BIN_DIR}/set-remna-token.sh" "${BIN_DIR}/install-remnanode.sh"
}

check_dns() {
    local public_ip
    local domain
    local resolved

    public_ip="$(curl -fsS4 --max-time 5 https://api.ipify.org || true)"
    [[ -n "$public_ip" ]] || return 0

    for domain in "$PANEL_DOMAIN" "$CLIENT_DOMAIN"; do
        resolved="$(getent ahostsv4 "$domain" | awk '{print $1}' | sort -u | tr '\n' ' ' || true)"
        if [[ "$resolved" != *"$public_ip"* ]]; then
            printf '\nWARNING: %s currently resolves to [%s], but this server is %s.\n' "$domain" "${resolved:-no A record}" "$public_ip"
            printf 'Caddy will issue SSL certificates only after DNS points to this server.\n'
        fi
    done
}

open_firewall_ports() {
    if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
        log "Opening HTTP/HTTPS in UFW"
        ufw allow 80/tcp
        ufw allow 443/tcp
    fi
}

check_required_ports() {
    local port
    local conflicts
    local caddy_ports

    for port in 80 443; do
        conflicts="$(ss -H -ltnp "sport = :${port}" 2>/dev/null || true)"
        if [[ -n "$conflicts" ]]; then
            caddy_ports="$(docker ps --filter "name=^/prizmvpn-caddy$" --format '{{.Ports}}' || true)"
            if [[ "$caddy_ports" == *":${port}->"* ]]; then
                continue
            fi

            cat >&2 <<PORT_ERROR

ERROR: TCP port ${port} is already in use.

Caddy needs ports 80 and 443 to serve ${PANEL_DOMAIN} and ${CLIENT_DOMAIN}
and to issue HTTPS certificates automatically.

Current listener:
${conflicts}

Find Docker containers that may own this port:
  docker ps --format 'table {{.Names}}\t{{.Image}}\t{{.Ports}}'

Common fixes on a clean server:
  systemctl stop nginx apache2 caddy traefik 2>/dev/null || true
  docker stop <container_name_using_${port}>

Then rerun:
  bash $0

PORT_ERROR
            exit 1
        fi
    done
}

start_stack() {
    log "Starting Prizm VPN stack"
    compose pull remnawave remnawave-db remnawave-redis prizmvpn-db caddy
    compose up -d --build
}

print_summary() {
    cat <<SUMMARY

Done.

Panel:
  https://${PANEL_DOMAIN}

Client:
  https://${CLIENT_DOMAIN}

Files:
  ${INSTALL_DIR}/docker-compose.yml
  ${REMNA_ENV}
  ${CLIENT_ENV}

Useful commands:
  cd ${INSTALL_DIR} && docker compose ps
  cd ${INSTALL_DIR} && docker compose logs -f -t caddy remnawave prizmvpn-client

Important next steps:
  1. Open https://${PANEL_DOMAIN} and create the first Remnawave admin user.
  2. Create a Remnawave API token in the panel.
  3. Connect the client to the panel:
     sudo ${BIN_DIR}/set-remna-token.sh <REMNA_API_TOKEN>
  4. Add a Remnawave Node in the panel. If the node is on this same server, run:
     sudo ${BIN_DIR}/install-remnanode.sh <SECRET_KEY_FROM_NODE_CARD>

SUMMARY
}

main() {
    require_root "$@"
    install_packages
    install_docker
    prepare_layout
    sync_client_repo
    ensure_client_container_files
    write_remnawave_env
    write_client_env
    write_compose_file
    write_caddyfile
    write_helper_scripts
    check_dns
    open_firewall_ports
    check_required_ports
    start_stack
    print_summary
}

main "$@"
