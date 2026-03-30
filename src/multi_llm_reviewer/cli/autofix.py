import argparse
from multi_llm_reviewer.services import fix_service
from multi_llm_reviewer.core import config

def main():
    parser = argparse.ArgumentParser(
        description="Auto Fix Loop with Fallback & Role Strategy",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
--- Review Options ---
You can pass review options after '--' or as additional arguments, for example:
  -i, --issue ISSUE     GitHub issue number to fix
  -b, --base BASE       Base branch for review (default: main)
  --reviewers MODE      Reviewer mode (auto, all, etc. default: auto)
  --red-team            Use adversarial red-team review prompt
  spec                  Additional specification text

Example:
  python3 -m multi_llm_reviewer.cli.autofix --fixer copilot -- -b develop -i 123 --red-team
"""
    )
    parser.add_argument("--fixer", choices=config.FIXER_ORDER, default="gemini3pro", help="Primary fixer agent")
    
    # 残りの引数は review_all.py (review_service) に渡すためのものとして取得
    args, unknown_args = parser.parse_known_args()
    
    # unknown_args をパースして review_service 用の引数を準備
    review_parser = argparse.ArgumentParser(add_help=False)
    review_parser.add_argument("-i", "--issue")
    review_parser.add_argument("-b", "--base", default="main")
    review_parser.add_argument("--reviewers", default="auto")
    review_parser.add_argument("--red-team", action="store_true")
    review_parser.add_argument("spec", nargs="*")
    
    # '--' 以降をパース
    r_args, r_spec = review_parser.parse_known_args(unknown_args)
    
    review_params = {
        "issue": r_args.issue,
        "base": r_args.base,
        "mode": r_args.reviewers,
        "red_team": r_args.red_team,
        "spec": " ".join(r_args.spec + r_spec)
    }

    fix_service.run_auto_fix_loop(
        fixer_name=args.fixer,
        review_args=review_params
    )

if __name__ == "__main__":
    main()
