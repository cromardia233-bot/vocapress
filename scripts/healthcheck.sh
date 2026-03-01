#!/bin/bash
# 헬스체크 스크립트 — 컨테이너 상태 확인 및 텔레그램 알림
# cron 설정: */5 * * * * /home/ubuntu/telegram-bots/scripts/healthcheck.sh

set -euo pipefail

# 텔레그램 알림 설정 (서버에서 직접 수정)
ALERT_BOT_TOKEN="${HEALTHCHECK_BOT_TOKEN:-}"
ALERT_CHAT_ID="${HEALTHCHECK_CHAT_ID:-}"

CONTAINERS=("earnings-call-agent" "investment-analyst" "telegram-stock-bot" "theqoo-cosmetics-bot")

send_alert() {
    local message="$1"
    if [[ -n "$ALERT_BOT_TOKEN" && -n "$ALERT_CHAT_ID" ]]; then
        curl -s -X POST "https://api.telegram.org/bot${ALERT_BOT_TOKEN}/sendMessage" \
            -d chat_id="$ALERT_CHAT_ID" \
            -d text="$message" \
            -d parse_mode="HTML" > /dev/null 2>&1
    fi
}

PROBLEMS=""

for CONTAINER in "${CONTAINERS[@]}"; do
    STATUS=$(docker inspect --format='{{.State.Status}}' "$CONTAINER" 2>/dev/null || echo "not_found")
    RESTARTS=$(docker inspect --format='{{.RestartCount}}' "$CONTAINER" 2>/dev/null || echo "0")

    if [[ "$STATUS" != "running" ]]; then
        PROBLEMS+="<b>${CONTAINER}</b>: ${STATUS}\n"
    elif [[ "$RESTARTS" -gt 5 ]]; then
        PROBLEMS+="<b>${CONTAINER}</b>: 재시작 ${RESTARTS}회\n"
    fi
done

if [[ -n "$PROBLEMS" ]]; then
    HOSTNAME=$(hostname)
    send_alert "⚠️ <b>[${HOSTNAME}] 봇 이상 감지</b>\n\n${PROBLEMS}\n$(date '+%Y-%m-%d %H:%M:%S')"
    echo "[$(date)] 이상 감지: $PROBLEMS"
else
    echo "[$(date)] 모든 컨테이너 정상"
fi
