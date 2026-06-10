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
            "3월 모의고사 수학 등급컷 분석",
            "6월 모의평가 수학 등급컷 분석",
            "9월 모의평가 수학 등급컷 분석",
            "평가원 수학 출제 경향 분석",
            "수능 수학 1등급 컷 서울 경기",
            "EBS 수학 연계 수능 서울 경기",
            "수능 EBS 수학 연계율 분석",
            "EBS 수학 킬러 준킬러 연계",
        ],
        "naver_blog": [
            "3월 모의고사 수학 풀이 분석",
            "6월 모의평가 수학 풀이 분석",
            "9월 모의평가 수학 풀이 분석",
            "평가원 수학 킬러문항 해설",
            "수능 수학 출제 경향 서울 경기",
            "EBS 수학 연계 수능 풀이 분석",
            "수능 EBS 수학 연계 킬러문항 분석",
        ],
    },
    {
        "id": "sushi",
        "name": "수시",
        "emoji": "🎓",
        "google": [
            "서울대 연세대 고려대 수시 수학 최저",
            "성균관대 한양대 서강대 수시 수학 논술",
            "중앙대 경희대 수시 수학 논술 서울",
            "인서울 수시 수학 최저학력기준 2027",
            "서울권 대학 수학 논술 전형 분석",
        ],
        "naver_blog": [
            "서울권 대학 수시 수학 최저학력기준 2027",
            "강남 분당 수시 수학 논술 전략",
            "인서울 수시 수학 논술 기출 분석",
            "서울대 연세대 수시 수학 최저 전략",
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
            "인서울 정시 수학 반영비율 유불리",
            "서울권 정시 수학 가중치 비교 분석",
        ],
        "naver_blog": [
            "서울권 35개 대학 정시 수학 반영비율 분석",
            "강남 분당 정시 수학 컨설팅 전략",
            "인서울 정시 수학 가중치 유불리 분석",
            "서울대 연세대 정시 수학 반영 전략",
        ],
    },
    {
        "id": "policy",
        "name": "교육과정·정책",
        "emoji": "📋",
        # 공식 사이트는 main()에서 fetch_suneung() + fetch_korea_kr()로 별도 수집
        "google": [
            "site:moe.go.kr 수능 수학",
            "site:suneung.re.kr 수학 모의평가",
            "교육부 수능 수학 교육과정 개편 발표",
            "2028 수능 수학 개편 교육부",
        ],
        "naver_blog": [],
        "naver_cafe": [],
        "official": True,   # 공식 사이트 수집 플래그
    },
    {
        "id": "yaksuljul",
        "name": "수리·약술 논술",
        "emoji": "✏️",
        "google": [
            "약술형 논술 수학 2027 대학",
            "국민대 가천대 약술 논술 수학 전형",
            "상명대 삼육대 서경대 약술 논술 수학",
            "약술형 논술 수1 수2 EBS 출제 분석",
            "수리논술 수학 2027 서울 경기 대학",
            "연세대 성균관대 수리논술 수학 기출",
            "인서울 수리논술 준비 전략 수학",
        ],
        "naver_blog": [
            "약술형 논술 수학 준비 전략 2027",
            "약술형 논술 대학별 기출 분석 수학",
            "수리논술 수학 기출 분석 서울 경기",
            "수리논술 준비 방법 수학 인서울",
            "수능최저 없는 약술 논술 수학 전형",
            "국민대 가천대 약술 논술 수학 기출",
        ],
    },
    {
        "id": "schedule",
        "name": "입시 일정",
        "emoji": "📅",
        "google": [
            "서울권 대학 수시 원서접수 일정 2027",
            "서울대 연세대 고려대 합격자 발표",
            "수능 원서접수 수도권 일정",
            "수학 논술 고사 일정 서울 경기",
        ],
        "naver_blog": [
            "서울 경기 대입 수학 관련 일정 2027",
            "수도권 대학 수학 논술 일정 정리",
        ],
    },
]

