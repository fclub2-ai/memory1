import sys

file_path = r"c:\Users\fclub\WORDPERSSAUTO\auto_blog_final.py"
with open(file_path, "r", encoding="utf-8") as f:
    content = f.read()

old_post_data = """post_data = {
            'title':          snippet_title or search_kw,
            'content':        body,
            'status':         'draft',
            'featured_media': thumb_id if thumb_id else 0,
            'meta':           post_meta,
            'tags':           wp_tag_ids,
        }"""

new_post_data = """post_data = {
            'title':          snippet_title or search_kw,
            'content':        body,
            'status':         'draft',
            'featured_media': thumb_id if thumb_id else 0,
            'meta':           post_meta,
            'tags':           wp_tag_ids,
            'slug':           _safe_slug(row_topic),  # 🔥 영문 슬러그 강제 지정
        }"""

content = content.replace(old_post_data, new_post_data)

old_wp_url = """res.raise_for_status()
        wp_post_url = res.json().get('link')"""

new_wp_url = """res.raise_for_status()
        # 🔥 임시저장(Draft) 상태라도 최종 확정된 URL(Slug 기반)을 조립해서 반환
        wp_res_json = res.json()
        wp_slug = wp_res_json.get('slug')
        domain = WP_URL.split('/wp-json')[0]
        wp_post_url = f"{domain}/{wp_slug}/"
        print(f"  👉 최종 발행 예정 URL: {wp_post_url}")"""

content = content.replace(old_wp_url, new_wp_url)

with open(file_path, "w", encoding="utf-8") as f:
    f.write(content)

print("URL slug fix applied!")
