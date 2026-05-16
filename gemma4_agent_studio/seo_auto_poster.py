# ==========================================
# SEO 최적화 프롬프트 및 META_DATA 검증 포함 통합 스크립트
# ==========================================

import requests
import json
import re
import base64
import random
import pandas as pd
import time
import os
import textwrap
import warnings
from urllib.parse import quote
from datetime import datetime
from typing import Tuple, Optional, List
from PIL import Image, ImageDraw, ImageFont
from concurrent.futures import ThreadPoolExecutor, as_completed
from tenacity import retry, stop_after_attempt, wait_exponential
from dotenv import load_dotenv

# ==========================================
# 0. 초기 설정 및 보안 (dotenv)
# ==========================================
load_dotenv()

# 🔒 보안: 기본값에 실제 크리덴셜을 절대 넣지 마세요.
#           .env 파일에 반드시 설정하세요.
TAVILY_API_KEY  = os.getenv("TAVILY_API_KEY", "")
SERPER_API_KEY  = os.getenv("SERPER_API_KEY", "")
WP_URL          = os.getenv("WP_URL",    "https://blog.worldwideinfonet.com/wp-json/wp/v2")
WP_USER         = os.getenv("WP_USER",   "blanclucy2026")
WP_APP_PW       = os.getenv("WP_APP_PW", "")          # ← .env 에서만 설정

if not WP_APP_PW:
    raise EnvironmentError("❌ WP_APP_PW 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")

OLLAMA_API_URL  = "http://localhost:11434/api/generate"
MODEL_NAME      = "gemma4:e4b"
EXCEL_FILE      = "keywords.xlsx"
COLUMN_NAME     = "주제"
LLM_TIMEOUT     = 600

# ── 발행 간격 설정 (단위: 초) ─────────────────────────────
# 각 포스트 완료 후 MIN~MAX 초 사이의 랜덤 시간만큼 대기
POST_DELAY_MIN  = 30    # 최소 대기 (초)
POST_DELAY_MAX  = 120   # 최대 대기 (초)

# ── 테스트 모드 ───────────────────────────────────────────
# True  → WordPress 업로드 없이 로컬 파일로 결과 저장 (첫 번째 항목 1개만)
# False → 실제 업로드 (운영 모드)
TEST_MODE       = True

warnings.filterwarnings('ignore', category=RuntimeWarning)

# ==========================================
# 1. 썸네일 생성 및 미디어 관리 (ID 반환)
# ==========================================

