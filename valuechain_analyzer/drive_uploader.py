"""Google Drive 업로드

OAuth 2.0 데스크탑 앱 인증으로 Google Drive에 파일 업로드.
HTML은 Google Docs로 변환하여 NotebookLM 소스로 바로 사용 가능.
"""

import logging
import os
import stat
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload

from .config import GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def _get_credentials() -> Credentials:
    """OAuth 2.0 인증 (첫 실행 시 브라우저, 이후 token.json 재사용)."""
    creds = None
    if GOOGLE_TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(GOOGLE_TOKEN_PATH), _SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not GOOGLE_CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"Google OAuth credentials 파일이 없습니다: {GOOGLE_CREDENTIALS_PATH}\n"
                    f"Google Cloud Console에서 OAuth 클라이언트 ID를 생성하고 "
                    f"credentials.json을 다운로드하세요."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                str(GOOGLE_CREDENTIALS_PATH), _SCOPES
            )
            creds = flow.run_local_server(port=0)

        GOOGLE_TOKEN_PATH.write_text(creds.to_json())
        os.chmod(GOOGLE_TOKEN_PATH, stat.S_IRUSR | stat.S_IWUSR)  # 600
        logger.info("[Drive] OAuth 토큰 저장 완료")

    return creds


def _get_drive_service():
    """Google Drive API 서비스 생성."""
    creds = _get_credentials()
    return build("drive", "v3", credentials=creds)


def _create_folder(service, name: str, parent_id: str | None = None) -> str:
    """Drive 폴더 생성. 반환: 폴더 ID."""
    metadata = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [parent_id]

    folder = service.files().create(body=metadata, fields="id").execute()
    folder_id = folder["id"]
    logger.info(f"[Drive] 폴더 생성: {name} ({folder_id})")
    return folder_id


def _upload_file(
    service,
    local_path: str,
    folder_id: str,
    convert_to_docs: bool = False,
) -> str:
    """파일 업로드. 반환: 파일 ID.

    Args:
        convert_to_docs: True이면 Google Docs로 변환 업로드
    """
    path = Path(local_path)
    metadata = {
        "name": path.name,
        "parents": [folder_id],
    }

    # HTML → Google Docs 변환
    if convert_to_docs and path.suffix.lower() in (".html", ".htm"):
        metadata["mimeType"] = "application/vnd.google-apps.document"

    # MIME 타입 결정
    suffix = path.suffix.lower()
    mime_map = {
        ".html": "text/html",
        ".htm": "text/html",
        ".txt": "text/plain",
        ".pdf": "application/pdf",
    }
    upload_mime = mime_map.get(suffix, "application/octet-stream")

    media = MediaFileUpload(local_path, mimetype=upload_mime, resumable=True)
    file = service.files().create(
        body=metadata, media_body=media, fields="id"
    ).execute()
    file_id = file["id"]
    logger.info(f"[Drive] 업로드 완료: {path.name} ({file_id})")
    return file_id


# ── 공개 API ──

def upload_to_drive(
    target_ticker: str,
    file_paths: list[str],
) -> str | None:
    """파일들을 Google Drive에 업로드.

    폴더 구조:
        ValueChain - {TICKER}/
            {기업별 하위 폴더}/
                filing 및 transcript 파일들

    Args:
        target_ticker: 분석 대상 티커
        file_paths: 업로드할 로컬 파일 경로 목록

    Returns:
        루트 폴더 URL 또는 None (실패 시)
    """
    if not file_paths:
        logger.warning("[Drive] 업로드할 파일 없음")
        return None

    try:
        service = _get_drive_service()
    except Exception as e:
        logger.error(f"[Drive] 인증 실패: {e}")
        return None

    # 루트 폴더 생성
    root_folder_name = f"ValueChain - {target_ticker.upper()}"
    root_folder_id = _create_folder(service, root_folder_name)

    # 기업별 하위 폴더 생성 및 파일 업로드
    subfolder_cache: dict[str, str] = {}
    uploaded_count = 0

    for file_path in file_paths:
        path = Path(file_path)
        if not path.exists():
            logger.warning(f"[Drive] 파일 없음: {file_path}")
            continue

        # 하위 폴더 결정: _downloads/{TICKER}/sec/ → TICKER
        # 상위 2단계에서 티커 추출
        parts = path.parts
        company_ticker = None
        for i, part in enumerate(parts):
            if part == "_downloads" and i + 1 < len(parts):
                company_ticker = parts[i + 1]
                break

        if not company_ticker:
            company_ticker = target_ticker.upper()

        # 하위 폴더 생성
        if company_ticker not in subfolder_cache:
            subfolder_id = _create_folder(service, company_ticker, root_folder_id)
            subfolder_cache[company_ticker] = subfolder_id

        folder_id = subfolder_cache[company_ticker]

        # HTML은 Google Docs로 변환
        convert = path.suffix.lower() in (".html", ".htm")
        try:
            _upload_file(service, file_path, folder_id, convert_to_docs=convert)
            uploaded_count += 1
        except Exception as e:
            logger.error(f"[Drive] 업로드 실패 {path.name}: {e}")

    logger.info(f"[Drive] 총 {uploaded_count}/{len(file_paths)}개 파일 업로드 완료")

    # 폴더 URL 반환
    folder_url = f"https://drive.google.com/drive/folders/{root_folder_id}"
    return folder_url
