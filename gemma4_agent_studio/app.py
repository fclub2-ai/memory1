import streamlit as st
import ollama
import re
import uuid
import sqlite3
import subprocess
import sys
from pathlib import Path
from dotenv import dotenv_values

# ============================================================
# 페이지 설정 & 상수
# ============================================================
st.set_page_config(
    page_title="Gemma 4 Custom Agent Studio",
    layout="wide",
    page_icon="🤖",
)

BASE_MODEL = "gemma4:e4b"
ICON_OPTIONS = ["✍️", "🔍", "📈", "🤖", "🧠", "💡", "📝", "🔬", "🎯", "📊", "🗂️", "🌐"]


# ============================================================
# 유틸 함수
# ============================================================
def _make_agent(model_name: str, display_name: str, icon: str, system_prompt: str) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "model_name": model_name,
        "display_name": display_name,
        "icon": icon,
        "system_prompt": system_prompt,
        "enabled": True,
    }


def get_installed_models() -> list[str]:
    try:
        return [m.model for m in ollama.list().models]
    except Exception as e:
        st.sidebar.warning(f"Ollama 연결 실패: {e}")
        return []


def is_model_ready(model_name: str, installed: list[str]) -> bool:
    return any(model_name == m or model_name == m.split(":")[0] for m in installed)


def extract_think_and_result(content: str) -> tuple[str, str]:
    """<think>...</think> 또는 <|think|>...</|think|> 블록 추출"""
    pattern = r"(?:<\|think\|>|<think>)(.*?)(?:<\|/think\|>|</think>)"
    thoughts = re.findall(pattern, content, re.DOTALL)
    result = re.sub(pattern, "", content, flags=re.DOTALL).strip()
    return (thoughts[0].strip() if thoughts else ""), result


def create_agent(model_name: str, system_prompt: str) -> bool:
    try:
        ollama.create(model=model_name, from_=BASE_MODEL, system=system_prompt)
        return True
    except Exception as e:
        st.error(
            f"**{model_name}** 생성 실패: {e}\n\n"
            f"> 기반 모델 `{BASE_MODEL}` 설치 여부를 확인하세요."
        )
        return False


def call_agent(model_name: str, display_name: str, icon: str, prompt: str) -> str:
    """에이전트를 스트리밍 방식으로 호출하고 결과 반환"""
    label = f"{icon} {display_name}"
    with st.status(f"🤖 {label} 작업 중...", expanded=True) as status:
        placeholder = st.empty()
        full_content = ""
        try:
            stream = ollama.chat(
                model=model_name,
                messages=[{"role": "user", "content": prompt}],
                stream=True,
            )
            for chunk in stream:
                delta = chunk.message.content
                if delta:
                    full_content += delta
                    placeholder.markdown(full_content + " ▌")
            placeholder.empty()
        except Exception as e:
            st.error(f"**{label}** 호출 실패: {e}")
            status.update(label=f"❌ {label} 오류", state="error")
            return ""

        thought, result = extract_think_and_result(full_content)
        if thought:
            with st.expander(f"🧐 {label}의 분석 과정 (클릭하여 펼치기)"):
                st.markdown(thought)
        st.markdown(result)
        status.update(label=f"✅ {label} 완료", state="complete")
    return result


# ============================================================
# 세션 상태 초기화
# ============================================================
if "agents" not in st.session_state:
    st.session_state.agents = [
        _make_agent(
            "writer-bot", "작가 (Writer)", "✍️",
            "너는 전문 IT 기술 블로거야. "
            "독자가 이해하기 쉬운 비유를 사용해 서론-본론-결론 구조로 글을 써줘.",
        ),
        _make_agent(
            "editor-bot", "편집자 (Editor)", "🔍",
            "너는 냉철한 편집장이야. "
            "글의 논리적 오류와 맞춤법을 검수하고 수정 제안을 해줘. "
            "반드시 <think> 태그를 사용하여 사고 과정을 보여줘.",
        ),
        _make_agent(
            "seo-bot", "SEO 전문가", "📈",
            "너는 검색 엔진 최적화(SEO) 전문가야. "
            "글이 구글의 '크롤링됨 - 현재 색인이 생성되지 않음' 페널티를 받지 않도록 "
            "독창성과 정보의 깊이를 극대화하고, 키워드 배치를 최적화하여 완벽한 마크다운 형식으로 최종 정리해줘.",
        ),
    ]

