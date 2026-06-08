"""
수학 입시 뉴스 수집기
- 소스: 구글 뉴스 RSS + 네이버 검색 API (뉴스·블로그·카페)
- 대상: 서울권 35개 4년제 대학 / 서울·경기 수도권
- NAVER_CLIENT_ID / NAVER_CLIENT_SECRET 환경변수 필요
"""

import json
import re
import os
import hashlib
import feedparser
import urllib.request
import urllib.parse
from datetime import datetime, timezone, timedelta
from pathlib import Path
from email.utils import parsedate_to_datetime

# ── 서울권 35개 대학 (입결 순) ────────────────────────────────
UNIV_TOP = ["서울대", "연세대", "고려대"]
UNIV_MID_HIGH = ["성균관대", "서강대", "한양대", "이화여대"]
UNIV_MID = ["중앙대", "경희대", "한국외대", "서울시립대",
            "건국대", "동국대", "홍익대", "숙명여대"]
UNIV_LOWER = ["광운대", "국민대", "단국대", "세종대", "숭실대",
              "아주대", "인하대", "가톨릭대", "서울과기대",
              "덕성여대", "동덕여대", "서울여대", "성신여대",
              "한국항공대", "상명대", "한성대", "명지대"]

ALL_UNIV = UNIV_TOP + UNIV_MID_HIGH + UNIV_MID + UNIV_LOWER  # 35개

# 상위권 / 중위권 묶음 (쿼리 효율화)
TIER_QUERIES = {
    "상위권": "·".join(UNIV_TOP + UNIV_MID_HIGH),        # 서울대·연세대·고려대·성균관대…
    "중위권": "·".join(UNIV_MID),
    "중하위권": "·".join(UNIV_LOWER[:10]),
}

# 지역 필터
REGION_KW = ["서울", "경기", "수도권", "강남", "분당", "수원", "목동", "노원"]

# ── 카테고리 정의 ─────────────────────────────────────────────
# 각 카테고리: 구글 뉴스 쿼리 + 네이버 블로그 쿼리 + 네이버 카페 쿼리
CATEGORIES = [
    {
        "id": "exam",
        "name": "평가원·모의고사",
        "emoji": "📝",
        "google": [
            "평가원 수학 모의고사 분석",
            "6월 9월 수능 수학 모의평가 서울",
            "수능 수학 1등급 컷 서울 경기",
        ],
        "naver_blog": [
            "수능 수학 6월 모의평가 분석 서울 경기",
            "평가원 수학 출제 경향 분석 2027",
            "수학 1등급 컷 모의고사 분석",
        ],
        "naver_cafe": [
            "수능 수학 6월 모의평가 컷 서울 경기",
            "평가원 수학 1등급 컷 분석",
        ],
    },
    {
        "id": "sushi",
        "name": "수시",
        "emoji": "🎓",
        "google": [
            "서울대 연세대 고려대 수시 수학 최저",
            "성균관대 한양대 서강대 수시 수학 논술",
            "중앙대 경희대 수시 수학 서울 경기",
        ],
        "naver_blog": [
            "서울권 대학 수시 수학 최저학력기준 2027",
            "강남 분당 수시 수학 논술 전략",
            "수도권 대학 수시 합격 수학 분석",
        ],
        "naver_cafe": [
            "서울대 연세대 고려대 수시 수학 최저 합격",
            "성균관대 한양대 서강대 수시 수학 논술",
        ],
    },
    {
        "id": "jeongshi",
        "name": "정시",
        "emoji": "📊",
        "google": [
            "서울대 연세대 고려대 정시 수학 반영비율",
            "성균관대 한양대 정시 수학 가중치 2027",
            "수도권 대학 정시 수학 컷 서울 경기",
        ],
        "naver_blog": [
            "서울권 35개 대학 정시 수학 반영비율 분석",
            "강남 분당 정시 수학 컨설팅 전략",
            "수능 수학 서울대 연세대 정시 컷라인",
        ],
        "naver_cafe": [
            "서울대 연세대 고려대 정시 수학 반영 컷",
            "인서울 정시 수학 가중치 분석",
        ],
    },
    {
        "id": "policy",
        "name": "교육과정·정책",
        "emoji": "📋",
        "google": [
            "2028 수능 개편 수학 서울 경기",
            "교육부 수학 교육과정 개편 발표",
            "서울 경기교육청 수학 정책",
        ],
        "naver_blog": [
            "2028 수능 수학 개편 서울 경기 영향",
            "수학 교육과정 개편 대입 전략",
        ],
        "naver_cafe": [
            "2028 수능 수학 개편 인서울 대학 영향",
        ],
    },
    {
        "id": "ebs",
        "name": "EBS 연계",
        "emoji": "📚",
        "google": [
            "EBS 수학 연계 수능 서울 경기",
            "수능 EBS 수학 연계율 분석",
        ],
        "naver_blog": [
            "EBS 수학 연계 서울권 대학 분석",
            "수능 EBS 수학 공부법 분당 강남",
        ],
        "naver_cafe": [
            "EBS 수학 수능 연계율 인서울 분석",
        ],
    },
    {
        "id": "schedule",
        "name": "입시 일정",
        "emoji": "📅",
        "google": [
            "서울권 대학 수시 원서접수 일정 2027",
            "서울대 연세대 고려대 합격자 발표",
            "수능 원서접수 수도권",
        ],
        "naver_blog": [
            "서울 경기 대입 일정 2027 정리",
            "수도권 대학 입시 일정 캘린더",
        ],
        "naver_cafe": [
            "인서울 대학 수시 정시 일정 2027",
        ],
    },
    {
        "id": "trend",
        "name": "수학 트렌드",
        "emoji": "🔥",
        "google": [
            "킬러문항 수학 서울 경기",
            "수학 사교육 정책 수도권",
            "서울 경기 수학 입시 트렌드 2027",
        ],
        "naver_blog": [
            "강남 분당 수학 입시 트렌드 분석",
            "수도권 수학 학습법 입시 컨설팅",
            "킬러문항 수학 서울권 대학 영향",
        ],
        "naver_cafe": [
            "수학 킬러문항 인서울 입시 영향",
        ],
    },
]

