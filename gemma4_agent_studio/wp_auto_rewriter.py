"""
wp_auto_rewriter.py
워드프레스 + Gemma 4 자동화 리라이팅 파이프라인

사용법:
  python wp_auto_rewriter.py --csv Table.csv
  python wp_auto_rewriter.py --csv Table.csv --dry-run
"""
import argparse
import csv
import json
import os
import re
import sqlite3
import time
import logging
from datetime import datetime
from pathlib import Path

import ollama
import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv
import markdown as md_lib

# ── 환경 설정 로드 ─────────────────────────────────────────
load_dotenv()
WP_URL          = os.getenv("WP_URL", "").rstrip("/")
WP_USER         = os.getenv("WP_USER", "")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "")
GSC_SITE_URL    = os.getenv("GSC_SITE_URL", "")
GSC_KEY_FILE    = os.getenv("GOOGLE_SERVICE_ACCOUNT_KEY", "service_account_key.json")
DELAY_SECONDS   = int(os.getenv("DELAY_SECONDS", "30"))
MIN_CHAR_COUNT  = int(os.getenv("MIN_CHAR_COUNT", "500"))
DRY_RUN_ENV     = os.getenv("DRY_RUN", "false").lower() == "true"

BASE_MODEL   = "gemma4:e4b"
DB_PATH      = Path(__file__).parent / "rewrite_history.db"
BACKUP_DIR   = Path(__file__).parent / "backups"
REPORT_PATH  = Path(__file__).parent / "wp_rewrite_report.html"

# ── 로거 ────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(Path(__file__).parent / "rewriter.log", encoding="utf-8"),
    ],
)
log = logging.getLogger(__name__)


# ============================================================
# 1. DB 초기화
# ============================================================
def init_db():
    con = sqlite3.connect(DB_PATH)
    con.execute("""
        CREATE TABLE IF NOT EXISTS history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            url         TEXT UNIQUE,
            post_id     INTEGER,
            status      TEXT,
            orig_chars  INTEGER,
            new_chars   INTEGER,
            processed_at TEXT
        )
    """)
    con.commit()
    return con


def is_already_processed(con, url: str) -> bool:
    row = con.execute("SELECT id FROM history WHERE url=? AND status='success'", (url,)).fetchone()
    return row is not None


def save_history(con, url, post_id, status, orig_chars, new_chars):
    con.execute(
        """INSERT OR REPLACE INTO history (url, post_id, status, orig_chars, new_chars, processed_at)
           VALUES (?,?,?,?,?,?)""",
        (url, post_id, status, orig_chars, new_chars, datetime.now().isoformat()),
    )
    con.commit()


# ============================================================
# 2. GSC CSV 파싱
# ============================================================
def parse_gsc_csv(csv_path: str) -> list[str]:
    """구글 서치 콘솔에서 내보낸 CSV에서 URL 목록 추출"""
    urls = []
    with open(csv_path, encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for row in reader:
            # 첫 번째 컬럼이 URL인 경우 (GSC CSV 형식)
            url = list(row.values())[0].strip()
            if url.startswith("http"):
                urls.append(url)
    log.info(f"CSV에서 {len(urls)}개 URL 파싱 완료")
    return urls


# ============================================================
# 3. 워드프레스 API
# ============================================================
def _wp_auth():
    return (WP_USER, WP_APP_PASSWORD)


def get_post_by_url(url: str) -> dict | None:
    """URL로 워드프레스 포스트 조회"""
    slug = url.rstrip("/").split("/")[-1]
    try:
        resp = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"slug": slug, "_fields": "id,link,content,title"},
            timeout=15,
        )
        if resp.status_code == 200 and resp.json():
            return resp.json()[0]
        # slug 매칭 실패 시 search 시도
        resp2 = requests.get(
            f"{WP_URL}/wp-json/wp/v2/posts",
            params={"search": slug, "_fields": "id,link,content,title"},
            timeout=15,
        )
        posts = resp2.json()
        for p in posts:
            if p.get("link", "").rstrip("/") == url.rstrip("/"):
                return p
    except Exception as e:
        log.error(f"WP API 조회 실패 ({url}): {e}")
    return None


