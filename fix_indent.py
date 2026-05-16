import sys

file_path = "c:/Users/fclub/WORDPERSSAUTO/auto_blog_final.py"

with open(file_path, "r", encoding="utf-8") as f:
    lines = f.readlines()

start_idx = -1
end_idx = -1

for i, line in enumerate(lines):
    if "# 7) WordPress 실제 업로드" in line:
        start_idx = i
    if "# 8) 사일로 주제 추출" in line:
        end_idx = i
        break

if start_idx != -1 and end_idx != -1:
    for i in range(start_idx, end_idx):
        if lines[i].startswith("    "):
            lines[i] = lines[i][4:]
            
    with open(file_path, "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"Fixed indentation for lines {start_idx+1} to {end_idx}")
else:
    print(f"Could not find start or end. Start: {start_idx}, End: {end_idx}")