# ── 필터 ──────────────────────────────────────────────────────
BLACKLIST_RE = re.compile(
    r"이벤트|경품|쿠폰|할인|무료체험|다운로드|앱\s*(출시|소개|다운)|"
    r"구독\s*혜택|이용권|증정|광고|홍보|후원|협찬|PR\b|모집\s*중\s*$|"
    r"풍경|르포|현장\s*속|학원가\s*(풍경|모습|열기|분위기)|포토\b|\[포토\]|포토뉴스|"
    r"사교육\s*(열풍|과열)|치열한\s*입시|입시\s*전쟁|"
    # 수학 무관 노이즈
    r"영어\s*(과외|학원|노트|문법)|국어\s*과외|"
    r"선관위|기본권|이념|정치|부동산|청약|맛집|여행|육아|"
    r"뉴스\s*브리핑|간추린\s*뉴스|정책뉴스\d|칼럼.*IB|"
    r"전기박사|철물|AI\s*패권",
    re.IGNORECASE,
)
STOPWORDS = {"수학", "수능", "입시", "학생", "교육", "학교", "대학", "고등", "전국",
             "분석", "결과", "발표", "올해", "이번", "지난", "대비", "위한", "통해"}

KEEP_DAYS   = 3
MAX_PER_CAT = 150
DATE_FROM   = datetime(2026, 3, 1, tzinfo=timezone.utc)  # 26년 3월 이후만 보관
OUTPUT_FILE  = Path(__file__).parent / "news_data.json"
NOISE_FILE   = Path(__file__).parent / "noise_patterns.json"

# 사용자 노이즈 패턴 로드
def load_noise_patterns() -> tuple[set, list]:
    if not NOISE_FILE.exists():
        return set(), []
    try:
        data = json.loads(NOISE_FILE.read_text(encoding="utf-8"))
        sources = set(data.get("sources", []))
        keywords = data.get("title_keywords", [])
        print(f"노이즈 패턴 로드: 출처 {len(sources)}개 · 키워드 {len(keywords)}개")
        return sources, keywords
    except Exception as e:
        print(f"노이즈 패턴 로드 실패: {e}")
        return set(), []

NOISE_SOURCES, NOISE_KEYWORDS = load_noise_patterns()
NOISE_KW_RE = re.compile("|".join(re.escape(k) for k in NOISE_KEYWORDS), re.IGNORECASE) if NOISE_KEYWORDS else None

NAVER_ID  = os.environ.get("NAVER_CLIENT_ID", "")
NAVER_SEC = os.environ.get("NAVER_CLIENT_SECRET", "")

# ── 수집 함수 ─────────────────────────────────────────────────
def fetch_google_news(query: str, n=10) -> list[dict]:
    url = f"https://news.google.com/rss/search?q={urllib.parse.quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    feed = feedparser.parse(url)
    items = []
    for entry in feed.entries[:n]:
        try:
            pub = parsedate_to_datetime(entry.get("published", ""))
            pub_iso = pub.astimezone(timezone.utc).isoformat()
        except Exception:
            pub_iso = datetime.now(timezone.utc).isoformat()
        uid = hashlib.md5(entry.get("link", entry.get("title", "")).encode()).hexdigest()
        items.append({
            "id": uid, "title": entry.get("title", ""),
            "link": entry.get("link", "#"),
            "source": entry.get("source", {}).get("title", ""),
            "published": pub_iso, "type": "news",
        })
    return items