if "final_draft" not in st.session_state:
    st.session_state.final_draft = ""

if "workflow_log" not in st.session_state:
    st.session_state.workflow_log = []  # list of (display_name, icon, content)

if "last_topic" not in st.session_state:
    st.session_state.last_topic = ""


# ============================================================
# 사이드바 — 에이전트 관리
# ============================================================
with st.sidebar:
    st.title("🛠️ 에이전트 관리")

    # 설치된 모델 목록 (1회 캐시)
    installed = get_installed_models()

    # ── 에이전트 카드 목록 ─────────────────────────────────
    st.subheader("🔗 파이프라인 순서")
    st.caption("↑↓ 순서 변경 · 이름·역할 수정 · 토글 비활성화 · 🗑️ 삭제")

    agents = st.session_state.agents

    for i, agent in enumerate(agents):
        aid = agent["id"]
        ready = is_model_ready(agent["model_name"], installed)
        badge = "✅" if ready else "⚠️"

        with st.expander(f"{badge} {agent['icon']} {agent['display_name']}", expanded=False):

            # 순서 변경 / 활성화 토글 / 삭제
            c1, c2, c3, c4 = st.columns([1, 1, 2, 1])
            with c1:
                if st.button("🔼", key=f"up_{aid}", disabled=(i == 0), help="위로 이동"):
                    agents[i], agents[i - 1] = agents[i - 1], agents[i]
                    st.rerun()
            with c2:
                if st.button("🔽", key=f"dn_{aid}", disabled=(i == len(agents) - 1), help="아래로 이동"):
                    agents[i], agents[i + 1] = agents[i + 1], agents[i]
                    st.rerun()
            with c3:
                agent["enabled"] = st.toggle("활성", value=agent["enabled"], key=f"en_{aid}")
            with c4:
                if st.button("🗑️", key=f"del_{aid}", help="에이전트 삭제"):
                    st.session_state.agents = [a for a in agents if a["id"] != aid]
                    st.rerun()

            # 아이콘
            icon_idx = ICON_OPTIONS.index(agent["icon"]) if agent["icon"] in ICON_OPTIONS else 0
            agent["icon"] = st.selectbox("아이콘", ICON_OPTIONS, index=icon_idx, key=f"icon_{aid}")

            # 표시 이름
            agent["display_name"] = st.text_input(
                "표시 이름", value=agent["display_name"], key=f"name_{aid}"
            )

            # Ollama 모델 이름
            agent["model_name"] = st.text_input(
                "Ollama 모델 이름",
                value=agent["model_name"],
                key=f"model_{aid}",
                help="변경 후 반드시 '업데이트' 버튼을 눌러주세요.",
            )

            # 시스템 프롬프트
            agent["system_prompt"] = st.text_area(
                "역할 지시 (System Prompt)",
                value=agent["system_prompt"],
                key=f"prompt_{aid}",
                height=120,
            )

    # 새 에이전트 추가
    if st.button("➕ 새 에이전트 추가", use_container_width=True):
        n = len(st.session_state.agents) + 1
        st.session_state.agents.append(
            _make_agent(
                f"custom-bot-{n}",
                f"새 에이전트 {n}",
                "🤖",
                "새로운 에이전트의 역할을 여기에 입력하세요.",
            )
        )
        st.rerun()

    st.divider()

    # 변경사항 적용
    if st.button("⚙️ 변경사항 적용 및 에이전트 업데이트", use_container_width=True, type="primary"):
        active = [a for a in st.session_state.agents if a["enabled"]]
        if not active:
            st.error("활성화된 에이전트가 없습니다.")
        else:
            with st.spinner(f"에이전트 생성 중... (기반 모델: `{BASE_MODEL}`)"):
                results = [create_agent(a["model_name"], a["system_prompt"]) for a in active]
            if all(results):
                st.success(f"✅ {len(results)}개 에이전트 업데이트 완료!")
            else:
                st.warning("일부 에이전트 설정에 실패했습니다. 오류 메시지를 확인하세요.")

    st.divider()

    # 콘텐츠 기획
    st.subheader("📝 콘텐츠 기획")
    topic = st.text_input("블로그 주제", placeholder="예) 2026 근로장려금 신청 방법")
    keywords = st.text_input("타겟 키워드 (쉼표 구분)", "근로장려금, 자격요건")
    crawled_text = st.text_area("기존 원문 (선택사항)", placeholder="구글에서 '크롤링됨 - 현재 색인이 생성되지 않음' 상태인 기존 포스트의 내용을 붙여넣으면 고품질로 리라이팅합니다.", height=150)

    active_agents = [a for a in st.session_state.agents if a["enabled"]]
    all_ready = bool(active_agents) and all(
        is_model_ready(a["model_name"], installed) for a in active_agents
    )
    can_start = all_ready and bool(topic)

    start_btn = st.button(
        "🚀 전체 공정 시작",
        use_container_width=True,
        disabled=not can_start,
        type="primary",
    )

    if not topic:
        st.info("주제를 입력해야 시작할 수 있습니다.")
    elif not active_agents:
        st.warning("활성화된 에이전트가 없습니다.")
    elif not all_ready:
        st.warning("⚠️ '변경사항 적용' 버튼으로 에이전트를 먼저 초기화하세요.")