def create_thumbnail(main_title: str, focus_keyword: str, output_filename: str) -> str:
    """SCDream9.otf 기반 1080x1080 썸네일 생성 (개선 버전)"""
    width, height = 1080, 1080
    img  = Image.new("RGB", (width, height), "#F0F4F8")
    draw = ImageDraw.Draw(img)

    # ── 배경 디자인 ──────────────────────────────────────────
    # 상단 연회색 띠
    draw.rectangle([(0, 0), (width, 210)], fill="#E4ECF4")
    # 상단 우측 파란 삼각형 포인트
    draw.polygon([(720, 0), (width, 0), (width, 230)], fill="#3B82F6")
    # 하단 네이비 사다리꼴
    draw.polygon([(0, 870), (width, 920), (width, height), (0, height)], fill="#1E3A5F")
    # 하단 파란 강조 띠
    draw.rectangle([(0, 970), (width, height)], fill="#2563EB")

    # ── 폰트 설정 ────────────────────────────────────────────
    # SCDream9.otf를 스크립트와 같은 폴더에서 먼저 탐색
    script_dir = os.path.dirname(os.path.abspath(__file__))
    font_candidates = [
        os.path.join(script_dir, "SCDream9.otf"),   # ← 최우선
        "SCDream9.otf",
        "C:/Windows/Fonts/malgun.ttf",
        "/System/Library/Fonts/AppleSDGothicNeo.ttc",
    ]
    font_path = next((p for p in font_candidates if os.path.exists(p)), None)

    TITLE_SIZE = 60   # 이전 95 → 60 (가독성 개선)
    TAG_SIZE   = 34

    try:
        if font_path:
            font_title = ImageFont.truetype(font_path, TITLE_SIZE)
            font_tag   = ImageFont.truetype(font_path, TAG_SIZE)
        else:
            raise IOError("폰트 없음")
    except Exception:
        font_title = font_tag = ImageFont.load_default()

    # ── 제목 텍스트 래핑 ─────────────────────────────────────
    # 60px 기준 1080px 너비 → 한 줄 약 15자(여백 포함 14자 권장)
    wrap_width = 14 if len(main_title) > 14 else len(main_title)
    wrapper    = textwrap.TextWrapper(width=wrap_width, break_long_words=True)
    wrapped    = wrapper.fill(text=main_title)

    # 텍스트 블록 크기 측정
    t_bbox = draw.multiline_textbbox((0, 0), wrapped, font=font_title, align="center", spacing=22)
    t_w = t_bbox[2] - t_bbox[0]
    t_h = t_bbox[3] - t_bbox[1]

    # 수직 중앙보다 약간 위 배치 (하단 태그 공간 확보)
    tx = (width - t_w) / 2
    ty = (height - t_h) / 2 - 60

    # 그림자 (2px 오프셋, 연한 슬레이트)
    draw.multiline_text((tx + 2, ty + 2), wrapped, font=font_title,
                        fill="#94A3B8", align="center", spacing=22)
    # 메인 타이틀
    draw.multiline_text((tx,     ty    ), wrapped, font=font_title,
                        fill="#0F172A", align="center", spacing=22)

    # ── 타이틀 아래 파란 구분선 ──────────────────────────────
    sep_y = int(ty + t_h + 32)
    draw.rectangle([(width // 2 - 100, sep_y), (width // 2 + 100, sep_y + 5)], fill="#3B82F6")

    # ── 하단 키워드 태그 박스 ────────────────────────────────
    tag_text = f"#{focus_keyword}  핵심 요약 가이드"
    sb  = draw.textbbox((0, 0), tag_text, font=font_tag)
    sw  = sb[2] - sb[0]
    sh  = sb[3] - sb[1]
    sx  = (width - sw) / 2
    sy  = height - 100          # 하단에서 100px 위

    pad_x, pad_y = 32, 14
    draw.rectangle(
        [(sx - pad_x, sy - pad_y), (sx + sw + pad_x, sy + sh + pad_y)],
        fill="#2563EB"
    )
    draw.text((sx, sy), tag_text, font=font_tag, fill="#FFFFFF")

    img.save(output_filename)
    return output_filename


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
def upload_media_to_wordpress(file_path: str) -> Tuple[Optional[int], Optional[str]]:
    """미디어 업로드 후 ID와 URL을 모두 반환하여 대표 이미지 설정 지원"""
    token = base64.b64encode(f"{WP_USER}:{WP_APP_PW}".encode()).decode()
    with open(file_path, 'rb') as f:
        media_data = f.read()
    headers = {
        'Authorization':      f'Basic {token}',
        'Content-Type':       'image/png',
        'Content-Disposition': f'attachment; filename="{quote(os.path.basename(file_path))}"'
    }
    res = requests.post(f"{WP_URL}/media", headers=headers, data=media_data, timeout=30)
    res.raise_for_status()
    info = res.json()
    return info.get('id'), info.get('source_url')


# ==========================================
# 2. 검색 엔진 데이터 수집 (Serper PAA / Tavily Facts)
# ==========================================

@retry(stop=stop_after_attempt(2), wait=wait_exponential(multiplier=1, min=2, max=5))
def get_seo_and_facts(query: str):
    """Serper PAA 질문과 Tavily 팩트 데이터를 동시에 수집"""
    # ✅ FIX #2: paa = ] → paa = []
    paa = []
    try:
        res = requests.post(
            "https://google.serper.dev/search",
            headers={'X-API-KEY': SERPER_API_KEY, 'Content-Type': 'application/json'},
            json={"q": query, "gl": "kr", "hl": "ko"},
            timeout=15
        )
        paa = [i.get('question') for i in res.json().get('peopleAlsoAsk', [])]
    except Exception as e:
        print(f"⚠️ Serper 에러: {e}")

    facts = ""
    try:
        res = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key":        TAVILY_API_KEY,
                "query":          query,
                "search_depth":   "advanced",
                "include_answer": True,
                "days":           90,    # ✅ 최근 90일 기사 우선 (구버전 기사 억제)
            },
            timeout=20
        )
        t_res = res.json()
        # 수집 날짜 태그를 facts에 포함 → LLM이 참고 시점을 인식하게 함
        today_str = datetime.now().strftime("%Y년 %m월 %d일")
        facts = f"📅 수집 날짜: {today_str}\n💡 AI 요약: {t_res.get('answer', '')}\n" + \
                "\n".join([f"- {r['content'][:300]}" for r in t_res.get('results', [])[:3]])
    except Exception as e:
        facts = f"팩트체크 수집 실패: {e}"

    return paa, facts


# ==========================================
# 3. 고도화된 콘텐츠 생성 (SEO 최적화 프롬프트)
# ==========================================

def _safe_slug(text: str) -> str:
    """영문/숫자만 남겨 URL-safe 슬러그 생성 (한글 URL 인코딩 방지)"""
    s = re.sub(r'[^0-9a-zA-Z\s]+', '', text)   # ✅ 개선: 한글 제거 → 깔끔한 영문 슬러그
    s = re.sub(r'\s+', '-', s.strip().lower())
    return s[:120] or "post"


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=5, max=20))
def generate_optimized_post(topic: str, paa: List[str], facts: str) -> str:
    """Serper PAA가 포함된 SEO 최적화 포스팅 생성"""
    paa_str        = ", ".join(paa) if paa else "일반적인 궁금증"
    suggested_slug = _safe_slug(topic)
    # ✅ 오늘 날짜를 프롬프트에 명시 → LLM 학습 컷오프 기준 날짜 오류 방지
    today_str      = datetime.now().strftime("%Y년 %m월 %d일")

    prompt = f"""
역할: 전문 IT/비즈니스 블로거 겸 SEO 콘텐츠 라이터. 출력은 HTML 태그만 사용합니다. 분량은 반드시 1,500~2,500단어 이상으로 작성하세요. 짧은 글은 절대 허용되지 않습니다. 한국어로 작성하세요.

⚠️ 중요: 오늘 날짜는 {today_str}입니다. 연도·날짜를 언급할 때 반드시 이 날짜를 기준으로 작성하세요. 2024년 등 과거 연도를 현재인 것처럼 쓰지 마세요.

입력값:
주제: {topic}
팩트데이터: {facts}
구글 추천질문들: {paa_str}

목표(우선순위):
구글 상위 노출(검색 의도 매칭, 스니펫/피처드 스니펫 타깃, People Also Ask 포함)
워드프레스에 바로 붙여넣어도 좋은 HTML 구조와 메타데이터 제공
독자 친화적이고 자연스러운 문장, 전문성(전문가 신뢰성), 근거(팩트 데이터) 반영

지시사항(반드시 따를 것):
출력은 세 개의 구역으로 나누어 제공: <META_DATA>, <HTML_BODY>, <IMAGE_PROMPT>.

<META_DATA>에는 한 줄씩 key:value 형태로 아래 항목을 생성:
snippet_title: 클릭 유도형 타이틀(최대 60자, 주요 키워드 앞부분에 배치)
meta_description: 140~155자 요약(검색결과에 최적화, 주요 키워드 포함)
focus_keyword: 주요 키워드(1-3단어)
secondary_keywords: 쉼표로 구분된 관련 키워드(3~6개, 변형 포함)
canonical_url: 가능하면 내부 경로(예: /{suggested_slug}) 형태 제안
schema_type: 추천 스키마 유형(Article, HowTo, FAQ 등)

<HTML_BODY> 구조 (아래 순서대로 모두 포함, 생략 금지):

[1] H1 제목 (단 하나, focus_keyword 포함)

[2] 도입부 (60~100단어): 독자의 문제 공감 → 이 글로 얻을 혜택 → 핵심 키워드 포함

[3] 핵심 요약 박스 <div style="background:#f0f4ff;border-left:4px solid #3b82f6;padding:16px;">: 이 글의 핵심 포인트 3~5개를 <ul>로 나열

[4] H2 본문 섹션 (최소 5개 이상 작성, 각 섹션마다 3~5문단):
   - 개념/정의 설명 (H2)
   - 필요한 이유/배경 (H2)
   - 단계별 방법 또는 핵심 절차 (H2, <ol>로 구체적 단계 나열)
   - 비교표 <table>: 관련 옵션·방법·서비스를 2~4열로 비교
   - 실전 예시 또는 사례 (H2): 구체적 상황을 가정한 예시
   - 전문가 팁 <div style="background:#fff7ed;border-left:4px solid #f97316;padding:16px;"> (H2): 놓치기 쉬운 팁 3가지 이상
   - 주의사항·실수 유형 (H2): 흔한 실수 또는 주의할 점

[5] FAQ 섹션 (H2): 구글 추천질문들을 각 <h3>로, 답변은 2~4문단(충분히 상세하게)
FAQ JSON-LD <script type="application/ld+json"> 블록 포함

[6] 마무리 요약 (H2): 핵심 내용을 3~5줄로 정리 후 행동 유도(CTA) 문장 포함
외부 링크: 본문 주제와 관련된 국내 공신력 있는 정부·공공기관 사이트 1~2개를 rel="nofollow noopener noreferrer" target="_blank"로 삽입하세요.
아래 목록에서 주제와 가장 관련성 높은 기관을 선택하세요(없으면 가장 유사한 곳 선택):
- 정부24 (https://www.gov.kr) — 행정·민원 전반
- 국세청 (https://www.nts.go.kr) — 세금·세무
- 고용노동부 (https://www.moel.go.kr) — 고용·노동·복지
- 금융감독원 (https://www.fss.or.kr) — 금융·보험·투자
- 국민건강보험공단 (https://www.nhis.or.kr) — 건강보험·의료
- 건강보험심사평가원 (https://www.hira.or.kr) — 의료비·약제
- 중소벤처기업부 (https://www.mss.go.kr) — 창업·중소기업
- 공정거래위원회 (https://www.ftc.go.kr) — 소비자·공정거래
- 행정안전부 (https://www.mois.go.kr) — 지방행정·안전
- 법제처 국가법령정보센터 (https://www.law.go.kr) — 법률·규정
- 통계청 (https://www.kostat.go.kr) — 통계·데이터
- 한국소비자원 (https://www.kca.go.kr) — 소비자 피해·상담
- 교육부 (https://www.moe.go.kr) — 교육·학교
- 질병관리청 (https://www.kdca.go.kr) — 감염병·공중보건
- 국토교통부 (https://www.molit.go.kr) — 부동산·교통
링크 텍스트는 기관명으로 작성하고, 본문 문맥에 자연스럽게 녹여 삽입하세요. 내부 링크는 삽입하지 마세요.
이미지 ALT: 본문에 삽입될 이미지의 ALT 텍스트 1개 이상 포함(간단 문장).

SEO 세부 지침:
키워드 밀도는 자연스럽게 유지. 초반 100단어 내에 주요 키워드 1회 포함.
제목(snippet_title)은 50~60자 이내, meta_description은 140~155자로 생성.
본문 내에 간단한 HTML <table> 비교표가 필요하면 포함.
메타데이터와 본문은 서로 일관성 있게 유지.

스니펫/클릭 유도:
도입과 meta_description에 '해결'과 '숫자/기간/혜택'을 넣어 클릭률을 높이세요(예: "5분만에", "3가지 방법").

사실 검증:
[팩트데이터]를 인라인으로 인용하되, 기존 출처가 있으면 괄호로 출처 표기(예: (출처: Tavily)).

출력 형식 제약:
절대 마크다운(#, *)을 사용하지 마세요.
HTML 외 다른 문구 포맷을 섞지 마세요.
<META_DATA>, <HTML_BODY>, <IMAGE_PROMPT> 태그는 반드시 포함하세요.

출력 예시 요구사항:
<META_DATA>에서 snippet_title과 meta_description은 실제 업로드용으로 바로 사용 가능하도록 길이 제한을 지키세요.
<HTML_BODY>의 끝에 <script type="application/ld+json"> ... </script> 형태의 FAQ JSON-LD를 포함하세요.
"""

    res = requests.post(
        OLLAMA_API_URL,
        json={
            "model":   MODEL_NAME,
            "prompt":  prompt,
            "stream":  False,
            "options": {"num_ctx": 16384}   # 긴 글 생성을 위해 컨텍스트 확장
        },
        timeout=LLM_TIMEOUT
    )
    res.raise_for_status()
    return res.json().get('response', '').strip()