def update_post(post_id: int, html_content: str, dry_run: bool) -> bool:
    if dry_run:
        log.info(f"[DRY-RUN] 포스트 {post_id} 업데이트 생략")
        return True
    try:
        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
            auth=_wp_auth(),
            json={"content": html_content},
            timeout=30,
        )
        if resp.status_code == 200:
            log.info(f"✅ 포스트 {post_id} 업데이트 완료")
            return True
        log.error(f"포스트 업데이트 실패 ({post_id}): {resp.status_code} {resp.text[:200]}")
    except Exception as e:
        log.error(f"포스트 업데이트 예외 ({post_id}): {e}")
    return False


# ============================================================
# 4. 원문 백업
# ============================================================
def backup_original(post_id: int, url: str, content_html: str):
    BACKUP_DIR.mkdir(exist_ok=True)
    backup = {
        "post_id": post_id,
        "url": url,
        "backed_up_at": datetime.now().isoformat(),
        "original_html": content_html,
    }
    path = BACKUP_DIR / f"post_{post_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    path.write_text(json.dumps(backup, ensure_ascii=False, indent=2), encoding="utf-8")
    log.info(f"원문 백업: {path.name}")


# ============================================================
# 5. 품질 사전 진단
# ============================================================
def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    return soup.get_text(separator=" ", strip=True)


def needs_rewrite(text: str) -> bool:
    return len(text) < MIN_CHAR_COUNT


# ============================================================
# 6. Gemma AI 3단계 파이프라인 (Headless)
# ============================================================
AGENT_DEFS = [
    {
        "model": "writer-bot",
        "system": (
            "너는 전문 IT/생활정보 블로거야. "
            "독자가 이해하기 쉬운 비유를 사용하고 서론-본론-결론 구조로 글을 써줘. "
            "내용이 얄팍하면 구글에서 색인이 생성되지 않으므로 반드시 충분한 깊이와 분량으로 작성해."
        ),
    },
    {
        "model": "editor-bot",
        "system": (
            "너는 냉철한 편집장이야. "
            "글의 논리적 오류와 맞춤법을 검수하고 수정 제안을 반영해줘."
        ),
    },
    {
        "model": "seo-bot",
        "system": (
            "너는 SEO 전문가야. "
            "구글의 '크롤링됨 - 현재 색인이 생성되지 않음' 패널티를 피하도록 "
            "독창성과 정보의 깊이를 극대화하고, 키워드 배치를 최적화하여 "
            "완벽한 마크다운 형식으로 최종 정리해줘."
        ),
    },
]


def _ensure_agents():
    """에이전트 모델이 없으면 생성"""
    installed = [m.model for m in ollama.list().models]
    for agent in AGENT_DEFS:
        name = agent["model"]
        if not any(name == m or name == m.split(":")[0] for m in installed):
            log.info(f"에이전트 생성 중: {name}")
            ollama.create(model=name, from_=BASE_MODEL, system=agent["system"])


def _call_agent_headless(model: str, prompt: str) -> str:
    """Ollama 에이전트를 UI 없이 호출하고 전체 응답 반환"""
    full = ""
    stream = ollama.chat(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        stream=True,
    )
    for chunk in stream:
        delta = chunk.message.content
        if delta:
            full += delta
    # <think> 태그 제거
    full = re.sub(r"(?:<\|think\|>|<think>).*?(?:<\|/think\|>|</think>)", "", full, flags=re.DOTALL).strip()
    return full


def run_pipeline(topic: str, original_text: str, keywords: str = "") -> str:
    """3단계 AI 파이프라인 실행 → 최종 마크다운 반환"""
    _ensure_agents()

    current = (
        f"주제: {topic}\n"
        f"타겟 키워드: {keywords}\n"
        f"기존 원문:\n{original_text}\n\n"
        "위 원문은 구글 검색엔진에서 '크롤링됨 - 현재 색인이 생성되지 않음' 상태로 누락된 글입니다. "
        "단순 요약이 아닌, 독창적이고 깊이 있는 고품질 포스트로 완전히 재작성(리라이팅)해주세요. "
        "전문적인 통찰을 더하고 가독성을 높여 검색 엔진이 선호하는 글로 만들어야 합니다."
    )

    for i, agent in enumerate(AGENT_DEFS):
        log.info(f"  [{i+1}/3] {agent['model']} 실행 중...")
        if i > 0:
            current = (
                f"이전 에이전트의 결과물:\n\n{current}\n\n"
                f"위 내용을 바탕으로 당신의 역할을 수행해주세요.\n"
                f"타겟 키워드: {keywords}"
            )
        current = _call_agent_headless(agent["model"], current)
        log.info(f"  [{i+1}/3] 완료 ({len(current)}자)")

    return current