# ============================================================
# 메인 화면
# ============================================================
st.title("🤖 Gemma 4 Custom Agent Studio")
st.caption("에이전트를 자유롭게 구성하고, 블로그 콘텐츠 생산 파이프라인을 직접 설계하세요.")

col_main, col_stats = st.columns([2, 1])

with col_main:
    tab1, tab2, tab3 = st.tabs(["🖋️ 워크플로우", "📝 최종 결과물", "🔁 자동화 관리"])

    with tab1:
        if start_btn:
            # 새 공정 시작 — 이전 결과 초기화
            st.session_state.workflow_log = []
            st.session_state.final_draft = ""
            st.session_state.last_topic = topic

            if crawled_text.strip():
                current_text = (
                    f"주제: {topic}\n"
                    f"타겟 키워드: {keywords}\n"
                    f"기존 원문:\n{crawled_text}\n\n"
                    "위 원문은 구글 검색엔진에서 '크롤링됨 - 현재 색인이 생성되지 않음' 상태로 누락된 글입니다. "
                    "이를 해결하기 위해 단순 요약이 아닌, 독창적이고 깊이 있는 고품질 포스트로 완전히 재작성(리라이팅)해주세요. "
                    "전문적인 통찰을 더하고 가독성을 높여 검색 엔진이 선호하는 글로 만들어야 합니다."
                )
            else:
                current_text = (
                    f"주제: {topic}\n"
                    f"타겟 키워드: {keywords}\n\n"
                    "위 주제로 구글에 잘 노출될 수 있는 고품질 블로그 글을 써줘. "
                    "내용이 얄팍하면 '색인이 생성되지 않음' 문제가 발생할 수 있으므로, 전문적이고 정보가 풍부한 글로 작성해야 해."
                )

            for i, agent in enumerate(active_agents):
                st.subheader(f"{i + 1}️⃣ {agent['icon']} {agent['display_name']}")

                if i == 0:
                    prompt = current_text
                else:
                    prev_name = active_agents[i - 1]["display_name"]
                    prompt = (
                        f"이전 에이전트({prev_name})의 결과물:\n\n{current_text}\n\n"
                        f"위 내용을 바탕으로 당신의 역할을 수행해주세요.\n"
                        f"타겟 키워드: {keywords}"
                    )

                result = call_agent(
                    agent["model_name"],
                    agent["display_name"],
                    agent["icon"],
                    prompt,
                )
                current_text = result
                st.session_state.workflow_log.append(
                    (agent["display_name"], agent["icon"], result)
                )

                if i < len(active_agents) - 1:
                    st.divider()

            st.session_state.final_draft = current_text
            st.success("🎉 전체 공정이 완료되었습니다! '최종 결과물' 탭을 확인하세요.")

        elif st.session_state.workflow_log:
            # 이전 공정 결과 재표시
            for i, (name, icon, content) in enumerate(st.session_state.workflow_log, 1):
                st.subheader(f"{i}️⃣ {icon} {name}")
                st.markdown(content)
                if i < len(st.session_state.workflow_log):
                    st.divider()
        else:
            st.info("👈 왼쪽 사이드바에서 에이전트를 구성하고 주제를 입력한 뒤 시작하세요.")

    with tab2:
        if st.session_state.final_draft:
            st.subheader("📄 최종 완성 글")
            st.markdown(st.session_state.final_draft)
            st.divider()
            st.subheader("📋 마크다운 원문 (복사용)")
            st.code(st.session_state.final_draft, language="markdown")

            fname = (
                f"blog_{st.session_state.last_topic[:20].replace(' ', '_')}.md"
                if st.session_state.last_topic
                else "blog_output.md"
            )
            st.download_button(
                label="⬇️ 마크다운 파일로 저장",
                data=st.session_state.final_draft.encode("utf-8"),
                file_name=fname,
                mime="text/markdown",
                use_container_width=True,
            )
        else:
            st.info("워크플로우를 완료하면 여기에 최종 결과물이 표시됩니다.")


