"""
수학 입시 뉴스 수집기
- 소스: 구글 뉴스 RSS + 입시 전문 언론 RSS + 공식 사이트 + 네이버 뉴스 API
- 대상: 서울권 35개 4년제 대학 / 서울·경기 수도권 / 수학 과목 한정
- 블로그·카페 수집 없음 (품질 관리)
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

# ── 입시 전문 언론 RSS ────────────────────────────────────────
# 블로그 대신 신뢰할 수 있는 입시 전문 언론 RSS 직접 수집
EDU_RSS_FEEDS = [
    # 입시 전문
    ("https://www.veritas-a.com/rss/allArticle.xml",   "베리타스알파"),
    ("https://www.edujin.co.kr/rss/allArticle.xml",    "에듀진"),
    ("https://edu.chosun.com/site/data/rss/rss.xml",   "조선에듀"),
    ("https://www.unn.net/news/rss",                    "한국대학신문"),
    ("https://www.dhnews.co.kr/rss/allArticle.xml",    "대학저널"),
    # 일반 신문 교육 섹션
    ("https://rss.edaily.co.kr/edaily/section/education/rss.xml", "이데일리 교육"),
    ("https://www.yna.co.kr/rss/education.xml",        "연합뉴스 교육"),
]

# ── 카테고리 정의 ─────────────────────────────────────────────
# 블로그·카페 수집 없음. 구글 뉴스 RSS + 네이버 뉴스 + 전문 RSS + 공식 사이트만.
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
            "수능 수학 1등급컷 난이도 분석",
            "EBS 수능 수학 연계율 분석",
            "수능 수학 킬러 준킬러 출제 경향",
        ],
        "naver_news": [
            "6월 모의평가 수학 등급컷",
            "9월 모의평가 수학 등급컷",
            "수능 수학 난이도 분석",
            "평가원 수학 출제 경향",
        ],
        # 전문 RSS 키워드 필터 (해당 키워드 포함 기사만)
        "rss_keywords": ["모의고사", "모의평가", "등급컷", "수능 수학", "평가원", "EBS 연계"],
    },
    {
        "id": "sushi",
        "name": "수시",
        "emoji": "🎓",
        "google": [
            "서울대 연세대 고려대 수시 수학 최저",
            "성균관대 한양대 서강대 수시 수학 최저",
            "인서울 수시 수학 최저학력기준 2027",
            "서울권 대학 수시 전형 분석 2027",
            "2028 수시 수학 학생부 개편",
        ],
        "naver_news": [
            "인서울 수시 수학 최저학력기준",
            "서울대 수시 수학 최저",
            "연세대 고려대 수시 전형",
            "2028 수시 개편 수학",
        ],
        "rss_keywords": ["수시", "학생부", "수능 최저", "논술전형", "수시 전형", "SKY 수시"],
    },
    {
        "id": "jeongshi",
        "name": "정시",
        "emoji": "📊",
        "google": [
            "서울대 연세대 고려대 정시 수학 반영비율",
            "성균관대 한양대 정시 수학 가중치 2027",
            "인서울 정시 수학 반영비율 유불리",
            "서울권 정시 수학 가중치 비교 분석",
            "2028 정시 수학 반영 개편",
        ],
        "naver_news": [
            "인서울 정시 수학 반영비율",
            "서울대 정시 수학 가중치",
            "정시 수학 반영 유불리",
            "2028 정시 개편 수학",
        ],
        "rss_keywords": ["정시", "정시 수학", "수능 반영", "가중치", "정시 전략"],
    },
    {
        "id": "policy",
        "name": "교육과정·정책",
        "emoji": "📋",
        "official": True,
    },
    {
        "id": "yaksuljul",
        "name": "수리·약술 논술",
        "emoji": "✏️",
        "google": [
            "약술형 논술 수학 2027 대학",
            "국민대 가천대 약술 논술 수학 전형",
            "수리논술 수학 2027 서울 경기 대학",
            "연세대 성균관대 수리논술 수학 기출",
            "인서울 수리논술 준비 전략 수학",
            "약술형 논술 수능최저 없는 전형 2027",
        ],
        "naver_news": [
            "약술형 논술 수학 2027",
            "수리논술 기출 분석 2027",
            "인서울 논술 수학 최저 없는",
        ],
        "rss_keywords": ["약술형 논술", "수리논술", "논술 수학", "논술전형 수학"],
    },
    {
        "id": "schedule",
        "name": "입시 일정",
        "emoji": "📅",
        "google": [
            "서울권 대학 수시 원서접수 일정 2027",
            "서울대 연세대 고려대 수시 접수 일정",
            "수능 원서접수 일정 2027",
            "인서울 논술 고사 일정 2027",
        ],
        "naver_news": [
            "수능 원서접수 일정",
            "수시 원서접수 일정 2027",
            "대입 논술 고사 일정",
        ],
        "rss_keywords": ["원서접수", "수시 일정", "수능 일정", "논술 일정", "입시 일정", "접수 기간"],
    },
    # ── 고교입시 (경기 남부 — 수원·화성·용인 일반고) ──────────────
    {
        "id": "highschool",
        "name": "고교입시",
        "emoji": "🏫",
        "section": "highschool",   # 섹션 구분 플래그
        "google": [
            "수원 일반고 고등학교 배정 학군 2026",
            "화성 동탄 일반고 배정 학군 내신",
            "용인 수지 기흥 일반고 배정 학군",
            "광교 고등학교 학군 내신 등급컷",
            "동탄 고등학교 내신 학군 배정",
            "경기 남부 일반고 입시 전략 2026",
            "수원 화성 용인 고등학교 입시",
            "내신 5등급제 일반고 2026",
            "특목고 자사고 입시 2026",
            "고교 선택 전략 자사고 특목고",
            "일반고 학업중단 고교 양극화",
        ],
        "naver_news": [
            "수원 일반고 배정 학군",
            "화성 동탄 고등학교 배정",
            "용인 수지 일반고 학군",
            "광교 고등학교 내신",
            "경기 남부 고교 입시",
            "내신 5등급제 고등학교",
            "특목고 자사고 입시 전략",
            "고교 양극화 일반고",
        ],
        "rss_keywords": ["일반고 배정", "고등학교 배정", "학군 내신", "고교 입시 전략", "내신 등급컷", "내신 5등급", "특목고", "자사고"],
        "no_math_filter": True,   # 수학 키워드 필터 미적용
    },
]

# 고교입시 전용 whitelist: 지역+학교 키워드 동시 포함 OR 전국 단위 고교 이슈
HS_REGION_RE = re.compile(r"수원|화성|동탄|광교|용인|수지|기흥|영통|팔달|봉담|향남|처인|경기\s*(남부|도교육청|교육청)", re.IGNORECASE)
HS_TOPIC_RE  = re.compile(r"고등학교|일반고|학군|배정|내신|등급컷|입학|고교|학교\s*선택|진학|자사고|특목고|과학고|외고", re.IGNORECASE)
HS_BROAD_RE  = re.compile(r"내신\s*5등급|특목고|자사고|과학고|외고|고교\s*서열|고교\s*양극화|학업\s*중단|일반고\s*위기|고교\s*입시\s*전략|고교\s*선택|자율형\s*사립고|영재학교", re.IGNORECASE)

# ── 필터 ──────────────────────────────────────────────────────
BLACKLIST_RE = re.compile(
    r"이벤트|경품|쿠폰|할인|무료체험|다운로드|앱\s*(출시|소개|다운)|"
    r"구독\s*혜택|이용권|증정|광고|홍보|후원|협찬|PR\b|모집\s*중\s*$|"
    r"풍경|르포|현장\s*속|학원가\s*(풍경|모습|열기|분위기)|포토\b|\[포토\]|포토뉴스|"
    r"사교육\s*(열풍|과열)|치열한\s*입시|입시\s*전쟁|"
    r"영어\s*(과외|학원|노트|문법)|국어\s*과외|"
    r"선관위|기본권|이념|정치|부동산|청약|맛집|여행|육아|"
    r"셔세권|역세권|아파트|분양|재건축|재개발|갭투자|집값|전세|월세|임대|매매가|호가|"
    r"반도체\s*클러스터|반도체\s*바람|부동산\s*시장|화려한\s*부활|"
    r"뉴스\s*브리핑|간추린\s*뉴스|정책뉴스\d|칼럼.*IB|"
    r"전기박사|철물|AI\s*패권|"
    r"코스닥|코스피|주식|테마주|외인|기관매수|장중|주린이|차트|"
    r"PHEV|풀체인지|신형.*출시|자동차|전기차|SUV|세단|"
    r"그날그날|오늘의\s*일기|소소한\s*일상|맛집\s*후기|"
    r"\[유료\]|〔유료〕|유료\s*기사|유료\s*회원|프리미엄\s*기사|"
    r"학원.*(?:설명회|모집|개강|개최|정규반|특강\s*모집|수강생\s*모집)|"
    r"(?:설명회|정규반|모집).*학원|"
    r"(?:씨사이트|메이드학원|맥스수리|대성학원|이투스247|프리베수학).*(?:모집|개최|개강|안내)",
    re.IGNORECASE,
)

# 타지역 필터 (수도권=서울·경기·인천 외 지역 언급 기사 제거)
# 수학 관련 키워드 (제목에 하나도 없으면 제거) — 정책 카테고리 제외
MATH_RE = re.compile(
    r"수학|수능|모의고사|모의평가|등급컷|킬러|준킬러|수리|논술|EBS|수1|수2|"
    r"미적분|확통|기하|행렬|수열|적분|미분|함수|벡터|통계|대입|입시|전형|최저|"
    r"반영비율|가중치|약술|서울대|연세대|고려대|성균관|한양|서강|중앙대|경희|"
    r"이화|숙명|한국외대|서울시립|건국|동국|홍익|숭실|세종대|국민대|가천|"
    r"수시|정시|논술|원서|접수",
    re.IGNORECASE,
)

# 타지역 필터 (수도권=서울·경기·인천 외 지역 언급 기사 제거)
REGION_RE = re.compile(
    r"부산|대구|광주|대전|울산|세종|강원|충북|충남|전북|전남|전주|"
    r"경북|경남|제주|춘천|청주|천안|포항|창원|진주|여수|순천|목포|"
    r"구미|안동|김천|경주|통영|거제|울산|속초|강릉|원주",
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

KEEP_DAYS    = 30
MAX_PER_CAT  = 500
DATE_FROM    = datetime(2026, 3, 1, tzinfo=timezone.utc)
OUTPUT_FILE  = Path(__file__).parent / "news_data.json"
NOISE_FILE   = Path(__file__).parent / "noise_patterns.json"
ARCHIVE_DIR  = Path(__file__).parent

# 사용자 노이즈 패턴 로드 (섹션별)
def load_noise_patterns() -> dict:
    if not NOISE_FILE.exists():
        return {}
    try:
        data = json.loads(NOISE_FILE.read_text(encoding="utf-8"))
        result = {}
        for section, val in data.items():
            if section == "blocked_ids":
                result["blocked_ids"] = set(val)
                continue
            sources = set(val.get("sources", []))
            keywords = val.get("title_keywords", [])
            kw_re = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE) if keywords else None
            result[section] = {"sources": sources, "kw_re": kw_re}
            print(f"노이즈 패턴 [{section}]: 출처 {len(sources)}개 · 키워드 {len(keywords)}개")
        blocked = result.get("blocked_ids", set())
        print(f"영구 차단 ID: {len(blocked)}개")
        return result
    except Exception as e:
        print(f"노이즈 패턴 로드 실패: {e}")
        return {}

NOISE_PATTERNS = load_noise_patterns()

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


def fetch_naver(query: str, endpoint: str = "news", n=10) -> list[dict]:
    """네이버 API 수집. news만 허용 (blog/cafe 사용 안 함)."""
    if endpoint not in ("news",):
        return []  # 블로그·카페 수집 비활성화
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
    # 괄호 이후 날짜/시간 정보 제거 후 비교 (업데이트 시간 차이로 중복 못 잡는 문제 방지)
    t = re.sub(r'\([^)]*\d{1,2}\.\s*\d{2}.*$', '', t).strip()
    return frozenset(w for w in re.findall(r"[가-힣a-zA-Z0-9]{2,}", t) if w not in STOPWORDS)

def is_dup(tok: frozenset, seen: list, thr=0.80) -> bool:
    for s in seen:
        u = tok | s
        if u and len(tok & s) / len(u) >= thr:
            return True
    return False

# ── 핵심 키워드 추출 (숫자 포함 명사, 2자 이상 한글/영문+숫자) ──
_NUM_RE   = re.compile(r'\d+')
_NOUN_RE  = re.compile(r'[가-힣]{2,}')
# 의미 없는 조각 제거 (stopwords + 1글자 조사류)
_KW_STOP  = {"대한", "대해", "위해", "통해", "이후", "이전", "이번", "지난", "올해",
             "예정", "진행", "실시", "공개", "발표", "결과", "분석", "관련", "기반",
             "강화", "확대", "변화", "유지", "증가", "감소", "개선", "제시", "적용",
             "우리", "이상", "이하", "이내", "이외", "이유", "경우", "현재", "최근"}

def key_tokens(title: str) -> frozenset:
    """제목에서 핵심 명사+숫자 조합을 추출한다."""
    words = set()
    # 숫자는 그대로 보존
    for n in _NUM_RE.findall(title):
        words.add(n)
    # 한글 명사 (2자 이상, 불용어 제거)
    for w in _NOUN_RE.findall(title):
        if w not in _KW_STOP and w not in STOPWORDS:
            words.add(w)
    # 복합어 분해: 4자 이상 한글 단어는 가능한 모든 2+n 분할점 시도
    # 예: "반도체학과"(5) → split@2("반도","체학과"), split@3("반도체","학과") 모두 추가
    for w in list(words):
        if len(w) >= 4 and _NOUN_RE.fullmatch(w):
            for split in range(2, len(w) - 1):
                left, right = w[:split], w[split:]
                if len(left) >= 2 and left not in _KW_STOP and left not in STOPWORDS:
                    words.add(left)
                if len(right) >= 2 and right not in _KW_STOP and right not in STOPWORDS:
                    words.add(right)
    return frozenset(words)

def semantic_dedup(items: list[dict], overlap: int = 3) -> list[dict]:
    """
    같은 날 기사 중 핵심 키워드가 overlap개 이상 겹치면
    가장 오래된 기사 하나만 남긴다.
    """
    def day_key(pub: str) -> str:
        try:
            d = datetime.fromisoformat(pub)
            return d.strftime("%Y-%m-%d")
        except Exception:
            return pub[:10]

    kept: list[dict] = []
    kept_kw: list[tuple[str, frozenset]] = []  # (day, keytokens)

    # 오래된 것 우선 (가장 먼저 나온 기사 보존)
    for item in sorted(items, key=lambda x: x.get("published", "")):
        day  = day_key(item["published"])
        ktok = key_tokens(item["title"])
        dup  = False
        for (kday, kkw) in kept_kw:
            if kday != day:
                continue
            if len(ktok) == 0 or len(kkw) == 0:
                continue
            if len(ktok & kkw) >= overlap:
                dup = True
                break
        if not dup:
            kept.append(item)
            kept_kw.append((day, ktok))

    # 원래 시간 역순 정렬 복원
    kept.sort(key=lambda x: x.get("published", ""), reverse=True)
    return kept

def is_expired(pub: str, no_expire: bool = False) -> bool:
    if no_expire:
        return False  # 정책 기사는 영구 보관
    try:
        d = datetime.fromisoformat(pub)
        if not d.tzinfo:
            d = d.replace(tzinfo=timezone.utc)
        if d < DATE_FROM:
            return True  # 26년 3월 이전은 항상 만료
        now = datetime.now(timezone.utc)
        age_days = (now - d).days
        # 이전 달 기사이면서 최소 14일 지난 경우 만료
        prev_month = (d.year, d.month) < (now.year, now.month)
        return prev_month and age_days >= 14
    except Exception:
        return False

def is_user_noise(item: dict, section: str = "daip") -> bool:
    pat = NOISE_PATTERNS.get(section, {})
    if item.get("source") in pat.get("sources", set()):
        return True
    kw_re = pat.get("kw_re")
    if kw_re and kw_re.search(item.get("title", "")):
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

BLOCKED_IDS = NOISE_PATTERNS.get("blocked_ids", set())

def clean(items: list[dict], cat_id: str = '') -> list[dict]:
    seen_ids, out = set(), []
    seen_tok_by_src: dict[str, list] = {}  # 출처별 토큰 목록
    for item in items:
        if item["id"] in seen_ids:
            continue
        if item["id"] in BLOCKED_IDS:
            continue
        # 블로그·카페 타입 전부 차단
        if item.get("type") in ("blog", "cafearticle"):
            continue
        if is_too_old(item["published"]):
            continue
        if BLACKLIST_RE.search(item["title"]):
            continue
        # 타지역(수도권 외) 기사 제거 (고교입시는 제외 — 경기 남부 특화)
        if cat_id != 'highschool' and REGION_RE.search(item["title"]):
            continue
        # 수학 관련 키워드 없는 기사 제거 (정책·고교입시 카테고리 제외)
        if cat_id not in ('policy', 'highschool') and not MATH_RE.search(item["title"]):
            continue
        # 고교입시: (지역+학교 키워드) 또는 (전국 단위 고교 이슈) 중 하나 충족
        if cat_id == 'highschool':
            local_pass  = HS_REGION_RE.search(item["title"]) and HS_TOPIC_RE.search(item["title"])
            broad_pass  = HS_BROAD_RE.search(item["title"])
            if not (local_pass or broad_pass):
                continue
        # 블로그·카페는 광고 추가 필터 적용
        if item.get("type") in ("blog", "cafearticle") and BLOG_AD_RE.search(item["title"]):
            continue
        section = "highschool" if cat_id == "highschool" else "daip"
        if is_user_noise(item, section):
            continue
        tok = tokenize(item["title"])
        src = item.get("source", "")
        src_toks = seen_tok_by_src.setdefault(src, [])
        if tok and is_dup(tok, src_toks):
            continue
        # 제목 최대 60자로 자르기 (공식 사이트 긴 설명문 방지)
        item["title"] = item["title"][:80].strip()
        item["grade"] = tag_grade(cat_id)
        seen_ids.add(item["id"])
        src_toks.append(tok)
        out.append(item)
    return out


# ── 전문 언론 RSS 수집 ───────────────────────────────────────
def fetch_edu_rss(rss_url: str, source_name: str, keywords: list[str], n=20) -> list[dict]:
    """입시 전문 언론 RSS 직접 파싱. keywords 중 하나라도 제목에 있어야 통과."""
    try:
        feed = feedparser.parse(rss_url)
    except Exception as e:
        print(f"  RSS 오류 ({source_name}): {e}")
        return []
    kw_re = re.compile("|".join(re.escape(k) for k in keywords), re.IGNORECASE) if keywords else None
    items = []
    for entry in feed.entries[:n]:
        title = entry.get("title", "").strip()
        if not title:
            continue
        if kw_re and not kw_re.search(title):
            continue
        link = entry.get("link", "#")
        try:
            pub = parsedate_to_datetime(entry.get("published", ""))
            pub_iso = pub.astimezone(timezone.utc).isoformat()
        except Exception:
            pub_iso = datetime.now(timezone.utc).isoformat()
        uid = hashlib.md5(link.encode()).hexdigest()
        # 유료화 출처는 본문에서 paywall 여부 확인
        if any(ps in link for ps in PAYWALL_SOURCES):
            if is_paywalled(link):
                continue
        items.append({
            "id": uid, "title": title, "link": link,
            "source": source_name, "published": pub_iso, "type": "news",
        })
    return items


PAYWALL_SOURCES = {"edujin.co.kr"}  # 본문 체크할 유료화 출처
# 에듀진: panel-block이 display:block → 유료, display:none → 무료
EDUJIN_PAYWALL_RE = re.compile(
    r'class="panel\s+panel-block[^"]*"[^>]*style="[^"]*display\s*:\s*block',
    re.IGNORECASE
)
# 기타 출처용 범용 유료 감지
PAYWALL_RE = re.compile(
    r"유료회원전용기사|유료회원만\s*열람|구독\s*후\s*이용|프리미엄\s*회원전용",
    re.IGNORECASE
)

def is_paywalled(url: str) -> bool:
    """유료화 출처의 기사 본문에서 paywall 여부 확인"""
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=7) as r:
            html = r.read(100000).decode("utf-8", errors="ignore")
        if "edujin.co.kr" in url:
            return bool(EDUJIN_PAYWALL_RE.search(html))
        return bool(PAYWALL_RE.search(html))
    except Exception:
        return False  # fetch 실패 시 일단 포함


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

    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=KEEP_DAYS)

    seen_seq = set()
    items = []
    # goView('boardID','boardSeq',...) 방식 — 제목 + boardSeq + 날짜(YYYY-MM-DD) 추출
    block_re = re.compile(
        r"goView\('1500229','(\d+)'[^)]*\)[^>]*>\s*(.*?)\s*(?:<img[^>]*>)?\s*</a>"
        r".*?(\d{4}-\d{2}-\d{2})",
        re.DOTALL
    )
    for seq, title, raw_date in block_re.findall(html)[:20]:
        if seq in seen_seq:
            continue
        seen_seq.add(seq)
        try:
            pub_dt = datetime.strptime(raw_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if pub_dt < cutoff or pub_dt < DATE_FROM:
            continue
        title = re.sub(r'<[^>]+>', '', title).strip()
        title = re.sub(r'&nbsp;|\s+', ' ', title).strip()
        if len(title) < 5:
            continue
        full_url = f"https://www.suneung.re.kr/boardCnts/view.do?boardID=1500229&boardSeq={seq}&lev=0&m=0301&s=suneung"
        uid = hashlib.md5(seq.encode()).hexdigest()
        items.append({
            "id": uid, "title": title, "link": full_url,
            "source": "한국교육과정평가원",
            "published": pub_dt.isoformat(),
            "type": "official", "no_expire": True,
        })
    return items


def fetch_korea_kr_press(n=20) -> list[dict]:
    """정책브리핑 보도자료 목록 직접 수집 — 실제 게시일 파싱, 30일 초과 기사 제외"""
    url = "https://www.korea.kr/briefing/pressReleaseList.do"
    headers = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=10) as r:
            html = r.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"  정책브리핑 수집 오류: {e}")
        return []

    POLICY_KEEP_RE = re.compile(
        r'수능|대입|대학수학능력|수시|정시|교육과정|고등학교|고등부|'
        r'학력평가|모의평가|출제|입시|수학능력|EBS|내신|논술|수학\s*교육|'
        r'사교육|킬러|입학전형|대학입학|학사|교육부', re.IGNORECASE
    )
    POLICY_BLOCK_RE = re.compile(
        r'베트남|TOPIK|한국어능력|직업훈련|내일배움|발달장애|크루즈|청소년증|'
        r'해수부|농식품|청렴|유치원|어린이|돌봄|마이스터고|거점국립|지방대학|'
        r'사립대학\s*육성|영어마을|장학재단', re.IGNORECASE
    )
    # korea.kr 목록: <strong>제목</strong> + <span class="source"><span>YYYY.MM.DD</span>
    block_re = re.compile(
        r'pressReleaseView\.do\?newsId=(\d+)[^"]*"[^>]*>.*?'
        r'<strong>(.*?)</strong>.*?'
        r'class="source">\s*<span>(\d{4}\.\d{2}\.\d{2})</span>',
        re.DOTALL
    )
    now_utc = datetime.now(timezone.utc)
    cutoff = now_utc - timedelta(days=KEEP_DAYS)

    seen_nid, seen_title, items = set(), set(), []
    for nid, raw_title, raw_date in block_re.findall(html):
        try:
            pub_dt = datetime.strptime(raw_date, "%Y.%m.%d").replace(tzinfo=timezone.utc)
        except ValueError:
            continue
        if pub_dt < cutoff or pub_dt < DATE_FROM:
            continue
        title = re.sub(r'<[^>]+>', '', raw_title).strip()
        title = re.sub(r'\s+', ' ', title).strip()
        title = re.split(r'[\.…\n□]', title)[0].strip()
        title = title[:70].strip()
        if len(title) < 5:
            continue
        title_key = re.sub(r'\s+', '', title)
        if nid in seen_nid or title_key in seen_title:
            continue
        if not POLICY_KEEP_RE.search(title):
            continue
        if POLICY_BLOCK_RE.search(title):
            continue
        seen_nid.add(nid)
        seen_title.add(title_key)
        full_url = f"https://www.korea.kr/briefing/pressReleaseView.do?newsId={nid}"
        uid = hashlib.md5(nid.encode()).hexdigest()
        items.append({
            "id": uid, "title": title, "link": full_url,
            "source": "정책브리핑(교육부)",
            "published": pub_dt.isoformat(),
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
    seen_global_ids = set()  # 카테고리 간 중복 제거용
    for cat in CATEGORIES:
        raw = []

        # 공식 사이트 수집 (정책 카테고리만)
        if cat.get("official"):
            print(f"  [{cat['name']}] 공식 사이트 수집 중...")
            raw.extend(fetch_suneung())
            raw.extend(fetch_korea_kr_press())

        # policy 카테고리는 공식 사이트만 — 구글/네이버/RSS 수집 없음
        if cat.get("id") != 'policy':
            for q in cat.get("google", []):
                raw.extend(fetch_google_news(q))
            for q in cat.get("naver_news", []):
                raw.extend(fetch_naver(q, "news"))
            rss_kws = cat.get("rss_keywords", [])
            for rss_url, src_name in EDU_RSS_FEEDS:
                raw.extend(fetch_edu_rss(rss_url, src_name, rss_kws))

        raw.sort(key=lambda x: x["published"], reverse=True)
        fresh = clean(raw, cat_id=cat["id"])

        prev = existing.get(cat["id"], {})
        now = datetime.now(timezone.utc)
        for item in fresh:
            # 발행일 기준 24시간 이내인 것만 NEW (놓쳤다가 나중에 발견한 구기사 제외)
            try:
                pub = datetime.fromisoformat(item["published"])
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                is_recent = (now - pub).total_seconds() < 86400
            except Exception:
                is_recent = False
            item["is_new"] = (item["id"] not in prev) and is_recent

        # no_expire 항목은 만료 안 됨 (정책 기사 영구 보관)
        _BAD_TITLE = re.compile(r'suneung\.re\.kr|^-\s*$|^https?://')
        kept_old = {
            iid: item for iid, item in prev.items()
            if iid not in BLOCKED_IDS
            and not is_expired(item["published"], no_expire=item.get("no_expire", False))
            and not _BAD_TITLE.search(item.get("title", ""))
            and len(item.get("title", "").strip()) >= 5
        }
        # 정책 카테고리: no_expire 기사는 수집 성공 여부와 무관하게 항상 보존
        if cat.get("official"):
            no_expire_backup = {iid: item for iid, item in prev.items()
                                if item.get("no_expire") and not _BAD_TITLE.search(item.get("title",""))
                                and len(item.get("title","").strip()) >= 5
                                and not re.search(r'^문서뷰어|^-\s*\w', item.get("title",""))}
            kept_old.update(no_expire_backup)
            if no_expire_backup:
                print(f"  📌 no_expire 기사 {len(no_expire_backup)}건 강제 보존")
        merged = {**{i["id"]: i for i in fresh}, **{iid: {**item, "is_new": False}
                  for iid, item in kept_old.items() if iid not in {i["id"] for i in fresh}}}
        # 앞 카테고리에 이미 있는 기사는 제거 (카테고리 간 중복 방지)
        deduped = {iid: item for iid, item in merged.items() if iid not in seen_global_ids}
        seen_global_ids.update(deduped.keys())
        result_raw = sorted(deduped.values(), key=lambda x: x["published"], reverse=True)[:MAX_PER_CAT]
        result = semantic_dedup(result_raw)

        sem_removed = len(result_raw) - len(result)
        expired = len(prev) - len(kept_old)
        print(f"[{cat['name']}] 신규 {len(fresh)}건 · 누적 {len(result)}건 · 만료 {expired}건" +
              (f" · 의미중복 제거 {sem_removed}건" if sem_removed else ""))

        categories_out.append({"id": cat["id"], "name": cat["name"],
                                "emoji": cat["emoji"], "items": result})

    # ── 만료 기사 아카이브 저장 ──────────────────────────────────
    archive_months = set()
    for cat_data in categories_out:
        cat_id = cat_data["id"]
        prev = existing.get(cat_id, {})
        _BAD = re.compile(r'suneung\.re\.kr|^-\s*$|^https?://')
        expired_items = [
            item for iid, item in prev.items()
            if is_expired(item["published"], no_expire=item.get("no_expire", False))
            and not _BAD.search(item.get("title", ""))
            and len(item.get("title", "").strip()) >= 5
        ]
        for item in expired_items:
            try:
                pub = datetime.fromisoformat(item["published"])
                if pub.tzinfo is None:
                    pub = pub.replace(tzinfo=timezone.utc)
                ym = pub.strftime("%Y_%m")
                archive_months.add(ym)
                arc_file = ARCHIVE_DIR / f"archive_{ym}.json"
                if arc_file.exists():
                    arc = json.loads(arc_file.read_text(encoding="utf-8"))
                else:
                    arc = {"month": ym, "generated_at": datetime.now(timezone.utc).isoformat(), "categories": {}}
                cats_arc = arc.get("categories", {})
                if cat_id not in cats_arc:
                    cats_arc[cat_id] = {"id": cat_id, "name": cat_data["name"], "emoji": cat_data["emoji"], "items": {}}
                cats_arc[cat_id]["items"][item["id"]] = item
                arc["categories"] = cats_arc
                arc_file.write_text(json.dumps(arc, ensure_ascii=False, indent=2), encoding="utf-8")
            except Exception as e:
                print(f"  아카이브 저장 오류: {e}")

    if archive_months:
        print(f"📦 아카이브 저장: {', '.join(sorted(archive_months))}")

    # available_archives 목록 자동 생성
    available = sorted([
        f.stem.replace("archive_", "").replace("_", "-")
        for f in ARCHIVE_DIR.glob("archive_*.json")
    ], reverse=True)

    # 경량 검색 인덱스 생성 (제목+링크+날짜+카테고리만)
    index_items = []
    for arc_ym in available:
        arc_file = ARCHIVE_DIR / f"archive_{arc_ym.replace('-', '_')}.json"
        try:
            arc = json.loads(arc_file.read_text(encoding="utf-8"))
            month_str = arc_ym  # "2026-05"
            for cat_id, cat_data_arc in arc.get("categories", {}).items():
                for item in cat_data_arc.get("items", {}).values():
                    index_items.append({
                        "id": item["id"],
                        "title": item["title"],
                        "link": item["link"],
                        "published": item["published"],
                        "source": item.get("source", ""),
                        "cat": cat_id,
                        "catName": cat_data_arc["name"],
                        "catEmoji": cat_data_arc["emoji"],
                        "month": month_str,
                    })
        except Exception as e:
            print(f"  인덱스 생성 오류 ({arc_ym}): {e}")

    index_items.sort(key=lambda x: x["published"], reverse=True)
    index_file = ARCHIVE_DIR / "archive_index.json"
    index_file.write_text(
        json.dumps({"generated_at": datetime.now(timezone.utc).isoformat(),
                    "total": len(index_items), "items": index_items},
                   ensure_ascii=False, separators=(',', ':')),
        encoding="utf-8"
    )
    print(f"🔍 인덱스 생성: {len(index_items)}건 → archive_index.json")

    OUTPUT_FILE.write_text(
        json.dumps({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "available_archives": available,
            "categories": categories_out
        }, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )
    print(f"\n저장 완료 → {OUTPUT_FILE}")

if __name__ == "__main__":
    main()