# ── 필터 ──────────────────────────────────────────────────────
BLACKLIST_RE = re.compile(
    r"이벤트|경품|쿠폰|할인|무료체험|다운로드|앱\s*(출시|소개|다운)|"
    r"구독\s*혜택|이용권|증정|광고|홍보|후원|협찬|PR\b|모집\s*중\s*$|"
    r"풍경|르포|현장\s*속|학원가\s*(풍경|모습|열기|분위기)|포토\b|\[포토\]|포토뉴스|"
    r"사교육\s*(열풍|과열)|치열한\s*입시|입시\s*전쟁|"
    r"영어\s*(과외|학원|노트|문법)|국어\s*과외|"
    r"선관위|기본권|이념|정치|부동산|청약|맛집|여행|육아|"
    r"뉴스\s*브리핑|간추린\s*뉴스|정책뉴스\d|칼럼.*IB|"
    r"전기박사|철물|AI\s*패권",
    re.IGNORECASE,
)

# 블로그·카페 전용 추가 광고 필터 (뉴스에는 적용 안 함)
BLOG_AD_RE = re.compile(
    r"수강\s*신청|수강료|등록금|개강\s*안내|OT\s*안내|무료\s*상담|상담\s*신청|"
    r"선착순|마감\s*임박|한정\s*모집|[0-9]+만\s*원|원/월|월\s*[0-9]+만|"
    r"카카오톡\s*문의|네이버\s*예약|전화\s*주세요|바로\s*신청|링크\s*클릭|"
    r"블로그\s*이웃|공감\s*눌러|구독\s*부탁|홍보|체험단|리뷰어|제품\s*제공|"
    r"협찬\s*받|소정의\s*원고|원고료",
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

def is_expired(pub: str, no_expire: bool = False) -> bool:
    if no_expire:
        return False  # 정책 기사는 영구 보관
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

def tag_grade(cat_id: str) -> str:
    """카테고리 기반 학년 태깅"""
    if cat_id in ('exam', 'sushi', 'jeongshi', 'ebs'):
        return '3'
    return 'all'  # policy, schedule, trend → 전체

def clean(items: list[dict], cat_id: str = '') -> list[dict]:
    seen_ids, seen_tok, out = set(), [], []
    for item in items:
        if item["id"] in seen_ids:
            continue
        if is_too_old(item["published"]):
            continue
        if BLACKLIST_RE.search(item["title"]):
            continue
        # 블로그·카페는 광고 추가 필터 적용
        if item.get("type") in ("blog", "cafearticle") and BLOG_AD_RE.search(item["title"]):
            continue
        if is_user_noise(item):
            continue
        tok = tokenize(item["title"])
        if tok and is_dup(tok, seen_tok):
            continue
        # 제목 최대 60자로 자르기 (공식 사이트 긴 설명문 방지)
        item["title"] = item["title"][:80].strip()
        item["grade"] = tag_grade(cat_id)
        seen_ids.add(item["id"])
        seen_tok.append(tok)
        out.append(item)
    return out


# ── 공식 사이트 직접 수집 ──────────────────────────────────────
def fetch_suneung() -> list[dict]:
    """한국교육과정평가원 공지사항 직접 수집"""
    url = "https://www.suneung.re.kr/boardCnts/list.do?boardID=1500229&m=0301&s=suneung"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  평가원 수집 오류: {e}")
        return []

    items = []
    # td 안의 링크 전체 추출
    rows = re.findall(
        r'<a[^>]+href="(/boardCnts/view\.do\?boardID=1500229[^"]+)"[^>]*>\s*(.*?)\s*</a>',
        html, re.DOTALL
    )
    for href, title in rows[:20]:
        title = re.sub(r'<[^>]+>', '', title).strip()
        title = re.sub(r'\s+', ' ', title).strip()
        if len(title) < 5 or title.startswith('-') or 'suneung.re.kr' in title:
            continue
        full_url = "https://www.suneung.re.kr" + href
        uid = hashlib.md5(full_url.encode()).hexdigest()
        items.append({
            "id": uid, "title": title, "link": full_url,
            "source": "한국교육과정평가원",
            "published": datetime.now(timezone.utc).isoformat(),
            "type": "official", "no_expire": True,
        })
    return items


def fetch_korea_kr(keyword: str, n=10) -> list[dict]:
    """정책브리핑 키워드 검색"""
    url = f"https://www.korea.kr/briefing/pressReleaseList.do?srchWord={urllib.parse.quote(keyword)}"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  정책브리핑 수집 오류: {e}")
        return []

    items = []
    links = re.findall(
        r'<a[^>]+href="(/briefing/pressReleaseView\.do\?newsId=(\d+)[^"]*)"[^>]*>(.*?)</a>',
        html, re.DOTALL
    )
    # 수능·대입·고등부 관련 키워드 (이 중 하나 있어야 통과)
    POLICY_KEEP_RE = re.compile(
        r'수능|대입|대학수학능력|수시|정시|교육과정|고등학교|고등부|'
        r'학력평가|모의평가|출제|입시|수학능력|EBS|내신|논술|수학 교육|'
        r'사교육|킬러|입학전형|대학입학', re.IGNORECASE
    )
    # 완전히 무관한 내용 차단
    POLICY_BLOCK_RE = re.compile(
        r'베트남|TOPIK|한국어능력|직업훈련|내일배움|발달장애|인공지능\s*앱|'
        r'AI\s*앱|크루즈|청소년증|해수부|농식품|청렴|캠페인|포럼|간담회|'
        r'초중등\s*이외|특수학교(?!.*수능)|유아|어린이|돌봄', re.IGNORECASE
    )

    seen_nid = set()   # newsId 기준 중복 방지
    seen_title = set() # 제목 기준 중복 방지
    for href, nid, title in links:
        title = re.sub(r'<[^>]+>', '', title).strip()
        title = re.sub(r'\s+', ' ', title).strip()
        # 첫 문장만 (마침표·줄바꿈 기준 자르기)
        title = re.split(r'[\.…\n□]', title)[0].strip()
        title = title[:60].strip()  # 최대 60자
        if len(title) < 5:
            continue
        # newsId 또는 제목 중복 제거
        title_key = re.sub(r'\s+', '', title)  # 공백 제거 후 비교
        if nid in seen_nid or title_key in seen_title:
            continue
        # 관련 없는 정책 기사 차단
        if not POLICY_KEEP_RE.search(title):
            continue
        if POLICY_BLOCK_RE.search(title):
            continue
        seen_nid.add(nid)
        seen_title.add(title_key)
        full_url = f"https://www.korea.kr/briefing/pressReleaseView.do?newsId={nid}"
        uid = hashlib.md5(nid.encode()).hexdigest()  # newsId 기준 uid (안정적)
        items.append({
            "id": uid, "title": title, "link": full_url,
            "source": "정책브리핑(교육부)",
            "published": datetime.now(timezone.utc).isoformat(),
            "type": "official", "no_expire": True,
        })
        if len(items) >= n:
            break
    return items


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

        # 공식 사이트 수집 (정책 카테고리만)
        if cat.get("official"):
            print(f"  [{cat['name']}] 공식 사이트 수집 중...")
            raw.extend(fetch_suneung())
            raw.extend(fetch_korea_kr("수능 수학"))
            raw.extend(fetch_korea_kr("교육과정 수학"))
            raw.extend(fetch_korea_kr("대입 수학"))

        for q in cat.get("google", []):
            raw.extend(fetch_google_news(q))
        for q in cat.get("naver_blog", []):
            raw.extend(fetch_naver(q, "blog"))

        raw.sort(key=lambda x: x["published"], reverse=True)
        fresh = clean(raw, cat_id=cat["id"])

        prev = existing.get(cat["id"], {})
        for item in fresh:
            item["is_new"] = item["id"] not in prev

        # no_expire 항목은 만료 안 됨 (정책 기사 영구 보관)
        _BAD_TITLE = re.compile(r'suneung\.re\.kr|^-\s*$|^https?://')
        kept_old = {
            iid: item for iid, item in prev.items()
            if not is_expired(item["published"], no_expire=item.get("no_expire", False))
            and not _BAD_TITLE.search(item.get("title", ""))
            and len(item.get("title", "").strip()) >= 5
        }
        # 공식 사이트 수집이 0건이어도 no_expire 기사는 반드시 보존
        if cat.get("official") and len(fresh) == 0:
            no_expire_backup = {iid: item for iid, item in prev.items()
                                if item.get("no_expire") and not _BAD_TITLE.search(item.get("title",""))
                                and len(item.get("title","").strip()) >= 5}
            kept_old.update(no_expire_backup)
            if no_expire_backup:
                print(f"  ⚠ 공식 수집 0건 → no_expire 기사 {len(no_expire_backup)}건 강제 보존")
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