# ── 오른쪽 통계 패널 ──────────────────────────────────────
with col_stats:
    st.subheader("📊 파이프라인 현황")

    active_agents = [a for a in st.session_state.agents if a["enabled"]]

    if active_agents:
        for i, agent in enumerate(active_agents):
            ready = is_model_ready(agent["model_name"], installed)
            badge = "✅" if ready else "⚠️"
            st.markdown(f"**{i + 1}. {agent['icon']} {agent['display_name']}**")
            st.caption(f"`{agent['model_name']}` {badge}")
            if i < len(active_agents) - 1:
                st.markdown("&nbsp;&nbsp;&nbsp;↓", unsafe_allow_html=True)
    else:
        st.info("활성화된 에이전트가 없습니다.")

    st.divider()
    st.subheader("📋 작업 정보")

    st.metric("활성 에이전트", f"{len(active_agents)}개")

    _topic = st.session_state.last_topic or topic
    if _topic:
        st.metric("주제", _topic[:22] + ("…" if len(_topic) > 22 else ""))

    kw_list = [k.strip() for k in keywords.split(",") if k.strip()]
    st.metric("타겟 키워드", f"{len(kw_list)}개")
    for kw in kw_list:
        st.markdown(f"- `{kw}`")

    if st.session_state.final_draft:
        st.divider()
        char_count = len(st.session_state.final_draft)
        st.metric("최종 글자 수", f"{char_count:,} 자")


# ============================================================
# 자동화 관리 탭 (tab3)
# ============================================================
_BASE_DIR = Path(__file__).parent
_ENV_PATH = _BASE_DIR / ".env"
_DB_PATH  = _BASE_DIR / "rewrite_history.db"
_REPORT   = _BASE_DIR / "wp_rewrite_report.html"
_SCRIPT   = _BASE_DIR / "wp_auto_rewriter.py"


def _load_env_safe() -> dict:
    if _ENV_PATH.exists():
        return dotenv_values(str(_ENV_PATH))
    return {}


def _test_wp_connection(cfg: dict) -> tuple[bool, str]:
    try:
        import requests as req
        url = cfg.get("WP_URL", "").rstrip("/")
        if not url:
            return False, "WP_URL이 설정되지 않았습니다."
        r = req.get(f"{url}/wp-json/wp/v2/posts?per_page=1", timeout=10)
        if r.status_code == 200:
            return True, f"✅ 연결 성공 ({url})"
        return False, f"❌ HTTP {r.status_code}"
    except Exception as e:
        return False, f"❌ 연결 실패: {e}"


def _load_history() -> list[dict]:
    if not _DB_PATH.exists():
        return []
    con = sqlite3.connect(_DB_PATH)
    rows = con.execute(
        "SELECT url, post_id, status, orig_chars, new_chars, processed_at FROM history ORDER BY processed_at DESC LIMIT 200"
    ).fetchall()
    con.close()
    return [
        {"URL": r[0], "포스트ID": r[1], "상태": r[2],
         "원문글자": r[3], "리라이팅후": r[4], "처리일시": r[5]}
        for r in rows
    ]


