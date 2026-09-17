"""Turn a pytest JUnit XML report into markdown for the GitHub job summary.

The publish-unit-test-result-action draws the counts table; this fills in the
detail it has no room for. Writes to stdout so the workflow can append it to
$GITHUB_STEP_SUMMARY.

Usage: python scripts/test_summary.py reports/unit-junit.xml unit
"""

import sys
from pathlib import Path
from xml.etree import ElementTree

SLOWEST_TEST_COUNT = 10

# JUnit marks an outcome with a child element; a case with none of them passed.
OUTCOME_TAGS = ("failure", "error", "skipped")
OUTCOME_ICONS = {
    "passed": "✅",
    "failure": "❌",
    "error": "❌",
    "skipped": "💤",
}


def read_outcome(case: ElementTree.Element) -> str:
    """Return the outcome tag of a single <testcase>, or 'passed'."""
    for tag in OUTCOME_TAGS:
        if case.find(tag) is not None:
            return tag
    return "passed"


def read_seconds(case: ElementTree.Element) -> float:
    """Return the runtime pytest recorded, tolerating a missing attribute."""
    try:
        return float(case.get("time", "0"))
    except ValueError:
        return 0.0


def read_name(case: ElementTree.Element) -> str:
    """Return a name you can paste straight back into pytest."""
    file_path = case.get("file") or case.get("classname", "unknown")
    name = case.get("name", "unknown")
    # A pipe inside a parametrised id would split the markdown table column.
    return f"{file_path}::{name}".replace("|", "\\|")


def read_cases(report_path: Path) -> tuple[tuple[str, str, float], ...]:
    """Parse the report into (name, outcome, seconds) rows."""
    root = ElementTree.parse(report_path).getroot()
    return tuple(
        (read_name(case), read_outcome(case), read_seconds(case))
        for case in root.iter("testcase")
    )


def render_rows(cases: tuple[tuple[str, str, float], ...]) -> str:
    """Render cases as markdown table rows."""
    return "\n".join(
        f"| {OUTCOME_ICONS[outcome]} | `{name}` | {seconds:.2f}s |"
        for name, outcome, seconds in cases
    )


def render_table(heading: str, cases: tuple[tuple[str, str, float], ...]) -> str:
    """Render a full markdown table, under a bold heading when there is one."""
    title_line = f"**{heading}**\n\n" if heading else ""
    header = f"{title_line}|  | test | time |\n| --- | --- | --- |"
    return f"{header}\n{render_rows(cases)}\n"


def render_summary(title: str, cases: tuple[tuple[str, str, float], ...]) -> str:
    """Render the slowest tests, then every test inside a collapsed block."""
    slowest = tuple(sorted(cases, key=lambda case: case[2], reverse=True))
    sections = (
        render_table(
            f"Slowest {min(SLOWEST_TEST_COUNT, len(cases))} {title} tests",
            slowest[:SLOWEST_TEST_COUNT],
        ),
        "<details>\n"
        f"<summary><b>All {len(cases)} {title} tests</b></summary>\n\n"
        f"{render_table('', cases)}"
        "</details>\n",
    )
    return "\n".join(sections)


def main() -> int:
    if len(sys.argv) != 3:
        print(__doc__)
        return 1

    report_path, title = Path(sys.argv[1]), sys.argv[2]

    # The workflow calls this with if: always(), so a crashed pytest run leaves
    # no report. Say so in the summary rather than failing the job twice over.
    if not report_path.is_file():
        print(f"_no {title} test report was written_")
        return 0

    try:
        cases = read_cases(report_path)
    except ElementTree.ParseError as error:
        print(f"_could not read the {title} test report: {error}_")
        return 0

    if not cases:
        print(f"_the {title} test report contains no tests_")
        return 0

    print(render_summary(title, cases))
    return 0


if __name__ == "__main__":
    sys.exit(main())
