import argparse
import json
from datetime import date
from pathlib import Path

from .answer import PolicyAnswerService
from .policies import PolicyCorpus


def main() -> None:
    parser = argparse.ArgumentParser(description="Sourced company-policy Q&A")
    parser.add_argument("question")
    parser.add_argument("--as-of", type=date.fromisoformat, default=date.today())
    parser.add_argument("--corpus", type=Path, default=Path("fixtures/policies.json"))
    parser.add_argument("--model", help="enabled Anthropic model name")
    args = parser.parse_args()
    result = PolicyAnswerService(PolicyCorpus(args.corpus)).ask(args.question, args.as_of, args.model)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
