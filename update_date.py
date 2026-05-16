import sys

file_path = r"c:\Users\fclub\WORDPERSSAUTO\auto_blog_final.py"

with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

# Replace date format
content = content.replace('%Y년 %m월 %d일', '%Y년 %m월')

# Replace prompt string
old_prompt = "⚠️ 중요: 오늘 날짜는 {today_str}입니다. 연도·날짜를 언급할 때 반드시 이 날짜를 기준으로 작성하세요."
new_prompt = "⚠️ 중요: 현재 시점은 {today_str}입니다. 연도나 날짜를 언급할 때 일(日)은 절대 쓰지 말고 반드시 이 '{today_str}'을 기준으로 작성하세요."
content = content.replace(old_prompt, new_prompt)

# Also replace in the other prompts if there's any slight variation
old_prompt_2 = "⚠️ 중요: 오늘 날짜는 {today_str}입니다. 연도·날짜를 언급할 때 반드시 이 날짜를 기준으로 작성하세요. 2024년 등 과거 연도를 현재인 것처럼 쓰지 마세요."
new_prompt_2 = "⚠️ 중요: 현재 시점은 {today_str}입니다. 연도나 날짜를 언급할 때 일(日)은 절대 쓰지 말고 반드시 이 '{today_str}'을 기준으로 작성하세요. 2024년 등 과거 연도를 현재인 것처럼 쓰지 마세요."
content = content.replace(old_prompt_2, new_prompt_2)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("Date formatting update completed.")