# ==========================================
# 3.1. 메타데이터 길이 검증 도우미
# ==========================================

def _truncate_meta_text(text: str, max_chars: int) -> str:
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text).strip()
    if len(text) <= max_chars:
        return text
    # ✅ FIX #4: rsplit()은 리스트 반환 → [0]으로 첫 번째 요소만 반환
    cut = text[:max_chars].rsplit(' ', 1)
    return cut[0]


# ==========================================
# 4. 통합 파이프라인 (단일 행 처리)
# ==========================================

def process_single_row(index: int, row_topic: str) -> dict:
    # ✅ FIX #5: split('\n')은 리스트 반환 → [0]으로 첫 줄만 추출 후 re.sub에 전달
    first_line = row_topic.split('\n')[0]
    search_kw  = " ".join(re.sub(r'[^\w\s가-힣]', ' ', first_line).strip().split()[:4])

    try:
        # 1) 데이터 수집
        paa, facts = get_seo_and_facts(search_kw)

        # 2) 글쓰기
        final_content = generate_optimized_post(row_topic, paa, facts)

        # 3) 파싱
        # ✅ FIX #6: \\n → \n, |$ 제거
        clean_text  = re.sub(r'^\w*\n', '', final_content, flags=re.MULTILINE).strip()
        meta_match  = re.search(r'<META_DATA>(.*?)</META_DATA>', clean_text, re.S)
        body_match  = re.search(r'<HTML_BODY>(.*?)</HTML_BODY>',  clean_text, re.S)

        if not body_match:
            return {"index": index, "status": "파싱 에러(본문 없음)"}

        body     = body_match.group(1).strip()
        meta_raw = meta_match.group(1).strip() if meta_match else ""

        meta: dict = {}
        if meta_raw:
            for line in meta_raw.split('\n'):
                if ':' in line:
                    k, v = line.split(':', 1)
                    meta[k.strip().lower().replace(" ", "_")] = v.strip()

        # 메타 길이 검증 및 보정
        snippet_title       = _truncate_meta_text(meta.get('snippet_title', search_kw), 60)
        meta_description    = _truncate_meta_text(meta.get('meta_description', ''),      155)
        focus_keyword       = meta.get('focus_keyword',    search_kw)
        secondary_keywords  = meta.get('secondary_keywords', '')

        # 4) 썸네일 생성 및 업로드 (Featured Image용)
        thumb_name = f"thumb_{index}_{int(time.time())}.png"
        create_thumbnail(snippet_title or search_kw, focus_keyword or search_kw, thumb_name)
        thumb_id, thumb_url = upload_media_to_wordpress(thumb_name)

        try:
            os.remove(thumb_name)
        except OSError:
            pass

        # 5) 본문 최상단 썸네일 삽입 (thumb_url None 체크 포함)
        if thumb_url:
            body = (
                f'<div style="text-align:center; margin-bottom:35px;">'
                f'<img src="{thumb_url}" alt="{focus_keyword} 안내" '
                f'style="max-width:100%; border-radius:15px; box-shadow:0 10px 20px rgba(0,0,0,0.1);">'
                f'</div>\n'
            ) + body

        # 6) 외부 링크는 LLM이 본문 내에 정부기관 링크를 직접 삽입하므로 별도 추가 불필요

        # 7) WordPress 발행 or 테스트 모드 로컬 저장
        if TEST_MODE:
            # ── 테스트 모드: 로컬 파일로 저장 ──────────────────
            test_dir = "test_output"
            os.makedirs(test_dir, exist_ok=True)

            # HTML 본문 저장
            html_path = os.path.join(test_dir, f"test_{index}_body.html")
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(f"""<!DOCTYPE html><html lang='ko'><head>
<meta charset='UTF-8'>
<title>{snippet_title}</title>
<style>body{{font-family:sans-serif;max-width:860px;margin:40px auto;padding:0 20px;line-height:1.8;}}
h1{{color:#0f172a;}} h2{{color:#1e3a5f;border-bottom:2px solid #3b82f6;padding-bottom:8px;}}
table{{border-collapse:collapse;width:100%;}} td,th{{border:1px solid #ddd;padding:8px;}}
</style></head><body>\n{body}\n</body></html>""")

            # 메타 정보 저장
            meta_path = os.path.join(test_dir, f"test_{index}_meta.txt")
            with open(meta_path, 'w', encoding='utf-8') as f:
                f.write(f"제목: {snippet_title}\n")
                f.write(f"메타설명: {meta_description}\n")
                f.write(f"포커스 키워드: {focus_keyword}\n")
                f.write(f"보조 키워드: {secondary_keywords}\n")
                f.write(f"썸네일: {thumb_name} (로컬 저장됨)\n")

            # 썸네일은 test_output 폴더에 복사
            import shutil
            test_thumb = os.path.join(test_dir, f"test_{index}_thumb.png")
            try:
                shutil.copy(thumb_name, test_thumb)
            except Exception:
                pass

            print(f"\n📁 테스트 결과 저장 위치: {os.path.abspath(test_dir)}/")
            print(f"   HTML 본문  : test_{index}_body.html")
            print(f"   메타 정보  : test_{index}_meta.txt")
            print(f"   썸네일     : test_{index}_thumb.png")

        else:
            # ── 운영 모드: WordPress 실제 업로드 ───────────────
            token = base64.b64encode(f"{WP_USER}:{WP_APP_PW}".encode()).decode()
            post_meta = {
                'rank_math_focus_keyword': focus_keyword,
                'rank_math_description':   meta_description,
            }
            if meta.get('canonical_url'):
                post_meta['canonical_url'] = meta['canonical_url']
            if meta.get('schema_type'):
                post_meta['schema_type'] = meta['schema_type']

            post_data = {
                'title':          snippet_title or search_kw,
                'content':        body,
                'status':         'draft',
                'featured_media': thumb_id if thumb_id else 0,
                'meta':           post_meta,
            }

            res = requests.post(
                f"{WP_URL}/posts",
                headers={'Authorization': f'Basic {token}', 'Content-Type': 'application/json'},
                json=post_data,
                timeout=30
            )
            res.raise_for_status()

        # 8) 사일로 주제 추출 (✅ FIX #7: 정규식 따옴표 이스케이프 + [^>]* 수정)
        new_topics = [
            re.sub(r'<[^>]+>', '', t).strip()
            for t in re.findall(r"""<a\s+[^>]*href=["']#["'][^>]*>(.*?)</a>""", body, re.I)
        ]

        return {"index": index, "status": "성공(임시저장)", "new_topics": new_topics, "body": body}

    except Exception as e:
        return {"index": index, "status": f"실패: {e}"}


