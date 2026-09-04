#!/usr/bin/env bash
# Brings up a local dev environment reachable from other devices on the LAN:
# Postgres, migrations, seed data, and the API server over HTTPS on 0.0.0.0.
#
# Requires a mkcert certificate for your Mac's current LAN IP. Generate one with:
#   brew install mkcert nss
#   mkcert -install
#   mkcert -cert-file certs/dev-lan.pem -key-file certs/dev-lan-key.pem <LAN-IP> localhost 127.0.0.1
#
# Then trust the mkcert root CA (`mkcert -CAROOT`) on your iOS test device:
# install the rootCA.pem as a configuration profile, then enable full trust
# under Settings > General > About > Certificate Trust Settings.
set -euo pipefail
cd "$(dirname "$0")/.."

CERT_DIR="certs"
CERT_FILE="$CERT_DIR/dev-lan.pem"
KEY_FILE="$CERT_DIR/dev-lan-key.pem"
LAN_IP="${MIYA_LAN_IP:-$(ipconfig getifaddr en0 2>/dev/null || true)}"

if [[ -z "$LAN_IP" ]]; then
  echo "Could not determine LAN IP via 'ipconfig getifaddr en0'. Set MIYA_LAN_IP explicitly." >&2
  exit 1
fi

if [[ ! -f "$CERT_FILE" || ! -f "$KEY_FILE" ]]; then
  echo "Missing mkcert cert/key at $CERT_FILE / $KEY_FILE." >&2
  echo "Generate one with:" >&2
  echo "  mkcert -cert-file $CERT_FILE -key-file $KEY_FILE $LAN_IP localhost 127.0.0.1" >&2
  exit 1
fi

docker compose up -d
until docker compose exec -T postgres pg_isready -U miya -d miya >/dev/null 2>&1; do
  sleep 1
done

uv run alembic upgrade head
uv run seed

echo "Serving on https://${LAN_IP}:8000 (PUBLIC_BASE_URL=https://${LAN_IP}:8000)"
echo "Point the iOS scheme's MIYA_SERVER_URL env var at that URL."

PUBLIC_BASE_URL="https://${LAN_IP}:8000" \
  uv run uvicorn miya_server.main:app \
  --host 0.0.0.0 --port 8000 \
  --ssl-keyfile "$KEY_FILE" --ssl-certfile "$CERT_FILE" \
  --reload
