#!/bin/bash
# DB 백업 스크립트
# cron 설정: 0 3 * * * /home/ubuntu/telegram-bots/scripts/backup.sh

set -euo pipefail

BACKUP_DIR="/home/ubuntu/telegram-bots/backups"
DATE=$(date +%Y%m%d_%H%M%S)
KEEP_DAYS=7

mkdir -p "$BACKUP_DIR"

# Docker 볼륨에서 DB 파일 복사
echo "[$(date)] 백업 시작"

for CONTAINER in investment-analyst telegram-stock-bot theqoo-cosmetics-bot; do
    if docker ps --format '{{.Names}}' | grep -q "^${CONTAINER}$"; then
        docker cp "${CONTAINER}:/app/data/" "$BACKUP_DIR/${CONTAINER}_${DATE}/" 2>/dev/null && \
            echo "  ${CONTAINER}: 백업 완료" || \
            echo "  ${CONTAINER}: /app/data 없음 (건너뜀)"
    else
        echo "  ${CONTAINER}: 컨테이너 미실행 (건너뜀)"
    fi
done

# 오래된 백업 삭제
find "$BACKUP_DIR" -maxdepth 1 -mindepth 1 -type d -mtime +${KEEP_DAYS} -exec rm -rf {} \;
echo "[$(date)] 백업 완료 (${KEEP_DAYS}일 이상 된 백업 삭제)"