def fetch_naver(query: str, endpoint: str, n=10) -> list[dict]:
    if not NAVER_ID:
        return []
    url = (f"https://openapi.naver.com/v1/search/{endpoint}.json"
           f"?query={urllib.parse.quote(query)}&display={n}&sort=date")
    req = urllib.request.Request(url)
    req.add_header("X-Naver-Client-Id", NAVER_ID)
    req.add_header("X-Naver-Client-Secret", NAVER_SEC)
    try:
        with urllib.request.urlopen(req, timeout=8) as r:
            data = json.loads(r.read())
    except Exception as e:
        print(f"  네이버 API 오류 ({endpoint}): {e}")
        return []

    tag_re = re.compile(r"<[^>]+>")
    items = []
    for item in data.get("items", []):
        title = tag_re.sub("", item.get("title", ""))
        link  = item.get("link") or item.get("originallink", "#")
        pub_str = item.get("pubDate", "")
        try:
            pub = parsedate_to_datetime(pub_str).astimezone(timezone.utc).isoformat()
        except Exception:
            pub = datetime.now(timezone.utc).isoformat()
        source = ""
        if endpoint == "news":
            source = item.get("originallink", "").split("/")[2] if item.get("originallink") else ""
        elif endpoint == "blog":
            source = item.get("bloggername", "블로그")
        elif endpoint == "cafearticle":
            source = item.get("cafename", "카페")
        uid = hashlib.md5(link.encode()).hexdigest()
        items.append({
            "id": uid, "title": title, "link": link,
            "source": source, "published": pub, "type": endpoint,
        })
    return items


# ── 정제 ─────────────────────────────────────────────────────
def tokenize(t: str) -> frozenset:
    return frozenset(w for w in re.findall(r"[가-힣a-zA-Z0-9]{2,}", t) if w not in STOPWORDS)

def is_dup(tok: frozenset, seen: list, thr=0.55) -> bool:
    for s in seen:
        u = tok | s
        if u and len(tok & s) / len(u) >= thr:
            return True
    return False

def is_expired(pub: str) -> bool:
    try:
        d = datetime.fromisoformat(pub)
        if not d.tzinfo:
            d = d.replace(tzinfo=timezone.utc)
        if d < DATE_FROM:
            return True  # 26년 3월 이전은 항상 만료
        return (datetime.now(timezone.utc) - d).days >= KEEP_DAYS
    except Exception:
        return False

def is_user_noise(item: dict) -> bool:
    if item.get("source") in NOISE_SOURCES:
        return True
    if NOISE_KW_RE and NOISE_KW_RE.search(item.get("title", "")):
        return True
    return False

def is_too_old(pub: str) -> bool:
    try:
        d = datetime.fromisoformat(pub)
        if not d.tzinfo:
            d = d.replace(tzinfo=timezone.utc)
        return d < DATE_FROM
    except Exception:
        return False

def clean(items: list[dict]) -> list[dict]:
    seen_ids, seen_tok, out = set(), [], []
    for item in items:
        if item["id"] in seen_ids:
            continue
        if is_too_old(item["published"]):
            continue
        if BLACKLIST_RE.search(item["title"]):
            continue
        if is_user_noise(item):
            continue
        tok = tokenize(item["title"])
        if tok and is_dup(tok, seen_tok):
            continue
        seen_ids.add(item["id"])
        seen_tok.append(tok)
        out.append(item)
    return out


# ── 메인 ─────────────────────────────────────────────────────
def main():
    if not NAVER_ID:
        print("⚠  NAVER_CLIENT_ID 환경변수 없음 → 구글 뉴스만 수집")

    # 기존 데이터 로드
    existing: dict[str, dict] = {}
    if OUTPUT_FILE.exists():
        try:
            data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
            for cat in data.get("categories", []):
                existing[cat["id"]] = {i["id"]: i for i in cat.get("items", [])}
        except Exception:
            pass

    categories_out = []
    for cat in CATEGORIES:
        raw = []
        for q in cat.get("google", []):
            raw.extend(fetch_google_news(q))
        for q in cat.get("naver_blog", []):
            raw.extend(fetch_naver(q, "blog"))
        for q in cat.get("naver_cafe", []):
            raw.extend(fetch_naver(q, "cafearticle"))

        raw.sort(key=lambda x: x["published"], reverse=True)
        fresh = clean(raw)

        prev = existing.get(cat["id"], {})
        for item in fresh:
            item["is_new"] = item["id"] not in prev

        kept_old = {iid: item for iid, item in prev.items() if not is_expired(item["published"])}
        merged = {**{i["id"]: i for i in fresh}, **{iid: {**item, "is_new": False}
                  for iid, item in kept_old.items() if iid not in {i["id"] for i in fresh}}}
        result = sorted(merged.values(), key=lambda x: x["published"], reverse=True)[:MAX_PER_CAT]

        expired = len(prev) - len(kept_old)
        print(f"[{cat['name']}] 신규 {len(fresh)}건 · 누적 {len(result)}건 · 만료 {expired}건")

        categories_out.append({"id": cat["id"], "name": cat["name"],
                                "emoji": cat["emoji"], "items": result})

    OUTPUT_FILE.write_text(
        json.dumps({"updated_at": datetime.now(timezone.utc).isoformat(),
                    "categories": categories_out}, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n저장 완료 → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