# ==========================================
# 5. 메인 컨트롤러 (멀티스레딩 & 안전 저장)
# ==========================================

if __name__ == "__main__":   # ✅ FIX #7: _name_ → __name__
    try:
        df = pd.read_excel(EXCEL_FILE)

        # ✅ FIX: 컬럼이 있어도 없어도 fillna+astype(str)로 강제 object 타입 지정
        #         (Excel 로딩 시 빈 컬럼이 float64로 추론되어 문자열 할당 불가 문제 해결)
        for col in ['업로드상태', '업로드시간', '본문원고']:
            if col not in df.columns:
                df[col] = ""
            df[col] = df[col].fillna("").astype(str)

        pending = df[
            ~df['업로드상태'].astype(str).str.contains('성공', na=False)
            & df[COLUMN_NAME].notna()
        ]

        if TEST_MODE:
            print("\n🧪 [테스트 모드] WordPress 업로드 없이 로컬 파일로만 저장합니다.")
            print(f"   첫 번째 항목 1개만 처리합니다.")
            pending = pending.head(1)   # 첫 번째 키워드 1개만

        print(f"🚀 총 {len(pending)}개의 포스팅 작업을 시작합니다. (스레드: 1)")
        start_total = time.time()

        # ✅ 개선: 로컬 LLM 동시 실행은 VRAM 부담 → max_workers=1 권장
        with ThreadPoolExecutor(max_workers=1) as executor:
            futures = {
                executor.submit(process_single_row, idx, row[COLUMN_NAME]): idx
                for idx, row in pending.iterrows()
            }

            for future in as_completed(futures):
                result = future.result()
                idx    = result["index"]

                df.at[idx, '업로드상태'] = result["status"]
                df.at[idx, '업로드시간'] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                if "body" in result:
                    df.at[idx, '본문원고'] = result["body"]

                # 새 주제 추가 (Silo)
                if result.get("new_topics"):
                    for nt in result["new_topics"]:
                        if nt and nt not in df[COLUMN_NAME].values:
                            new_row = pd.DataFrame([{COLUMN_NAME: nt, '업로드상태': '대기'}])
                            df = pd.concat([df, new_row], ignore_index=True)

                print(f"  ✓ [{idx}] 처리 완료: {result['status']}")

                # 다음 포스트가 있을 경우에만 랜덤 대기 (테스트 모드 제외)
                remaining = sum(1 for f in futures if not f.done())
                if remaining > 0 and not TEST_MODE:
                    delay = random.uniform(POST_DELAY_MIN, POST_DELAY_MAX)
                    print(f"  ⏳ 다음 발행까지 {delay:.0f}초 대기 중... (남은 포스트: {remaining}개)")
                    time.sleep(delay)

        elapsed = time.time() - start_total
        print(f"\n⏱️  총 소요 시간: {elapsed/60:.1f}분 ({elapsed:.0f}초)")

        # ✅ 개선 #9: Excel 저장은 루프 완료 후 1회만 실행 (성능 개선)
        df.to_excel(EXCEL_FILE, index=False)
        print("\n✨ 모든 작업이 완료되었습니다. 워드프레스 '임시글'을 확인하세요.")

    except Exception as e:
        print(f"❌ 메인 루프 에러: {e}")
