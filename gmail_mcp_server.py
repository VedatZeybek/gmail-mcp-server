#!/usr/bin/env python
import os
import base64
import mimetypes
from typing import List, Optional, Literal, Dict, Any

from mcp.server.fastmcp import FastMCP

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders

# -----------------------------
# MCP App
# -----------------------------
app = FastMCP(
    name="gmail-mcp-server",
    host="0.0.0.0",
    port=3001,
    streamable_http_path="/mcp",  # Postman buraya bağlanacak
)

# -----------------------------
# Gmail OAuth / Service
# -----------------------------
SCOPES = [
    "https://www.googleapis.com/auth/gmail.send",
]

TOKEN_FILE = os.getenv("GMAIL_TOKEN_FILE", "token.json")
CREDENTIALS_FILE = os.getenv("GMAIL_CREDENTIALS_FILE", "credentials.json")

def get_gmail_service():
    """
    Basit local dev OAuth:
    - credentials.json (Google Cloud OAuth Client)
    - token.json (ilk login sonrası oluşur)
    """
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not os.path.exists(CREDENTIALS_FILE):
                raise RuntimeError(
                    f"credentials file not found: {CREDENTIALS_FILE}. "
                    f"Set GMAIL_CREDENTIALS_FILE or place credentials.json next to server."
                )
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, "w", encoding="utf-8") as f:
            f.write(creds.to_json())

    return build("gmail", "v1", credentials=creds)

# -----------------------------
# Helpers: attachment reading
# -----------------------------
def _safe_read_file(path: str, base_dir: Optional[str]) -> bytes:
    """
    Güvenlik: base_dir verilirse sadece base_dir altında okur.
    """
    p = os.path.abspath(path)

    if base_dir:
        b = os.path.abspath(base_dir)
        if not (p == b or p.startswith(b + os.sep)):
            raise ValueError(f"Attachment path not allowed (outside base dir): {p}")

    # Boyut limiti (default 20MB)
    max_mb = int(os.getenv("MAX_ATTACHMENT_MB", "20"))
    size = os.path.getsize(p)
    if size > max_mb * 1024 * 1024:
        raise ValueError(f"Attachment too large: {size} bytes (max {max_mb}MB)")

    with open(p, "rb") as f:
        return f.read()

def _resolve_attachment_path(path: str) -> str:
    """
    path relative gelirse ATTACHMENTS_BASE_DIR ile birleştir.
    Default base dir: /shared
    """
    base_dir = os.getenv("ATTACHMENTS_BASE_DIR", "/shared")

    # relative path ise base_dir altına koy
    if path and not os.path.isabs(path):
        path = os.path.join(base_dir, path)

    return path

# -----------------------------
# Helpers: email building
# -----------------------------
def build_raw_email(
    to: str,
    subject: str,
    body: str,
    body_format: Literal["plain", "html"] = "plain",
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> str:
    attachments = attachments or []

    msg = MIMEMultipart()
    msg["To"] = to
    msg["Subject"] = subject

    # body
    msg.attach(MIMEText(body, "html" if body_format == "html" else "plain", "utf-8"))

    for att in attachments:
        filename = att.get("filename")
        mime_type = att.get("mime_type")
        content_b64 = att.get("content_base64")
        path = att.get("path")

        if content_b64 and path:
            raise ValueError("attachment: provide either content_base64 OR path, not both")

        # 1) path varsa oku (volume)
        if path:
            path = _resolve_attachment_path(path)

            # filename yoksa path'ten türet
            if not filename:
                filename = os.path.basename(path)

            # mime_type yoksa filename'den tahmin et
            if not mime_type:
                guessed, _ = mimetypes.guess_type(filename)
                mime_type = guessed or "application/octet-stream"

            base_dir = os.getenv("ATTACHMENTS_BASE_DIR", "/shared")
            data = _safe_read_file(path, base_dir)

        # 2) base64 varsa decode et
        elif content_b64:
            if not filename:
                raise ValueError("attachment with content_base64 requires filename")

            if not mime_type:
                guessed, _ = mimetypes.guess_type(filename)
                mime_type = guessed or "application/octet-stream"

            data = base64.b64decode(content_b64)

        else:
            raise ValueError("attachment requires content_base64 or path")

        maintype, subtype = (mime_type.split("/", 1) + ["octet-stream"])[:2]
        part = MIMEBase(maintype, subtype)
        part.set_payload(data)
        encoders.encode_base64(part)
        part.add_header("Content-Disposition", f'attachment; filename="{filename}"')
        msg.attach(part)

    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode("utf-8")
    return raw

# -----------------------------
# MCP Tool (single tool)
# -----------------------------
@app.tool()
def send_gmail(
    to: str,
    subject: str,
    body: str,
    body_format: Literal["plain", "html"] = "plain",
    attachments: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Send an email with optional attachments.

    attachments item supports:
    - { "filename": "...", "mime_type": "...", "content_base64": "..." }
    OR (volume/path)
    - { "path": "/shared/output/file.pptx" }
    - { "path": "output/file.pptx" }  # relative => /shared/output/file.pptx (default)
    """
    service = get_gmail_service()
    raw = build_raw_email(
        to=to,
        subject=subject,
        body=body,
        body_format=body_format,
        attachments=attachments or [],
    )

    sent = service.users().messages().send(userId="me", body={"raw": raw}).execute()
    return {"ok": True, "message_id": sent.get("id")}

def main(transport: str = "http", port: int = 3001):
    app.settings.host = "0.0.0.0"
    app.settings.port = port

    if transport == "http":
        app.run(transport="streamable-http")
    elif transport == "sse":
        app.run(transport="sse")
    else:
        app.run(transport="stdio")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("-t", "--transport", default="http", choices=["http", "sse", "stdio"])
    parser.add_argument("-p", "--port", type=int, default=3001)
    args = parser.parse_args()
    main(args.transport, args.port)
