import argparse
import sys
from src.services import fix_service
from src.core import config

def main():
    parser = argparse.ArgumentParser(description="Auto Fix Loop with Fallback & Role Strategy", add_help=False)
    parser.add_argument("--fixer", choices=config.FIXER_ORDER, default="gemini3pro", help="Primary fixer agent")
    parser.add_argument("--help", action="store_true", help="Show help")
    
    # 残りの引数は review_all.py (review_service) に渡すためのものとして取得
    args, unknown_args = parser.parse_known_args()
    
    if args.help:
        parser.print_help()
        print("\n--- Review Options ---")
        print("You can pass review options after '--', for example:")
        print("  python3 -m src.cli.autofix --fixer copilot -- -b develop -i 123")
        sys.exit(0)

    # unknown_args をパースして review_service 用の引数を準備
    review_parser = argparse.ArgumentParser(add_help=False)
    review_parser.add_argument("-i", "--issue")
    review_parser.add_argument("-b", "--base", default="main")
    review_parser.add_argument("--reviewers", default="auto")
    review_parser.add_argument("spec", nargs="*")
    
    # '--' 以降をパース
    r_args, r_spec = review_parser.parse_known_args(unknown_args)
    
    review_params = {
        "issue": r_args.issue,
        "base": r_args.base,
        "mode": r_args.reviewers,
        "spec": " ".join(r_args.spec + r_spec)
    }

    fix_service.run_auto_fix_loop(
        fixer_name=args.fixer,
        review_args=review_params
    )

if __name__ == "__main__":
    main()