# ============================================================
# 7. GSC 색인 재요청
# ============================================================
def request_indexing(url: str):
    """Google Search Console URL Inspection API로 색인 재요청"""
    if not os.path.exists(GSC_KEY_FILE):
        log.warning(f"GSC 서비스 계정 키 파일 없음 ({GSC_KEY_FILE}) — 색인 재요청 건너뜀")
        return

    try:
        from google.oauth2 import service_account
        from googleapiclient.discovery import build

        creds = service_account.Credentials.from_service_account_file(
            GSC_KEY_FILE,
            scopes=["https://www.googleapis.com/auth/webmasters"],
        )
        service = build("searchconsole", "v1", credentials=creds)
        result = service.urlInspection().index().inspect(
            body={"inspectionUrl": url, "siteUrl": GSC_SITE_URL}
        ).execute()
        verdict = result.get("urlInspectionResult", {}).get("indexStatusResult", {}).get("verdict", "UNKNOWN")
        log.info(f"  GSC 색인 재요청 완료 ({url}) → verdict: {verdict}")
    except Exception as e:
        log.error(f"  GSC 색인 재요청 실패 ({url}): {e}")


# ============================================================
# 8. HTML 리포트 생성
# ============================================================
def generate_report(results: list[dict]):
    success = [r for r in results if r["status"] == "success"]
    fail = [r for r in results if r["status"] != "success"]

    rows = ""
    for r in results:
        color = "#22c55e" if r["status"] == "success" else "#ef4444"
        rows += f"""
        <tr>
          <td><a href="{r['url']}" target="_blank">{r['url'][:60]}…</a></td>
          <td style="text-align:center">{r['orig_chars']:,  if isinstance(r.get('orig_chars'), int) else '-'}</td>
          <td style="text-align:center">{r['new_chars']:,   if isinstance(r.get('new_chars'),  int) else '-'}</td>
          <td style="text-align:center;color:{color};font-weight:bold">{r['status']}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<title>WP 리라이팅 결과 리포트</title>
<style>
  body{{font-family:'Segoe UI',sans-serif;background:#0f172a;color:#e2e8f0;margin:0;padding:2rem}}
  h1{{color:#818cf8;margin-bottom:.5rem}}
  .meta{{color:#94a3b8;font-size:.9rem;margin-bottom:2rem}}
  .cards{{display:flex;gap:1rem;margin-bottom:2rem}}
  .card{{background:#1e293b;border-radius:12px;padding:1.2rem 2rem;flex:1;text-align:center}}
  .card .num{{font-size:2.5rem;font-weight:700;margin:.3rem 0}}
  .card .label{{color:#94a3b8;font-size:.85rem}}
  table{{width:100%;border-collapse:collapse;background:#1e293b;border-radius:12px;overflow:hidden}}
  th{{background:#334155;padding:.8rem 1rem;text-align:left;font-size:.85rem;color:#94a3b8}}
  td{{padding:.8rem 1rem;border-bottom:1px solid #334155;font-size:.9rem}}
  tr:last-child td{{border-bottom:none}}
  a{{color:#818cf8;text-decoration:none}}
</style></head><body>
<h1>🤖 WP 리라이팅 자동화 결과 리포트</h1>
<div class="meta">생성일시: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}</div>
<div class="cards">
  <div class="card"><div class="num" style="color:#818cf8">{len(results)}</div><div class="label">전체 처리</div></div>
  <div class="card"><div class="num" style="color:#22c55e">{len(success)}</div><div class="label">성공</div></div>
  <div class="card"><div class="num" style="color:#ef4444">{len(fail)}</div><div class="label">실패/건너뜀</div></div>
</div>
<table>
  <thead><tr><th>URL</th><th>원문 글자수</th><th>리라이팅 후</th><th>상태</th></tr></thead>
  <tbody>{rows}</tbody>
</table>
</body></html>"""

    REPORT_PATH.write_text(html, encoding="utf-8")
    log.info(f"📊 HTML 리포트 생성: {REPORT_PATH}")


