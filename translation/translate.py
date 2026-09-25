"""Book translator — PT-BR → English, with a whole-book Spiritist reviewer agent.

Usage:
    python translate.py run [--limit-chunks N] [--no-review] [--reset]
    python translate.py bible [--force]
    python translate.py review [--changed]
    python translate.py apply-corrections
    python translate.py build
    python translate.py status
"""

import argparse
import logging
import sys

from config import ConfigError, load_settings, require_credentials
from llm import FoundryLLM
from pipeline import Pipeline
from state import SourceChangedError


def _pipeline(args, needs_api: bool) -> Pipeline:
    settings = load_settings()
    if not settings.source_docx.exists():
        raise ConfigError(f"source document not found: {settings.source_docx}")
    llm = None
    if needs_api:
        require_credentials()
        llm = FoundryLLM(settings.model)
    return Pipeline(settings, llm, reset=getattr(args, "reset", False))


def cmd_run(args) -> None:
    p = _pipeline(args, needs_api=True)
    p.run_bible()
    p.run_chunks(limit=args.limit_chunks)
    if p.all_final() and not args.no_review and not p.state.data["book_review_done"]:
        result = p.run_book_review()
        print(f"\nBook review verdict: {result['overall_verdict']} — see {p.settings.book_review_md}")
    print("\n".join(p.build()))
    print("\n".join(p.status_lines()))


def cmd_bible(args) -> None:
    p = _pipeline(args, needs_api=True)
    p.run_bible(force=args.force)
    print(f"Book bible saved to {p.settings.state_dir / 'book_bible.json'}; "
          f"new terms added to {p.settings.review_md}")


def cmd_review(args) -> None:
    p = _pipeline(args, needs_api=True)
    result = p.run_book_review(changed_only=args.changed)
    if result:
        print(f"Book review verdict: {result['overall_verdict']} — see {p.settings.book_review_md} "
              f"and {p.settings.review_md}")


def cmd_apply(args) -> None:
    p = _pipeline(args, needs_api=True)
    terms, findings, affected = p.apply_corrections()
    if not terms and not findings:
        print("Nothing to apply: no corrections or accepted findings in the review file.")
        return
    print(f"Applied {terms} term corrections and {findings} reviewer findings; "
          f"updated chunks: {', '.join(affected)}")
    print("\n".join(p.build()))
    print("Run `python translate.py review --changed` to have the reviewer re-read the changed chapters.")


def cmd_build(args) -> None:
    print("\n".join(_pipeline(args, needs_api=False).build()))


def cmd_status(args) -> None:
    print("\n".join(_pipeline(args, needs_api=False).status_lines()))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="bible → translate every chunk → book review → build")
    run.add_argument("--limit-chunks", type=int, default=None, help="process at most N chunks this time")
    run.add_argument("--no-review", action="store_true", help="skip the whole-book review")
    run.add_argument("--reset", action="store_true", help="discard saved progress and start over")
    run.set_defaults(func=cmd_run)

    bible = sub.add_parser("bible", help="build the style guide, character voices and term list")
    bible.add_argument("--force", action="store_true", help="rebuild even if it exists")
    bible.set_defaults(func=cmd_bible)

    review = sub.add_parser("review", help="whole-book Spiritist review of the translation")
    review.add_argument("--changed", action="store_true", help="only chapters changed since the last review")
    review.set_defaults(func=cmd_review)

    sub.add_parser("apply-corrections", help="apply the human reviewer's corrections").set_defaults(func=cmd_apply)
    sub.add_parser("build", help="write the English .docx from the saved state").set_defaults(func=cmd_build)
    sub.add_parser("status", help="progress, review counts and API spend").set_defaults(func=cmd_status)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    try:
        args.func(args)
    except (ConfigError, SourceChangedError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
