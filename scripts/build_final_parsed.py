#!/usr/bin/env python3
import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List


# Ensure we can import sibling script
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from parse_course_prereqs import parse_prereq_text  # type: ignore


COURSE_TOKEN = re.compile(r"\b([A-Z]{2,4})\s*(\d{2,3}[A-Z]?)\b")
CLAUSE_SPLIT_RE = re.compile(r";+")

NON_COURSE_KEYWORDS = [
    r"consent", r"permission", r"approval",
    r"standing", r"senior", r"junior", r"sophomore", r"freshman",
    r"major", r"minor", r"program", r"restricted", r"enrollment", r"enrolled",
    r"gpa", r"grade", r"minimum", r"credit hour", r"credits?", r"hours?",
    r"registration", r"concurrent", r"co-requisite", r"corequisite",
    r"department", r"instructor",
]


def has_course_token(s: str) -> bool:
    return COURSE_TOKEN.search(s) is not None


def detect_flags(text: str) -> List[str]:
    t = text.lower()
    flags: List[str] = []
    mapping = [
        (r"consent|permission|approval", "CONSENT"),
        (r"standing|senior|junior|sophomore|freshman", "STANDING"),
        (r"major|minor|program|restricted|enrollment|enrolled", "MAJOR_OR_PROGRAM"),
        (r"gpa|grade|minimum", "GRADE_OR_GPA"),
        (r"concurrent|co-requisite|corequisite", "COREQ_ALLOWED"),
        (r"department|instructor", "DEPT_OR_INSTRUCTOR"),
    ]
    for pat, name in mapping:
        if re.search(pat, t):
            flags.append(name)
    return sorted(set(flags))


def main() -> int:
    ap = argparse.ArgumentParser(description="Build final parsed JSON for all courses")
    ap.add_argument("input", nargs="?", default="data/courses.json", help="Input courses.json")
    ap.add_argument("--output", default="data/courses_parsed.json", help="Output JSON path")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        courses = json.load(f)

    out: List[Dict[str, Any]] = []
    stats = {"total": 0, "hard_nonempty": 0, "coreq_nonempty": 0}
    for c in courses:
        stats["total"] += 1
        raw = (c.get("prerequisites") or "").strip()
        ast = parse_prereq_text(raw)

        hard = ast.get("hard") if isinstance(ast, dict) else {"op": "EMPTY"}
        coreq_ok = ast.get("coreq_ok") if isinstance(ast, dict) else {"op": "EMPTY"}
        if hard and hard.get("op") != "EMPTY":
            stats["hard_nonempty"] += 1
        if coreq_ok and coreq_ok.get("op") != "EMPTY":
            stats["coreq_nonempty"] += 1

        # Capture non-course clauses for reference
        notes: List[str] = []
        if raw:
            clauses = [s.strip() for s in CLAUSE_SPLIT_RE.split(raw) if s.strip()]
            for cl in clauses:
                if not has_course_token(cl) or detect_flags(cl):
                    notes.append(cl)

        out.append({
            "index": c.get("index"),
            "name": c.get("name"),
            "description": c.get("description"),
            "prerequisites": {
                "raw": raw or None,
                "hard": hard,
                "coreq_ok": coreq_ok,
                "flags": detect_flags(raw) if raw else [],
                "notes": notes,
            },
        })

    os.makedirs(os.path.dirname(args.output) or ".", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)

    print(json.dumps(stats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


