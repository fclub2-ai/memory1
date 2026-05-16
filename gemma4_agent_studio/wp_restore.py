"""
wp_restore.py
백업된 JSON 파일로 워드프레스 포스트 원문 복원

사용법:
  # 특정 파일 복원
  python wp_restore.py --file backups/post_2122_20260513_113007.json

  # backups/ 폴더 전체 목록 확인 (복원 안 함)
  python wp_restore.py --list

  # 특정 포스트 ID의 최신 백업으로 복원
  python wp_restore.py --post-id 2122
"""
import argparse
import json
import os
import requests
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime

load_dotenv()
WP_URL          = os.getenv("WP_URL", "").rstrip("/")
WP_USER         = os.getenv("WP_USER", "")
WP_APP_PASSWORD = os.getenv("WP_APP_PASSWORD", "")
BACKUP_DIR      = Path(__file__).parent / "backups"


def _wp_auth():
    return (WP_USER, WP_APP_PASSWORD)


def list_backups():
    """backups/ 폴더의 모든 백업 파일 출력"""
    files = sorted(BACKUP_DIR.glob("post_*.json"), reverse=True)
    if not files:
        print("❌ 백업 파일이 없습니다.")
        return

    print(f"\n{'#':<4} {'파일명':<45} {'포스트ID':<10} {'백업일시'}")
    print("-" * 85)
    for i, f in enumerate(files, 1):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            backed_at = data.get("backed_up_at", "")[:19].replace("T", " ")
            print(f"{i:<4} {f.name:<45} {data.get('post_id', '?'):<10} {backed_at}")
        except Exception:
            print(f"{i:<4} {f.name:<45} (파싱 실패)")
    print()


def restore_from_file(backup_file: Path, dry_run: bool = False):
    """지정된 백업 JSON 파일로 워드프레스 포스트 복원"""
    if not backup_file.exists():
        print(f"❌ 파일을 찾을 수 없습니다: {backup_file}")
        return False

    data = json.loads(backup_file.read_text(encoding="utf-8"))
    post_id      = data["post_id"]
    url          = data["url"]
    original_html = data["original_html"]
    backed_at    = data.get("backed_up_at", "")[:19].replace("T", " ")

    print(f"\n📄 복원 대상 정보")
    print(f"  포스트 ID : {post_id}")
    print(f"  URL       : {url}")
    print(f"  백업 일시 : {backed_at}")
    print(f"  원문 길이 : {len(original_html):,}자")

    if dry_run:
        print("\n🟡 DRY-RUN: 실제 복원은 하지 않습니다.")
        return True

    confirm = input("\n⚠️  정말 복원하시겠습니까? (yes 입력): ").strip().lower()
    if confirm != "yes":
        print("❌ 취소되었습니다.")
        return False

    try:
        resp = requests.post(
            f"{WP_URL}/wp-json/wp/v2/posts/{post_id}",
            auth=_wp_auth(),
            json={"content": original_html},
            timeout=30,
        )
        if resp.status_code == 200:
            print(f"✅ 포스트 {post_id} 복원 완료!")
            return True
        else:
            print(f"❌ 복원 실패: {resp.status_code}")
            print(resp.text[:300])
    except Exception as e:
        print(f"❌ 오류 발생: {e}")
    return False


def restore_by_post_id(post_id: int, dry_run: bool = False):
    """특정 포스트 ID의 가장 최신 백업으로 복원"""
    files = sorted(BACKUP_DIR.glob(f"post_{post_id}_*.json"), reverse=True)
    if not files:
        print(f"❌ 포스트 ID {post_id}의 백업 파일이 없습니다.")
        return False

    latest = files[0]
    print(f"📂 최신 백업 파일: {latest.name}")
    return restore_from_file(latest, dry_run)


def main():
    parser = argparse.ArgumentParser(description="워드프레스 포스트 원문 복원 도구")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--list",    action="store_true",    help="백업 파일 목록 출력")
    group.add_argument("--file",    type=str,               help="복원할 백업 JSON 파일 경로")
    group.add_argument("--post-id", type=int,               help="복원할 포스트 ID (최신 백업 자동 선택)")
    parser.add_argument("--dry-run", action="store_true",   help="실제 복원 없이 테스트")
    args = parser.parse_args()

    if args.list:
        list_backups()
    elif args.file:
        restore_from_file(Path(args.file), args.dry_run)
    elif args.post_id:
        restore_by_post_id(args.post_id, args.dry_run)


if __name__ == "__main__":
    main()
