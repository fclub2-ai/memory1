# 📝 SEO 자동 포스팅 스크립트 (`seo_auto_poster.py`)

> Ollama(gemma4:e4b) + Serper + Tavily API를 활용한 워드프레스 SEO 블로그 자동화 파이프라인

---

## 📋 목차

1. [개요](#개요)
2. [전체 동작 흐름](#전체-동작-흐름)
3. [설치 요구사항](#설치-요구사항)
4. [환경 변수 설정 (.env)](#환경-변수-설정-env)
5. [파일 구조](#파일-구조)
6. [기능 상세](#기능-상세)
7. [실행 방법](#실행-방법)
8. [Excel 키워드 파일 형식](#excel-키워드-파일-형식)
9. [생성되는 포스트 구조](#생성되는-포스트-구조)
10. [주요 수정 이력](#주요-수정-이력)
11. [트러블슈팅](#트러블슈팅)

---

## 개요

`keywords.xlsx`에 작성된 주제 목록을 읽어, 각 주제에 대해:

1. **Serper API**로 구글 추천질문(PAA) 수집
2. **Tavily API**로 실시간 팩트/요약 수집
3. **Ollama(gemma4:e4b)** 로 SEO 최적화 HTML 본문 자동 생성
4. **PIL**로 1080×1080 썸네일 이미지 생성 (SCDream9.otf 폰트)
5. **WordPress REST API**로 임시글(draft) 자동 업로드

---

## 전체 동작 흐름

```
keywords.xlsx
     │
     ▼
[키워드 추출] ──────────────────────────────────────────┐
     │                                                  │
     ▼                                                  │
[Serper API] ─── 구글 추천질문(PAA) ──┐                 │
[Tavily API] ─── 실시간 팩트/요약 ───┤                 │
                                      ▼                 │
                               [Ollama LLM]             │
                               gemma4:e4b               │
                               1500~2500단어             │
                               SEO HTML 생성            │
                                      │                 │
                    ┌─────────────────┤                 │
                    │                 │                 │
                    ▼                 ▼                 │
             [META_DATA]        [HTML_BODY]             │
             파싱·검증          본문 파싱                │
                    │                 │                 │
                    └────────┬────────┘                 │
                             │                         │
                             ▼                         │
                      [썸네일 생성]                     │
                      PIL + SCDream9.otf               │
                      1080×1080 PNG                    │
                             │                         │
                             ▼                         │
                   [WordPress 업로드]                   │
                   미디어 + 포스트(draft)               │
                             │                         │
                             ▼                         │
                    keywords.xlsx 상태 업데이트 ─────────┘
```

---

## 설치 요구사항

### Python 패키지

```bash
pip install requests pandas pillow python-dotenv tenacity openpyxl
```

### 외부 서비스

| 서비스 | 용도 | 비고 |
|--------|------|------|
| [Ollama](https://ollama.com) | 로컬 LLM 실행 | `gemma4:e4b` 모델 필요 |
| [Serper.dev](https://serper.dev) | 구글 PAA 수집 | API Key 필요 |
| [Tavily](https://tavily.com) | 실시간 팩트 수집 | API Key 필요 |
| WordPress | 포스트 업로드 | 앱 비밀번호 필요 |

### Ollama 모델 설치

```bash
ollama pull gemma4:e4b
```

---

## 환경 변수 설정 (.env)

스크립트와 **같은 폴더**에 `.env` 파일을 생성하세요.

```dotenv
# Tavily API
TAVILY_API_KEY=tvly-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# Serper API
SERPER_API_KEY=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx

# WordPress
WP_URL=https://your-blog.com/wp-json/wp/v2
WP_USER=your_username
WP_APP_PW=xxxx xxxx xxxx xxxx xxxx xxxx
```

> ⚠️ **보안 주의**: `.env` 파일을 Git에 절대 커밋하지 마세요.  
> WordPress 앱 비밀번호는 **관리자 → 프로필 → 앱 비밀번호**에서 생성할 수 있습니다.

---

## 파일 구조

```
📁 작업 폴더/
├── seo_auto_poster.py   # 메인 스크립트
├── keywords.xlsx        # 포스팅 주제 목록
├── SCDream9.otf         # 썸네일용 한글 폰트 (필수)
├── .env                 # API 키·크리덴셜 (Git 제외)
└── .gitignore
```

---

## 기능 상세

### 1. 썸네일 생성 (`create_thumbnail`)

- **크기**: 1080 × 1080 px (인스타그램/블로그 최적)
- **폰트**: `SCDream9.otf` → 없으면 `malgun.ttf` → 기본폰트 순으로 폴백
- **레이아웃**:
  - 상단 연회색 띠 + 우측 파란 포인트
  - 중앙 제목 (60px, 최대 14자/줄)
  - 제목 하단 파란 구분선
  - 하단 키워드 태그 박스 (파란 배경)

### 2. 데이터 수집 (`get_seo_and_facts`)

| API | 수집 내용 | 옵션 |
|-----|-----------|------|
| Serper | 구글 추천질문(PAA) | `gl=kr`, `hl=ko` |
| Tavily | 실시간 AI 요약 + 참고 기사 3건 | `days=90` (최근 90일) |

수집된 날짜(`📅 수집 날짜`)도 팩트 데이터에 포함되어 LLM에 전달됩니다.

### 3. 콘텐츠 생성 (`generate_optimized_post`)

**프롬프트 핵심 지시사항**:
- 분량: **1,500~2,500단어** 이상 (짧은 글 불허)
- 오늘 날짜 명시 → 연도 오류 방지
- 필수 섹션 6개 (순서 강제):

  | 섹션 | 내용 |
  |------|------|
  | H1 | focus_keyword 포함 제목 |
  | 도입부 | 60~100단어, 문제 공감 + 혜택 |
  | 핵심 요약 박스 | 파란 테두리 박스 + 3~5개 포인트 |
  | H2 본문 (5개 이상) | 개념·이유·단계·비교표·실전예시·전문가팁·주의사항 |
  | FAQ | 구글 PAA 기반, 답변 2~4문단 + JSON-LD |
  | 마무리 + CTA | 핵심 정리 + 행동 유도 |

- 외부 링크: 국내 정부/공공기관 사이트 자동 선택 (15개 기관 풀)
- 내부 링크: 미삽입 (설정에 따라 변경 가능)

**Ollama 옵션**:

```python
{"num_ctx": 16384}  # 긴 글 생성을 위한 컨텍스트 확장
```

### 4. WordPress 업로드

- **상태**: `draft` (임시글) — 검토 후 수동 발행
- **대표 이미지**: `featured_media` ID로 설정
- **본문 상단**: 썸네일 이미지 `<img>` 태그 삽입
- **RankMath 메타 필드**: `focus_keyword`, `meta_description` 자동 설정

---

## 실행 방법

```bash
# 1. 폴더 이동
cd C:\Users\fclub\WORDPERSSAUTO

# 2. Ollama 실행 확인
ollama list   # gemma4:e4b 있는지 확인

# 3. 스크립트 실행
python seo_auto_poster.py
```

**실행 결과 예시**:

```
🚀 총 5개의 포스팅 작업을 시작합니다. (스레드: 1)
  ✓ [0] 처리 완료: 성공(임시저장)
  ✓ [1] 처리 완료: 성공(임시저장)
  ...
✨ 모든 작업이 완료되었습니다. 워드프레스 '임시글'을 확인하세요.
```

---

## Excel 키워드 파일 형식

`keywords.xlsx`의 필수/자동생성 컬럼:

| 컬럼명 | 설명 | 입력방식 |
|--------|------|----------|
| `주제` | 포스팅 주제 (1줄 또는 여러 줄) | **직접 입력** |
| `업로드상태` | 처리 결과 (`성공(임시저장)` / `실패: ...`) | 자동 |
| `업로드시간` | 처리 완료 시각 | 자동 |
| `본문원고` | 생성된 HTML 본문 전체 | 자동 |

> 💡 `업로드상태`에 `성공`이 포함된 행은 **재처리하지 않습니다** (중복 방지).

---

## 생성되는 포스트 구조

```html
<!-- 본문 상단: 썸네일 이미지 -->
<div style="text-align:center; margin-bottom:35px;">
  <img src="[썸네일 URL]" alt="[키워드] 안내" ...>
</div>

<!-- H1 제목 -->
<h1>...</h1>

<!-- 도입부 -->
<p>...</p>

<!-- 핵심 요약 박스 (파란 테두리) -->
<div style="background:#f0f4ff;border-left:4px solid #3b82f6;padding:16px;">
  <ul>...</ul>
</div>

<!-- H2 본문 섹션들 -->
<h2>개념/정의 설명</h2>
<h2>필요한 이유</h2>
<h2>단계별 방법</h2>  <!-- <ol> 포함 -->
<h2>비교표</h2>       <!-- <table> 포함 -->
<h2>실전 예시</h2>
<h2>전문가 팁</h2>    <!-- 주황 테두리 박스 -->
<h2>주의사항</h2>

<!-- FAQ -->
<h2>자주 묻는 질문</h2>
<h3>질문1</h3> ... <h3>질문2</h3> ...

<!-- FAQ JSON-LD -->
<script type="application/ld+json">...</script>

<!-- 마무리 요약 + CTA -->
<h2>마무리</h2>
```

---

## 주요 수정 이력

| 버전 | 수정 내용 |
|------|-----------|
| v1.0 | 최초 작성 |
| v1.1 | `t_bbox` 인덱스 오류 수정, `paa = ]` → `[]` 수정 |
| v1.2 | `__name__` 오타 수정, `_truncate_meta_text` 반환값 수정 |
| v1.3 | Excel dtype float64 오류 수정 (`fillna + astype(str)`) |
| v1.4 | SCDream9.otf 폰트 적용, 썸네일 디자인 개선 |
| v1.5 | Tavily `days=90` 추가, 프롬프트에 오늘 날짜 명시 |
| v1.6 | 외부 링크 → 국내 정부기관 자동 선택, 내부 링크 제거 |
| v1.7 | 분량 1500~2500단어, 필수 섹션 강화, `num_ctx=16384` |

---

## 트러블슈팅

### ❌ `WP_APP_PW 환경변수가 설정되지 않았습니다`
→ `.env` 파일에 `WP_APP_PW=xxxx xxxx xxxx xxxx xxxx xxxx` 추가

### ❌ `Invalid value '...' for dtype 'float64'`
→ Excel의 `업로드시간` 컬럼 타입 문제. 스크립트가 자동 수정함 (`fillna + astype(str)`)

### ❌ 썸네일에 글자가 깨짐
→ `SCDream9.otf` 파일이 스크립트와 같은 폴더에 있는지 확인

### ❌ Ollama 응답 없음 / 타임아웃
→ `ollama serve` 실행 확인, `LLM_TIMEOUT = 600` 값 증가

### ❌ 본문이 짧게 생성됨
→ `num_ctx` 값이 모델의 VRAM 한계를 초과할 경우 `12288`로 낮춰 시도

### ❌ 결과물에 2024년이 나옴
→ Tavily `days=90` + 프롬프트 날짜 명시로 대부분 해결됨.  
   그래도 발생하면 팩트데이터에 최신 통계를 직접 넣어 제공

---

*최종 수정: 2026-05-13*
