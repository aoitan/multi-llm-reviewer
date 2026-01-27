import argparse
import sys
from src.services import review_service

def main():
    parser = argparse.ArgumentParser(description="Multi-LLM Code Reviewer")
    parser.add_argument("spec", nargs="*", help="Additional specification text")
    parser.add_argument("-i", "--issue", help="Issue number")
    parser.add_argument("-b", "--base", default="main", help="Base branch for comparison")
    parser.add_argument("--reviewers", default="auto", help="Review mode: 'auto', 'all', 'single', or comma-separated names")
    
    args = parser.parse_args()

    results = review_service.run_multi_llm_review(
        target_branch=args.base,
        issue_num=args.issue,
        mode=args.reviewers,
        spec_text=" ".join(args.spec)
    )

    success = all(r['success'] for r in results)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
