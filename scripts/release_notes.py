#!/usr/bin/env python3
"""Generate release notes from conventional commit messages.

    python scripts/release_notes.py --to v1.2.0                  # since the previous tag
    python scripts/release_notes.py --from v1.1.0 --to v1.2.0 --output RELEASE_NOTES.md

Commits that follow ``type(scope): subject`` are grouped by type; a ``!`` after the type or a
``BREAKING CHANGE:`` footer is listed first. Anything else lands under "Other changes" rather than
being dropped, so the notes never silently omit work. Standard library only.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from dataclasses import dataclass, field

SECTIONS = [
    ("feat", "Features"),
    ("fix", "Bug fixes"),
    ("perf", "Performance"),
    ("security", "Security"),
    ("refactor", "Refactoring"),
    ("docs", "Documentation"),
    ("test", "Tests"),
    ("build", "Build"),
    ("ci", "CI"),
    ("chore", "Chores"),
]
HEADER = re.compile(r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]+)\))?(?P<bang>!)?:\s+(?P<subject>.+)$")
BREAKING_FOOTER = re.compile(r"^BREAKING[ -]CHANGE:\s*(?P<text>.+)$", re.MULTILINE)


@dataclass
class Change:
    kind: str
    scope: str | None
    subject: str
    sha: str
    breaking: str | None = None


@dataclass
class Notes:
    changes: list[Change] = field(default_factory=list)

    def add(self, sha: str, subject: str, body: str = "") -> None:
        match = HEADER.match(subject.strip())
        footer = BREAKING_FOOTER.search(body)
        if match:
            breaking = None
            if match["bang"] or footer:
                breaking = footer["text"] if footer else match["subject"]
            self.changes.append(
                Change(match["type"], match["scope"], match["subject"], sha, breaking)
            )
        else:
            breaking = footer["text"] if footer else None
            self.changes.append(Change("other", None, subject.strip(), sha, breaking))

    def render(self, version: str, date: str | None = None) -> str:
        lines = [f"# {version}" + (f" ({date})" if date else ""), ""]
        breaking = [change for change in self.changes if change.breaking]
        if breaking:
            lines += ["## Breaking changes", ""]
            lines += [f"- {change.breaking} ({change.sha})" for change in breaking]
            lines.append("")
        known = {kind for kind, _ in SECTIONS}
        for kind, title in SECTIONS:
            selected = [change for change in self.changes if change.kind == kind]
            if selected:
                lines += [f"## {title}", ""] + [self._line(change) for change in selected] + [""]
        others = [change for change in self.changes if change.kind not in known]
        if others:
            lines += ["## Other changes", ""] + [self._line(change) for change in others] + [""]
        if not self.changes:
            lines += ["No changes since the previous release.", ""]
        return "\n".join(lines)

    @staticmethod
    def _line(change: Change) -> str:
        scope = f"**{change.scope}:** " if change.scope else ""
        return f"- {scope}{change.subject} ({change.sha})"


def git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], check=True, capture_output=True, text=True
    ).stdout.strip()


def previous_tag(tag: str) -> str | None:
    try:
        return git("describe", "--tags", "--abbrev=0", f"{tag}^")
    except subprocess.CalledProcessError:
        return None  # the first release: include the whole history


def collect(revision_range: str) -> Notes:
    notes = Notes()
    # %x1e / %x1f are record and field separators that cannot occur in commit text.
    log = git("log", revision_range, "--no-merges", "--format=%h%x1f%s%x1f%b%x1e")
    for record in filter(None, log.split("\x1e")):
        sha, subject, body = (record.strip("\n").split("\x1f") + ["", ""])[:3]
        notes.add(sha.strip(), subject, body)
    return notes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate release notes from commits.")
    parser.add_argument("--to", default="HEAD", help="the tag or revision being released")
    parser.add_argument("--from", dest="from_", help="previous tag (default: the tag before --to)")
    parser.add_argument("--output", help="write to a file instead of stdout")
    arguments = parser.parse_args(argv)

    start = arguments.from_ or previous_tag(arguments.to)
    revision_range = f"{start}..{arguments.to}" if start else arguments.to
    text = collect(revision_range).render(arguments.to)
    if arguments.output:
        with open(arguments.output, "w", encoding="utf-8") as handle:
            handle.write(text)
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
