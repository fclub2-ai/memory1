import sys

file_path = r"c:\Users\fclub\WORDPERSSAUTO\auto_blog_final.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

import re

# Find post_data
match = re.search(r"post_data\s*=\s*\{.*?\n\s*\}", content, re.DOTALL)
if match:
    print("Found post_data:")
    print(match.group(0))

# Find wp_post_url line
match2 = re.search(r"res\.raise_for_status\(\)\n\s*wp_post_url.*?\n", content, re.DOTALL)
if match2:
    print("\nFound wp_post_url line:")
    print(match2.group(0))
