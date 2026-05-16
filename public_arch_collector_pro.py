import customtkinter as ctk
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import threading
import sys
import os
import ollama
import requests
import pandas as pd
from datetime import datetime
import time
import json
from bs4 import BeautifulSoup
from urllib.parse import quote
import queue

# ==========================================
# 1. 디자인 테마 설정
# ==========================================
ctk.set_appearance_mode("Dark")  # 기본을 다크 모드로 설정하여 세련된 느낌 강조
ctk.set_default_color_theme("blue")

CONFIG_FILE = "config.json"

def load_config():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return {"naver_client_id": "", "naver_client_secret": "", "model": "gemma4:e4b", "save_path": os.getcwd()}

def save_config(config):
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=4, ensure_ascii=False)

# ==========================================
# 3. 데이터 수집 핵심 엔진
# ==========================================
def fetch_full_article(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        res = requests.get(url, headers=headers, timeout=10)
        res.encoding = 'utf-8'
        soup = BeautifulSoup(res.text, 'html.parser')
        
        article_body = soup.select_one("#dic_area, #articeBody, .newsct_article, .article-body, article")
        if article_body:
            for script in article_body(["script", "style", "em"]): script.decompose()
            return article_body.get_text(separator=' ', strip=True)[:4000]
        else:
            return " ".join([p.text.strip() for p in soup.find_all('p') if len(p.text.strip()) > 15])[:4000]
    except: return ""

def analyze_and_extract(model_name, title, full_text):
    prompt = f"""당신은 공공건축 프로젝트 분석 전문가입니다. 기사를 읽고 정보를 추출하세요.
    제목: {title}\n본문: {full_text}
    반드시 JSON 형식으로만 응답하세요. 정보가 없으면 "확인불가"로 적으세요.
    {{
        "is_relevant": "공공건물 신축/건립/설계 소식이면 true, 아니면 false",
        "city": "시/군/구", "project_title": "건물명", "completion_date": "준공 예정일",
        "area": "규모/면적", "cost": "총사업비", "team": "담당부서",
        "birdseye_view": "조감도 언급", "firm": "건축사무소"
    }}"""
    try:
        response = ollama.generate(model=model_name, prompt=prompt, format="json")
        return json.loads(response['response'])
    except: return None

def fetch_all_news(region, base_keyword, client_id, client_secret, max_results=15):
    news_list = []
    query = f"{region} {base_keyword}".strip() 
    enc_query = quote(query)
    
    # Naver
    if client_id and client_secret:
        try:
            n_res = requests.get("https://openapi.naver.com/v1/search/news.json", 
                                 headers={"X-Naver-Client-Id": client_id, "X-Naver-Client-Secret": client_secret}, 
                                 params={"query": query, "display": max_results, "sort": "sim"}).json()
            for item in n_res.get('items', []): 
                news_list.append({"title": item['title'].replace("<b>", "").replace("</b>", ""), "link": item['link'], "desc": item.get('description', ''), "source": "Naver"})
        except Exception as e: 
            print(f"네이버 뉴스 수집 오류: {e}")
            pass
    
    # Google
    try:
        g_soup = BeautifulSoup(requests.get(f"https://news.google.com/rss/search?q={enc_query}&hl=ko&gl=KR", timeout=5).content, 'xml')
        for item in g_soup.find_all('item')[:max_results]: 
            desc = item.description.text if item.description else ""
            news_list.append({"title": item.title.text, "link": item.link.text, "desc": desc, "source": "Google"})
    except: pass

    # Daum
    try:
        d_soup = BeautifulSoup(requests.get(f"https://search.daum.net/search?w=news&q={enc_query}", headers={"User-Agent": "Mozilla/5.0"}, timeout=5).text, 'html.parser')
        for li in d_soup.select("ul.list_news > li")[:max_results]:
            title_tag = li.select_one("a.tit_main")
            desc_tag = li.select_one("p.desc")
            if title_tag:
                news_list.append({"title": title_tag.text, "link": title_tag['href'], "desc": desc_tag.text if desc_tag else "", "source": "Daum"})
    except: pass

    # Bing
    try:
        b_soup = BeautifulSoup(requests.get(f"https://www.bing.com/news/search?q={enc_query}&format=RSS", headers={"User-Agent": "Mozilla/5.0"}, timeout=5).content, 'xml')
        for item in b_soup.find_all('item')[:max_results]: 
            desc = item.description.text if item.description else ""
            news_list.append({"title": item.title.text, "link": item.link.text, "desc": desc, "source": "Bing"})
    except: pass

    return news_list

# ==========================================
# 4. 모던 GUI 설계 (가독성 최적화 버전)
# ==========================================
class ModernApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("🏢 공공건축 데이터 통합 수집 대시보드 Pro")
        self.geometry("1000x800")
        self.is_running = False 
        self.log_queue = queue.Queue()
        self.config = load_config()
        self.final_dataframe = None

        # [폰트 정의] - 윈도우에서 가장 깔끔한 맑은 고딕 적용
        font_family = "맑은 고딕"
        self.font_header = ctk.CTkFont(family=font_family, size=24, weight="bold")
        self.font_title = ctk.CTkFont(family=font_family, size=15, weight="bold")
        self.font_main = ctk.CTkFont(family=font_family, size=13)
        self.font_btn = ctk.CTkFont(family=font_family, size=15, weight="bold")
        self.font_log = ctk.CTkFont(family=font_family, size=12)

        self.setup_ui()
        self.poll_log_queue()
        
        # 주기적으로 stdout 큐 폴링을 위해 sys.stdout 리다이렉트
        sys.stdout = TextRedirector(self.log_queue)

    def setup_ui(self):
        # 탭 뷰 설정
        self.tabview = ctk.CTkTabview(self, width=950, height=750)
        self.tabview.pack(padx=20, pady=(10, 20), fill="both", expand=True)

        self.tab_crawling = self.tabview.add("🚀 수집 실행")
        self.tab_settings = self.tabview.add("⚙️ 설정")
        self.tab_results = self.tabview.add("📊 수집 결과")

        self.setup_crawling_tab()
        self.setup_settings_tab()
        self.setup_results_tab()
        
        # 상태 바
        self.status_var = ctk.StringVar(value="대기 중...")
        self.status_bar = ctk.CTkLabel(self, textvariable=self.status_var, anchor="w", font=self.font_main)
        self.status_bar.pack(side="bottom", fill="x", padx=20, pady=(0, 10))

    def setup_settings_tab(self):
        # API 키 설정
        frame_api = ctk.CTkFrame(self.tab_settings, corner_radius=12, fg_color=("gray92", "gray16"), border_width=1, border_color=("gray85", "gray25"))
        frame_api.pack(fill="x", padx=20, pady=10, ipadx=10, ipady=10)
        
        ctk.CTkLabel(frame_api, text="🔑 Naver API 설정", font=self.font_title).pack(anchor="w", padx=15, pady=(10, 5))
        
        self.entry_client_id = ctk.CTkEntry(frame_api, placeholder_text="Client ID", width=400, font=self.font_main)
        self.entry_client_id.insert(0, self.config.get("naver_client_id", ""))
        self.entry_client_id.pack(anchor="w", padx=15, pady=5)
        
        self.entry_client_secret = ctk.CTkEntry(frame_api, placeholder_text="Client Secret", width=400, font=self.font_main, show="*")
        self.entry_client_secret.insert(0, self.config.get("naver_client_secret", ""))
        self.entry_client_secret.pack(anchor="w", padx=15, pady=5)

        # 모델 및 경로 설정
        frame_model = ctk.CTkFrame(self.tab_settings, corner_radius=12, fg_color=("gray92", "gray16"), border_width=1, border_color=("gray85", "gray25"))
        frame_model.pack(fill="x", padx=20, pady=10, ipadx=10, ipady=10)
        
        ctk.CTkLabel(frame_model, text="🤖 기본 설정", font=self.font_title).pack(anchor="w", padx=15, pady=(10, 5))
        
        models = ["gemma4:e4b"]
        try:
            models = [m.model for m in ollama.list().models]
        except:
            pass
            
        self.combo_model = ctk.CTkComboBox(frame_model, values=models, width=400, font=self.font_main)
        if self.config.get("model") in models:
            self.combo_model.set(self.config.get("model"))
        self.combo_model.pack(anchor="w", padx=15, pady=5)

        # 저장 경로
        path_frame = ctk.CTkFrame(frame_model, fg_color="transparent")
        path_frame.pack(fill="x", padx=15, pady=5)
        self.entry_save_path = ctk.CTkEntry(path_frame, width=300, font=self.font_main)
        self.entry_save_path.insert(0, self.config.get("save_path", os.getcwd()))
        self.entry_save_path.pack(side="left", padx=(0, 5))
        ctk.CTkButton(path_frame, text="경로 변경", command=self.change_save_path, width=80).pack(side="left")

        ctk.CTkButton(self.tab_settings, text="💾 설정 저장", font=self.font_btn, command=self.save_settings).pack(pady=20)

    def change_save_path(self):
        dir_path = filedialog.askdirectory(initialdir=self.entry_save_path.get())
        if dir_path:
            self.entry_save_path.delete(0, "end")
            self.entry_save_path.insert(0, dir_path)

    def save_settings(self):
        self.config["naver_client_id"] = self.entry_client_id.get().strip()
        self.config["naver_client_secret"] = self.entry_client_secret.get().strip()
        self.config["model"] = self.combo_model.get()
        self.config["save_path"] = self.entry_save_path.get().strip()
        save_config(self.config)
        messagebox.showinfo("저장 완료", "설정이 저장되었습니다.")

    def setup_crawling_tab(self):
        # --------------------------------------------------
        # 카드 1: 검색 설정 영역
        # --------------------------------------------------
        self.card_settings = ctk.CTkFrame(self.tab_crawling, corner_radius=12, fg_color=("gray92", "gray16"), border_width=1, border_color=("gray85", "gray25"))
        self.card_settings.pack(fill="x", pady=(0, 10), ipadx=10, ipady=10)

        self.lbl_keyword = ctk.CTkLabel(self.card_settings, text="🔍 기본 검색 키워드", font=self.font_title)
        self.lbl_keyword.pack(anchor="w", padx=15, pady=(10, 5))
        self.entry_keyword = ctk.CTkEntry(self.card_settings, placeholder_text="예: 공공건축 신축 건립", height=35, font=self.font_main)
        self.entry_keyword.insert(0, "공공건축 신축 건립")
        self.entry_keyword.pack(fill="x", padx=15, pady=(0, 10))

        self.lbl_custom_reg = ctk.CTkLabel(self.card_settings, text="✍️ 추가 수동 입력 (특정 사업명/지역명 쉼표 구분)", font=self.font_title)
        self.lbl_custom_reg.pack(anchor="w", padx=15, pady=(5, 5))
        self.entry_custom_reg = ctk.CTkEntry(self.card_settings, placeholder_text="예: 화성시 꿈탄탄이음터", height=35, font=self.font_main)
        self.entry_custom_reg.pack(fill="x", padx=15, pady=(0, 10))

        # --------------------------------------------------
        # 카드 2: 지역 선택 영역
        # --------------------------------------------------
        self.card_region = ctk.CTkFrame(self.tab_crawling, corner_radius=12, fg_color=("gray92", "gray16"), border_width=1, border_color=("gray85", "gray25"))
        self.card_region.pack(fill="x", pady=(0, 10), ipadx=10, ipady=10)

        self.lbl_region = ctk.CTkLabel(self.card_region, text="📍 광역 자치단체 선택 (17개 시/도)", font=self.font_title)
        self.lbl_region.pack(anchor="w", padx=15, pady=(10, 10))
        
        self.region_inner_frame = ctk.CTkFrame(self.card_region, fg_color="transparent")
        self.region_inner_frame.pack(fill="x", padx=15, pady=(0, 5))

        self.regions = [
            "서울특별시", "부산광역시", "대구광역시", "인천광역시", "광주광역시", "대전광역시", 
            "울산광역시", "세종특별자치시", "경기도", "강원특별자치도", "충청북도", "충청남도", 
            "전북특별자치도", "전라남도", "경상북도", "경상남도", "제주특별자치도"
        ]
        self.check_vars = {}
        for i, reg in enumerate(self.regions):
            var = ctk.BooleanVar(value=False)
            self.check_vars[reg] = var
            chk = ctk.CTkCheckBox(self.region_inner_frame, text=reg, variable=var, font=self.font_main)
            chk.grid(row=i//6, column=i%6, sticky="w", padx=10, pady=5)

        # --------------------------------------------------
        # 카드 3: 실행 컨트롤 및 로그 영역
        # --------------------------------------------------
        self.card_controls = ctk.CTkFrame(self.tab_crawling, fg_color="transparent")
        self.card_controls.pack(fill="both", expand=True)

        self.btn_frame = ctk.CTkFrame(self.card_controls, fg_color="transparent")
        self.btn_frame.pack(fill="x", pady=(0, 10))
        
        # 버튼 색상을 세련된 블루/레드 파스텔 톤으로 변경
        self.btn_start = ctk.CTkButton(self.btn_frame, text="▶ 데이터 수집 시작", fg_color="#1F6AA5", hover_color="#144870", 
                                       font=self.font_btn, height=45, corner_radius=8, command=self.start_thread)
        self.btn_start.pack(side="left", expand=True, padx=(0, 5), fill="x")

        self.btn_stop = ctk.CTkButton(self.btn_frame, text="⏹ 작업 취소", fg_color="#C25A5A", hover_color="#9C4444", 
                                      font=self.font_btn, height=45, corner_radius=8, state="disabled", command=self.stop_crawling)
        self.btn_stop.pack(side="right", expand=True, padx=(5, 0), fill="x")

        # 통계 표시 영역
        self.stats_frame = ctk.CTkFrame(self.card_controls, fg_color="transparent")
        self.stats_frame.pack(fill="x", pady=(0, 5))
        self.lbl_stats = ctk.CTkLabel(self.stats_frame, text="총 발견: 0 | 관련 데이터: 0 | 중복 제외: 0", font=self.font_main)
        self.lbl_stats.pack(anchor="w")

        self.progress_bar = ctk.CTkProgressBar(self.card_controls, height=14, progress_color="#2FA572")
        self.progress_bar.pack(fill="x", pady=(0, 10))
        self.progress_bar.set(0)

        self.textbox = ctk.CTkTextbox(self.card_controls, height=150, font=self.font_log)
        self.textbox.pack(fill="both", expand=True)

    def setup_results_tab(self):
        # Treeview 스타일 설정 (다크모드 대응)
        style = ttk.Style(self)
        style.theme_use("default")
        style.configure("Treeview", 
                        background="#2b2b2b",
                        foreground="white",
                        rowheight=25,
                        fieldbackground="#2b2b2b",
                        font=("맑은 고딕", 11))
        style.configure("Treeview.Heading", font=("맑은 고딕", 12, "bold"), background="#404040", foreground="white")
        style.map('Treeview', background=[('selected', '#1f538d')])

        self.tree_frame = ctk.CTkFrame(self.tab_results)
        self.tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        columns = ("지역", "시/군/구", "타이틀", "준공예정일", "면적", "총공사비", "담당팀", "출처")
        self.tree = ttk.Treeview(self.tree_frame, columns=columns, show='headings', selectmode="browse")
        
        for col in columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=100, anchor="center")
        
        # 특정 컬럼 너비 조정
        self.tree.column("타이틀", width=200, anchor="w")
        self.tree.column("지역", width=80)
        self.tree.column("시/군/구", width=80)
        
        # 스크롤바
        vsb = ttk.Scrollbar(self.tree_frame, orient="vertical", command=self.tree.yview)
        hsb = ttk.Scrollbar(self.tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscrollcommand=vsb.set, xscrollcommand=hsb.set)
        
        self.tree.grid(column=0, row=0, sticky='nsew')
        vsb.grid(column=1, row=0, sticky='ns')
        hsb.grid(column=0, row=1, sticky='ew')
        
        self.tree_frame.grid_columnconfigure(0, weight=1)
        self.tree_frame.grid_rowconfigure(0, weight=1)

        self.btn_export = ctk.CTkButton(self.tab_results, text="엑셀 다시 저장", font=self.font_btn, command=self.export_excel, state="disabled")
        self.btn_export.pack(pady=10)

    def export_excel(self):
        if self.final_dataframe is not None:
            save_dir = self.config.get("save_path", os.getcwd())
            filename = os.path.join(save_dir, f"공공건축_수집결과_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
            try:
                self.final_dataframe.to_excel(filename, index=False)
                messagebox.showinfo("저장 완료", f"파일이 저장되었습니다:\n{filename}")
            except Exception as e:
                messagebox.showerror("저장 오류", f"파일 저장 중 오류가 발생했습니다:\n{e}")

    def poll_log_queue(self):
        # 큐에서 메시지를 꺼내서 텍스트박스에 추가
        while not self.log_queue.empty():
            msg = self.log_queue.get()
            self.textbox.insert("end", msg)
            self.textbox.see("end")
        self.after(100, self.poll_log_queue)

    def start_thread(self):
        self.is_running = True
        self.btn_start.configure(state="disabled", text="⏳ 수집 진행 중...")
        self.btn_stop.configure(state="normal")
        self.progress_bar.set(0)
        self.textbox.delete("0.0", "end")
        
        # 트리뷰 초기화
        for item in self.tree.get_children():
            self.tree.delete(item)
            
        threading.Thread(target=self.run_crawling, daemon=True).start()

    def stop_crawling(self):
        self.is_running = False
        print("\n[알림] 사용자가 작업을 취소했습니다. 중지 중...")
        self.btn_stop.configure(state="disabled", text="정지 중...")

    def update_stats(self, total, relevant, duplicates):
        self.after(0, lambda: self.lbl_stats.configure(text=f"총 발견: {total} | 관련 데이터: {relevant} | 중복 제외: {duplicates}"))
        self.after(0, lambda: self.status_var.set(f"수집 중... (관련 데이터 {relevant}건 확인됨)"))

    def run_crawling(self):
        try:
            selected = [reg for reg, var in self.check_vars.items() if var.get()]
            custom_input = self.entry_custom_reg.get().strip()
            if custom_input:
                selected.extend([x.strip() for x in custom_input.split(",") if x.strip()])
            
            base_keyword = self.entry_keyword.get().strip()

            if not selected:
                if base_keyword: selected = [""]
                else:
                    print("\n[경고] 수집할 지역이나 검색어를 최소 1개 이상 입력해주세요!")
                    self.after(0, self.reset_buttons)
                    return

            print(f"========== 쿼드 엔진(Quad Engine) 가동 ==========")
            print(f"[{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}] 데이터 수집 시작 (모델: {self.config.get('model')})\n")
            
            final_data = []
            seen_urls = set()
            total_regions = len(selected)
            total_found = 0
            relevant_count = 0
            duplicate_count = 0

            for idx, province in enumerate(selected):
                if not self.is_running: break 

                display_name = province if province else "전체/수동입력"
                print(f"▶ [{display_name}] 지역 기사 탐색 중... ", end="")
                
                all_news = fetch_all_news(province, base_keyword, self.config.get("naver_client_id"), self.config.get("naver_client_secret"))
                print(f"{len(all_news)}건 발견.")
                
                for item in all_news:
                    if not self.is_running: break
                    
                    # URL 중복 제거 로직
                    if item['link'] in seen_urls:
                        duplicate_count += 1
                        continue
                    seen_urls.add(item['link'])
                    total_found += 1
                    
                    full_text = fetch_full_article(item['link'])
                    if len(full_text) < 50: full_text = item.get('desc', '')
                    if len(full_text) < 20: continue
                    
                    details = analyze_and_extract(self.config.get('model'), item['title'], full_text)
                    if details and str(details.get('is_relevant')).lower() == 'true':
                        row = {
                            "출처": item['source'], "지역": province, "시/군/구": details.get('city', ''), 
                            "타이틀": details.get('project_title', ''), "준공예정일": details.get('completion_date', ''), 
                            "면적": details.get('area', ''), "총공사비": details.get('cost', ''), "담당팀": details.get('team', ''), 
                            "조감도": details.get('birdseye_view', ''), "url": item['link'], "건축사무소": details.get('firm', ''),
                            "기사 원제목": item['title']
                        }
                        final_data.append(row)
                        relevant_count += 1
                        print("★", end="", flush=True)
                        
                        # Treeview 실시간 업데이트
                        tree_vals = (row["지역"], row["시/군/구"], row["타이틀"], row["준공예정일"], row["면적"], row["총공사비"], row["담당팀"], row["출처"])
                        self.after(0, lambda v=tree_vals: self.tree.insert("", "end", values=v))
                        
                    self.update_stats(total_found, relevant_count, duplicate_count)
                    time.sleep(0.5) # API 과부하 방지
                    
                print("\n")
                self.after(0, lambda i=idx, t=total_regions: self.progress_bar.set((i + 1) / t))

            if final_data:
                df = pd.DataFrame(final_data)
                df.sort_values(by=['지역', '타이틀'], inplace=True)
                df.insert(0, '번호', range(1, len(df) + 1))
                
                column_order = ["번호", "출처", "지역", "시/군/구", "타이틀", "준공예정일", "면적", "총공사비", "담당팀", "조감도", "url", "건축사무소", "기사 원제목"]
                df = df[column_order]
                
                self.final_dataframe = df
                self.after(0, lambda: self.btn_export.configure(state="normal"))

                save_dir = self.config.get("save_path", os.getcwd())
                filename = os.path.join(save_dir, f"공공건축_수집결과_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx")
                df.to_excel(filename, index=False)
                
                print(f"==================================================")
                print(f"✅ [성공] 엑셀 파일 저장 완료: {filename}")
                print(f"==================================================")
                if self.is_running:
                    self.after(0, lambda f=filename: messagebox.showinfo("수집 완료", f"데이터 수집이 완료되었습니다!\n\n저장 위치: {f}"))
            else:
                print("\n[알림] 조건에 맞는 기사를 찾지 못했습니다.")
                self.after(0, lambda: messagebox.showinfo("결과 없음", "조건에 맞는 공공건축 기사를 찾지 못했습니다."))
                
        except Exception as e:
            print(f"\n[오류 발생] 작업을 수행하는 도중 에러가 발생했습니다:\n{e}")
        finally:
            self.after(0, self.reset_buttons)

    def reset_buttons(self):
        self.btn_start.configure(state="normal", text="▶ 데이터 수집 시작")
        self.btn_stop.configure(state="disabled", text="⏹ 작업 취소")
        self.is_running = False
        self.status_var.set("대기 중...")

class TextRedirector:
    def __init__(self, queue):
        self.queue = queue
    def write(self, str):
        self.queue.put(str)
    def flush(self): pass

if __name__ == "__main__":
    app = ModernApp()
    app.mainloop()
