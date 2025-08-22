#!/usr/bin/env python3
import argparse
import json
import re
from typing import Any, Dict, Iterable, List


COURSE_TOKEN = re.compile(r"\b([A-Z]{2,4})\s*(\d{2,3}[A-Z]?)\b")
NONE_PATTERNS = [
    re.compile(r"^\s*none\.?\s*$", re.IGNORECASE),
    re.compile(r"no prerequisites", re.IGNORECASE),
    re.compile(r"prerequisite[s]?:\s*none\b", re.IGNORECASE),
]


def is_none_text(text: str) -> bool:
    t = text.strip()
    return any(p.search(t) for p in NONE_PATTERNS)


def extract_course_refs(text: str) -> List[str]:
    refs = []
    for m in COURSE_TOKEN.finditer(text):
        subject, number = m.group(1), m.group(2)
        refs.append(f"{subject} {number}")
    return refs


NON_COURSE_KEYWORDS = [
    r"consent", r"permission", r"approval",
    r"standing", r"senior", r"junior", r"sophomore", r"freshman",
    r"major", r"minor", r"program", r"restricted", r"enrollment", r"enrolled",
    r"gpa", r"grade", r"minimum", r"credit hour", r"credits?", r"hours?",
    r"registration", r"concurrent", r"co-requisite", r"corequisite",
    r"department", r"instructor",
]

def has_non_course_requirements(text: str) -> bool:
    t = text.lower()
    return any(re.search(k, t) for k in NON_COURSE_KEYWORDS)


def is_course_only(text: str) -> bool:
    t = text.strip()
    if has_non_course_requirements(t):
        return False
    # Remove course tokens, then see if any nontrivial tokens remain besides basic connectors
    placeholder = COURSE_TOKEN.sub("COURSE", t)
    # Remove conjunctions and punctuation
    simplified = re.sub(r"[(),.;]", " ", placeholder)
    simplified = re.sub(r"\b(and|or|and/or|either|both|one of|two of|with|credit in)\b", " ", simplified, flags=re.IGNORECASE)
    # Remove common quantifiers
    simplified = re.sub(r"\b(at\s+least)\b", " ", simplified, flags=re.IGNORECASE)
    # Collapse whitespace
    simplified = re.sub(r"\s+", " ", simplified).strip()
    # If empty or only words like COURSE left, treat as course-only
    return simplified == "" or re.fullmatch(r"(COURSE\s*)+", simplified) is not None


def analyze(courses: Iterable[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    results = {
        "none": [],
        "course_only": [],
        "remaining": [],
    }

    for c in courses:
        prereq = c.get("prerequisites") or ""
        if not prereq.strip():
            results["none"].append(c)
            continue
        if is_none_text(prereq):
            results["none"].append(c)
            continue
        if is_course_only(prereq):
            results["course_only"].append({
                "index": c.get("index"),
                "name": c.get("name"),
                "prerequisites": prereq,
                "courses": extract_course_refs(prereq),
            })
        else:
            results["remaining"].append({
                "index": c.get("index"),
                "name": c.get("name"),
                "prerequisites": prereq,
            })
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="Analyze UIUC course prerequisite text")
    ap.add_argument("input", default="data/courses.json", nargs="?", help="Input courses JSON array")
    ap.add_argument("--outdir", default="data/analysis", help="Output directory")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    res = analyze(data)

    import os
    os.makedirs(args.outdir, exist_ok=True)
    with open(os.path.join(args.outdir, "none.json"), "w", encoding="utf-8") as f:
        json.dump(res["none"], f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.outdir, "course_only.json"), "w", encoding="utf-8") as f:
        json.dump(res["course_only"], f, ensure_ascii=False, indent=2)
    with open(os.path.join(args.outdir, "remaining.json"), "w", encoding="utf-8") as f:
        json.dump(res["remaining"], f, ensure_ascii=False, indent=2)

    print(f"none: {len(res['none'])}")
    print(f"course_only: {len(res['course_only'])}")
    print(f"remaining: {len(res['remaining'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