with tab3:
    st.subheader("🔁 자동화 파이프라인 관리")
    st.caption("구글 서치 콘솔 CSV를 업로드하면 색인 누락 포스트를 자동으로 리라이팅합니다.")

    # ── .env 설정 상태 ─────────────────────────────────────
    st.markdown("### ⚙️ 환경 설정 (.env)")
    cfg = _load_env_safe()

    if not _ENV_PATH.exists():
        st.warning("`.env` 파일이 없습니다. `.env.example`을 복사하여 `.env`로 저장하고 설정을 입력하세요.")
    else:
        wp_url  = cfg.get("WP_URL", "")
        wp_user = cfg.get("WP_USER", "")
        wp_pw   = cfg.get("WP_APP_PASSWORD", "")

        col_a, col_b, col_c = st.columns(3)
        col_a.metric("WP URL", wp_url[:30] + "…" if len(wp_url) > 30 else (wp_url or "미설정"))
        col_b.metric("WP 사용자", wp_user or "미설정")
        col_c.metric("앱 비밀번호", "설정됨 ✅" if wp_pw else "미설정 ❌")

        if st.button("🔌 워드프레스 연결 테스트", key="wp_test"):
            ok, msg = _test_wp_connection(cfg)
            (st.success if ok else st.error)(msg)

    st.divider()

    # ── CSV 업로드 & 실행 ──────────────────────────────────
    st.markdown("### 📂 GSC CSV 업로드 및 실행")
    st.info("구글 서치 콘솔 → 페이지 색인 생성 → '크롤링됨 - 현재 색인이 생성되지 않음' → 우측 상단 **[내보내기]** 버튼으로 CSV를 다운로드하세요.")

    uploaded = st.file_uploader("CSV 파일 선택", type=["csv"], key="gsc_csv")
    kw_auto  = st.text_input("타겟 키워드 (선택, 쉼표 구분)", key="kw_auto")
    dry_run  = st.toggle("🟡 Dry-Run 모드 (실제 업데이트 없이 테스트)", value=True, key="dry_run_toggle")
    delay    = st.slider("URL 간 대기 시간 (초)", 10, 120, 30, key="delay_slider")

    if uploaded and st.button("🚀 자동화 파이프라인 실행", type="primary", key="run_auto"):
        # CSV 임시 저장
        tmp_csv = _BASE_DIR / "gsc_upload.csv"
        tmp_csv.write_bytes(uploaded.read())

        cmd = [sys.executable, str(_SCRIPT), "--csv", str(tmp_csv), "--delay", str(delay)]
        if kw_auto.strip():
            cmd += ["--keywords", kw_auto.strip()]
        if dry_run:
            cmd.append("--dry-run")

        st.info(f"실행 명령: `{' '.join(cmd)}`")
        with st.spinner("파이프라인 실행 중... (백그라운드 처리, 로그는 `rewriter.log` 파일에서 확인)"):
            try:
                result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=3600)
                if result.returncode == 0:
                    st.success("✅ 파이프라인 완료!")
                else:
                    st.error("파이프라인 오류 발생")

                if result.stdout:
                    with st.expander("📋 실행 로그 보기"):
                        st.code(result.stdout[-3000:], language="text")
                if result.stderr:
                    with st.expander("⚠️ 오류 로그"):
                        st.code(result.stderr[-2000:], language="text")
            except subprocess.TimeoutExpired:
                st.warning("실행 시간이 초과되었습니다. `rewriter.log`를 확인하세요.")

        # 리포트 링크
        if _REPORT.exists():
            st.markdown(f"📊 [HTML 리포트 열기]({_REPORT.as_uri()})")

    st.divider()

    # ── 처리 이력 ──────────────────────────────────────────
    st.markdown("### 📜 처리 이력")
    history = _load_history()
    if history:
        st.caption(f"최근 200건 표시 | DB: `{_DB_PATH.name}`")
        # 상태별 색상 배지
        status_icon = {
            "success":      "✅ 성공",
            "skipped":      "⏭️ 건너뜀",
            "not_found":    "🔍 찾기 실패",
            "sufficient":   "📏 충분",
            "ai_error":     "🤖 AI 오류",
            "update_failed":"❌ 업데이트 실패",
        }
        for row in history:
            row["상태"] = status_icon.get(row["상태"], row["상태"])
        st.dataframe(history, use_container_width=True, hide_index=True)

        if st.button("🗑️ 이력 DB 초기화", key="clear_db"):
            if _DB_PATH.exists():
                _DB_PATH.unlink()
            st.success("이력 DB를 초기화했습니다.")
            st.rerun()
    else:
        st.info("처리 이력이 없습니다. 파이프라인을 실행하면 여기에 기록됩니다.")

    # ── 리포트 미리보기 ────────────────────────────────────
    if _REPORT.exists():
        st.divider()
        st.markdown("### 📊 최근 실행 리포트")
        with st.expander("리포트 미리보기"):
            st.components.v1.html(_REPORT.read_text(encoding="utf-8"), height=500, scrolling=True)

