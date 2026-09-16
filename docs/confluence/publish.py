#!/usr/bin/env python3
"""Publish (create or update) the Confluence guide page from the storage
XHTML next to this script, and attach the videos from docs/videos/.

Pure stdlib — no venv needed. Auth via env:

  CONFLUENCE_BASE   e.g. https://yoursite.atlassian.net/wiki
  CONFLUENCE_USER   your Atlassian account email
  CONFLUENCE_TOKEN  an API token (id.atlassian.com → Security → API tokens)

Usage:
  python3 docs/confluence/publish.py --space TEAM --parent-id 123456 \
      [--title "start_stack command builder — User Guide"] [--no-videos]

Idempotent: a page with the same title in the space is updated in place
(version bumped); otherwise a new child of --parent-id is created.
Attachments with the same file name are replaced.
"""

import argparse
import base64
import json
import mimetypes
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import uuid

HERE = os.path.dirname(os.path.abspath(__file__))
VIDEOS_ROOT = os.path.join(os.path.dirname(HERE), "videos")

# Per-language: the storage body, where its videos live, the attachment
# name prefix (so en and ja videos can share one page's attachment space
# without clobbering), and the default page title.
LANGS = {
    "en": {
        "body": os.path.join(HERE, "start-stack-app-guide.storage.xhtml"),
        "videos": VIDEOS_ROOT,
        "prefix": "",
        "title": "start_stack command builder — User Guide",
    },
    "ja": {
        "body": os.path.join(HERE, "start-stack-app-guide.ja.storage.xhtml"),
        "videos": os.path.join(VIDEOS_ROOT, "ja"),
        "prefix": "ja-",
        "title": "start_stack コマンドビルダー — ユーザーガイド",
    },
}


def env(name):
    value = os.environ.get(name, "").strip()
    if not value:
        sys.exit(f"{name} is not set — see the docstring for the three env vars.")
    return value


class Confluence:
    def __init__(self, base, user, token):
        self.base = base.rstrip("/")
        self.auth = base64.b64encode(f"{user}:{token}".encode()).decode()

    def request(self, method, path, body=None, headers=None, raw=None):
        url = self.base + path
        data = raw if raw is not None else (json.dumps(body).encode() if body is not None else None)
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Authorization", f"Basic {self.auth}")
        req.add_header("Accept", "application/json")
        if raw is None and body is not None:
            req.add_header("Content-Type", "application/json")
        for key, value in (headers or {}).items():
            req.add_header(key, value)
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = resp.read().decode()
                return json.loads(text) if text else {}
        except urllib.error.HTTPError as err:
            sys.exit(f"{method} {path} → HTTP {err.code}: {err.read().decode()[:600]}")

    def get_page(self, page_id):
        page = self.request("GET", f"/rest/api/content/{page_id}?expand=version,body.storage")
        return page

    def find_page(self, space, title):
        query = urllib.parse.urlencode({"spaceKey": space, "title": title, "expand": "version"})
        result = self.request("GET", f"/rest/api/content?{query}")
        return (result.get("results") or [None])[0]

    def create_page(self, space, parent_id, title, body):
        payload = {
            "type": "page",
            "title": title,
            "space": {"key": space},
            "body": {"storage": {"value": body, "representation": "storage"}},
        }
        if parent_id:
            payload["ancestors"] = [{"id": str(parent_id)}]
        return self.request("POST", "/rest/api/content", payload)

    def update_page(self, page, title, body):
        payload = {
            "id": page["id"],
            "type": "page",
            "title": title,
            "version": {"number": page["version"]["number"] + 1},
            "body": {"storage": {"value": body, "representation": "storage"}},
        }
        return self.request("PUT", f"/rest/api/content/{page['id']}", payload)

    def existing_attachment(self, page_id, filename):
        query = urllib.parse.urlencode({"filename": filename})
        result = self.request("GET", f"/rest/api/content/{page_id}/child/attachment?{query}")
        return (result.get("results") or [None])[0]

    def upload(self, page_id, path, filename=None):
        filename = filename or os.path.basename(path)
        existing = self.existing_attachment(page_id, filename)
        endpoint = (
            f"/rest/api/content/{page_id}/child/attachment/{existing['id']}/data"
            if existing else f"/rest/api/content/{page_id}/child/attachment"
        )
        boundary = uuid.uuid4().hex
        ctype = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        with open(path, "rb") as f:
            content = f.read()
        parts = [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'.encode(),
            f"Content-Type: {ctype}\r\n\r\n".encode(),
            content, b"\r\n",
            f"--{boundary}\r\n".encode(),
            b'Content-Disposition: form-data; name="minorEdit"\r\n\r\ntrue\r\n',
            f"--{boundary}--\r\n".encode(),
        ]
        self.request(
            "POST", endpoint, raw=b"".join(parts),
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}",
                     "X-Atlassian-Token": "nocheck"},
        )
        return "replaced" if existing else "uploaded"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--space", help="space key, e.g. TEAM (not needed with --page-id)")
    parser.add_argument("--parent-id", help="parent page id for a newly created page")
    parser.add_argument("--page-id", help="update this exact page instead of matching by title")
    parser.add_argument("--append", action="store_true",
                        help="with --page-id: keep the page's existing content and add the guide below it")
    parser.add_argument("--lang", choices=sorted(LANGS), default="en",
                        help="which guide to publish (body, videos, default title)")
    parser.add_argument("--title", help="page title (default: the language's guide title)")
    parser.add_argument("--no-videos", action="store_true", help="skip attaching the videos")
    args = parser.parse_args()
    lang = LANGS[args.lang]
    args.title = args.title or lang["title"]
    BODY_PATH, VIDEOS_DIR = lang["body"], lang["videos"]
    if not args.page_id and not args.space:
        parser.error("--page-id or --space is required")

    client = Confluence(env("CONFLUENCE_BASE"), env("CONFLUENCE_USER"), env("CONFLUENCE_TOKEN"))
    with open(BODY_PATH, encoding="utf-8") as f:
        body = f.read()

    if args.page_id:
        page = client.get_page(args.page_id)
        if args.append:
            existing = (page.get("body", {}).get("storage", {}).get("value") or "")
            if existing.strip():
                body = existing + "\n<hr/>\n" + body
        title = page["title"]
        page = client.update_page(page, title, body)
        print(f"updated page {page['id']} \"{title}\" (v{page['version']['number']})")
    else:
        page = client.find_page(args.space, args.title)
        if page:
            page = client.update_page(page, args.title, body)
            print(f"updated page {page['id']} (v{page['version']['number']})")
        else:
            page = client.create_page(args.space, args.parent_id, args.title, body)
            print(f"created page {page['id']}")

    if not args.no_videos:
        for name in sorted(os.listdir(VIDEOS_DIR)):
            if name.endswith(".mp4"):
                attached_as = lang["prefix"] + name
                status = client.upload(page["id"], os.path.join(VIDEOS_DIR, name), attached_as)
                print(f"  {status} {attached_as}")

    link = page.get("_links", {})
    print(link.get("base", client.base) + link.get("webui", ""))


if __name__ == "__main__":
    main()
