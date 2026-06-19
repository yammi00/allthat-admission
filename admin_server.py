"""
올댓 입시정보 어드민 API 서버 (포트 3457)
- GET  /api/articles       : 전체 기사 목록
- DELETE /api/articles/:id : 기사 삭제
- POST /api/noise/source   : 출처 차단 추가
- POST /api/noise/keyword  : 키워드 차단 추가
- POST /api/push           : GitHub push
"""

import json
import subprocess
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import urlparse, parse_qs

BASE = Path(__file__).parent
NEWS_FILE   = BASE / "news_data.json"
NOISE_FILE  = BASE / "noise_patterns.json"
ADMIN_FILE  = BASE / "admin.html"

HEADERS_CORS = {
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Methods": "GET, POST, DELETE, OPTIONS",
    "Access-Control-Allow-Headers": "Content-Type",
    "Content-Type": "application/json; charset=utf-8",
}


def load_news():
    return json.loads(NEWS_FILE.read_text(encoding="utf-8"))

def save_news(data):
    NEWS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def load_noise():
    return json.loads(NOISE_FILE.read_text(encoding="utf-8"))

def save_noise(data):
    NOISE_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


class AdminHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[admin] {args[0]} {args[1]}")

    def send_json(self, code, obj):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        for k, v in HEADERS_CORS.items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        for k, v in HEADERS_CORS.items():
            self.send_header(k, v)
        self.end_headers()

    def do_GET(self):
        path = urlparse(self.path).path

        # admin.html 서빙
        if path in ("/", "/admin", "/admin.html"):
            html = ADMIN_FILE.read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)
            return

        if path == "/api/articles":
            data = load_news()
            articles = []
            for cat in data.get("categories", []):
                for item in cat.get("items", []):
                    articles.append({
                        "id": item["id"],
                        "title": item["title"],
                        "source": item.get("source", ""),
                        "published": item.get("published", ""),
                        "link": item.get("link", "#"),
                        "type": item.get("type", "news"),
                        "cat_id": cat["id"],
                        "cat_name": cat["name"],
                    })
            articles.sort(key=lambda x: x["published"], reverse=True)
            self.send_json(200, {"articles": articles, "total": len(articles)})
            return

        if path == "/api/noise":
            self.send_json(200, load_noise())
            return

        self.send_json(404, {"error": "not found"})

    def do_DELETE(self):
        path = urlparse(self.path).path
        parts = path.split("/")

        # DELETE /api/articles/<id>
        if len(parts) == 4 and parts[1] == "api" and parts[2] == "articles":
            art_id = parts[3]
            data = load_news()
            removed = 0
            for cat in data.get("categories", []):
                before = len(cat["items"])
                cat["items"] = [i for i in cat["items"] if i["id"] != art_id]
                removed += before - len(cat["items"])
            save_news(data)
            self.send_json(200, {"deleted": removed, "id": art_id})
            return

        self.send_json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length)) if length else {}

        # POST /api/noise/source  {"value": "출처명"}
        if path == "/api/noise/source":
            val = body.get("value", "").strip()
            if not val:
                self.send_json(400, {"error": "value required"})
                return
            noise = load_noise()
            if val not in noise.get("sources", []):
                noise.setdefault("sources", []).append(val)
                save_noise(noise)
            self.send_json(200, {"added": val})
            return

        # POST /api/noise/keyword  {"value": "키워드"}
        if path == "/api/noise/keyword":
            val = body.get("value", "").strip()
            if not val:
                self.send_json(400, {"error": "value required"})
                return
            noise = load_noise()
            if val not in noise.get("keywords", []):
                noise.setdefault("keywords", []).append(val)
                save_noise(noise)
            self.send_json(200, {"added": val})
            return

        # POST /api/articles/<id>/move  {"cat_id": "exam"}
        if len(path.split("/")) == 5 and path.split("/")[2] == "articles" and path.split("/")[4] == "move":
            art_id = path.split("/")[3]
            new_cat = body.get("cat_id", "").strip()
            data = load_news()
            item = None
            for cat in data.get("categories", []):
                for i in cat["items"]:
                    if i["id"] == art_id:
                        item = i
                        cat["items"] = [x for x in cat["items"] if x["id"] != art_id]
                        break
                if item:
                    break
            if not item:
                self.send_json(404, {"error": "article not found"})
                return
            target = next((c for c in data["categories"] if c["id"] == new_cat), None)
            if not target:
                self.send_json(400, {"error": "category not found"})
                return
            target["items"].insert(0, item)
            save_news(data)
            self.send_json(200, {"moved": art_id, "to": new_cat})
            return

        # POST /api/scrape  → scraper.py 실행
        if path == "/api/scrape":
            try:
                proc = subprocess.Popen(
                    ["python3", "scraper.py"],
                    cwd=str(BASE), stdout=subprocess.PIPE, stderr=subprocess.STDOUT
                )
                self.send_json(200, {"status": "started", "pid": proc.pid})
            except Exception as e:
                self.send_json(500, {"error": str(e)})
            return

        # POST /api/noise/source/delete  {"value": "출처명"}
        if path == "/api/noise/source/delete":
            val = body.get("value", "").strip()
            noise = load_noise()
            noise["sources"] = [s for s in noise.get("sources", []) if s != val]
            save_noise(noise)
            self.send_json(200, {"removed": val})
            return

        # POST /api/noise/keyword/delete  {"value": "키워드"}
        if path == "/api/noise/keyword/delete":
            val = body.get("value", "").strip()
            noise = load_noise()
            noise["title_keywords"] = [k for k in noise.get("title_keywords", []) if k != val]
            save_noise(noise)
            self.send_json(200, {"removed": val})
            return

        # POST /api/push  → git add + commit + push
        if path == "/api/push":
            try:
                subprocess.run(
                    ["git", "add", "news_data.json", "noise_patterns.json"],
                    cwd=str(BASE), check=True, capture_output=True
                )
                result = subprocess.run(
                    ["git", "diff", "--cached", "--quiet"],
                    cwd=str(BASE), capture_output=True
                )
                if result.returncode != 0:
                    subprocess.run(
                        ["git", "commit", "-m", "어드민: 기사/필터 수동 수정"],
                        cwd=str(BASE), check=True, capture_output=True
                    )
                    subprocess.run(
                        ["git", "push"],
                        cwd=str(BASE), check=True, capture_output=True
                    )
                    self.send_json(200, {"status": "pushed"})
                else:
                    self.send_json(200, {"status": "no_changes"})
            except subprocess.CalledProcessError as e:
                self.send_json(500, {"error": e.stderr.decode()})
            return

        self.send_json(404, {"error": "not found"})


if __name__ == "__main__":
    server = HTTPServer(("localhost", 3457), AdminHandler)
    print("🔧 어드민 서버 시작: http://localhost:3457/admin")
    print("   Ctrl+C로 종료")
    server.serve_forever()
