from __future__ import annotations

import sys

from ._paths import QA_ROUTER_DIR, check_layout


def main() -> int:
    problems = check_layout()
    if problems:
        for p in problems:
            print(f"finqa: {p}", file=sys.stderr)
        print(
            "finqa: this console command expects to run from an editable install "
            "(`pip install -e .` from the project root) with all sibling project "
            "folders still present alongside fin_llm_platform/ -- see MANUAL.md.",
            file=sys.stderr,
        )
        return 1

    sys.path.insert(0, str(QA_ROUTER_DIR))
    from src.cli import main as qa_main  # noqa: PLC0415 -- deliberately late, see module docstring

    return qa_main()


if __name__ == "__main__":
    raise SystemExit(main())