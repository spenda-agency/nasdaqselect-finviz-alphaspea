"""Google Drive にレポート Markdown ファイルをアップロードする。

既存の Service Account を再利用するため、スコープに drive を追加して認証する。
同名ファイルが既にあれば内容を更新（上書き）し、無ければ新規作成する。
"""
import json
import logging
import os
from io import BytesIO
from typing import Optional

logger = logging.getLogger(__name__)

DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive.file",
]

DEFAULT_FOLDER_ID = "1e0_XPuoi6vh4-tkd-V3pwW-oV5M7p9JE"


def _service():
    raw = os.environ.get("GOOGLE_CREDENTIALS_JSON", "")
    if not raw:
        raise RuntimeError("GOOGLE_CREDENTIALS_JSON 未設定")
    from google.oauth2.service_account import Credentials  # noqa: WPS433
    from googleapiclient.discovery import build  # noqa: WPS433
    creds = Credentials.from_service_account_info(json.loads(raw), scopes=DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def _find_file(service, folder_id: str, name: str) -> Optional[str]:
    """フォルダ内の同名ファイルを検索し、見つかれば fileId を返す。"""
    safe_name = name.replace("'", "\\'")
    q = f"name = '{safe_name}' and '{folder_id}' in parents and trashed = false"
    try:
        resp = service.files().list(
            q=q, fields="files(id,name)", pageSize=1,
            supportsAllDrives=True, includeItemsFromAllDrives=True,
        ).execute()
        files = resp.get("files", [])
        return files[0]["id"] if files else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("既存ファイル検索失敗: %s", exc)
        return None


def upload_markdown(filename: str, content: str, folder_id: Optional[str] = None) -> Optional[str]:
    """Markdown 文字列を Drive にアップロードし、webViewLink を返す。"""
    folder_id = folder_id or os.environ.get("DRIVE_FOLDER_ID") or DEFAULT_FOLDER_ID
    try:
        from googleapiclient.http import MediaIoBaseUpload  # noqa: WPS433
        service = _service()
    except Exception as exc:  # noqa: BLE001
        logger.error("Drive サービス初期化失敗: %s", exc)
        return None

    media = MediaIoBaseUpload(
        BytesIO(content.encode("utf-8")),
        mimetype="text/markdown",
        resumable=False,
    )
    existing_id = _find_file(service, folder_id, filename)
    try:
        if existing_id:
            f = service.files().update(
                fileId=existing_id, media_body=media,
                fields="id,webViewLink", supportsAllDrives=True,
            ).execute()
            logger.info("Drive 更新: %s (id=%s)", filename, f.get("id"))
        else:
            metadata = {"name": filename, "parents": [folder_id]}
            f = service.files().create(
                body=metadata, media_body=media,
                fields="id,webViewLink", supportsAllDrives=True,
            ).execute()
            logger.info("Drive 新規作成: %s (id=%s)", filename, f.get("id"))
        return f.get("webViewLink")
    except Exception as exc:  # noqa: BLE001
        logger.error("Drive アップロード失敗 (%s): %s", filename, exc)
        return None