# ============================================================
# 9. 메인 실행
# ============================================================
def main():
    parser = argparse.ArgumentParser(description="워드프레스 자동 리라이팅 파이프라인")
    parser.add_argument("--csv",      required=True, help="구글 서치 콘솔에서 내보낸 CSV 파일 경로")
    parser.add_argument("--dry-run",  action="store_true", help="실제 WP 업데이트 없이 테스트")
    parser.add_argument("--keywords", default="", help="타겟 키워드 (쉼표 구분)")
    parser.add_argument("--delay",    type=int, default=DELAY_SECONDS, help=f"URL 간 대기 시간(초, 기본:{DELAY_SECONDS})")
    args = parser.parse_args()

    dry_run = args.dry_run or DRY_RUN_ENV
    if dry_run:
        log.info("🟡 DRY-RUN 모드: 실제 워드프레스 업데이트를 하지 않습니다.")

    if not WP_URL or not WP_USER or not WP_APP_PASSWORD:
        log.error(".env 파일에 WP_URL, WP_USER, WP_APP_PASSWORD를 설정하세요.")
        return

    con = init_db()
    urls = parse_gsc_csv(args.csv)
    results = []

    for idx, url in enumerate(urls, 1):
        log.info(f"\n[{idx}/{len(urls)}] 처리 중: {url}")

        # 중복 체크
        if is_already_processed(con, url):
            log.info("  → 이미 처리된 URL, 건너뜀")
            results.append({"url": url, "status": "skipped"})
            continue

        # 워드프레스 원문 조회
        post = get_post_by_url(url)
        if not post:
            log.warning("  → 워드프레스 포스트를 찾을 수 없음")
            results.append({"url": url, "status": "not_found"})
            save_history(con, url, None, "not_found", 0, 0)
            continue

        post_id = post["id"]
        title   = post["title"]["rendered"]
        raw_html = post["content"]["rendered"]
        orig_text = html_to_text(raw_html)
        orig_chars = len(orig_text)
        log.info(f"  포스트 ID: {post_id}, 제목: {title[:40]}, 원문: {orig_chars}자")

        # 원문 백업
        backup_original(post_id, url, raw_html)

        # 품질 진단
        if not needs_rewrite(orig_text):
            log.info(f"  → 원문이 {orig_chars}자로 충분. 리라이팅 불필요, 건너뜀")
            results.append({"url": url, "status": "sufficient", "orig_chars": orig_chars})
            save_history(con, url, post_id, "sufficient", orig_chars, orig_chars)
            continue

        # AI 파이프라인
        log.info("  → AI 3단계 파이프라인 실행...")
        try:
            rewritten_md = run_pipeline(title, orig_text, args.keywords)
        except Exception as e:
            log.error(f"  AI 파이프라인 실패: {e}")
            results.append({"url": url, "status": "ai_error", "orig_chars": orig_chars})
            save_history(con, url, post_id, "ai_error", orig_chars, 0)
            continue

        new_chars = len(rewritten_md)
        log.info(f"  리라이팅 완료: {orig_chars}자 → {new_chars}자")

        # 마크다운 → HTML
        new_html = md_lib.markdown(rewritten_md, extensions=["extra", "tables"])

        # 워드프레스 업데이트
        ok = update_post(post_id, new_html, dry_run)
        status = "success" if ok else "update_failed"

        # GSC 색인 재요청
        if ok and not dry_run:
            request_indexing(url)

        save_history(con, url, post_id, status, orig_chars, new_chars)
        results.append({"url": url, "status": status, "orig_chars": orig_chars, "new_chars": new_chars})

        # 다음 URL 처리 전 대기
        if idx < len(urls):
            log.info(f"  {args.delay}초 대기 중...")
            time.sleep(args.delay)

    # 리포트 생성
    generate_report(results)

    success_count = sum(1 for r in results if r["status"] == "success")
    log.info(f"\n✅ 전체 완료: {len(results)}개 처리, {success_count}개 성공")
    log.info(f"📊 리포트: {REPORT_PATH}")


if __name__ == "__main__":
    main()
