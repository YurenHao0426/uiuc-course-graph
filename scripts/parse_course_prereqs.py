#!/usr/bin/env python3
import argparse
import json
import re
from typing import Any, Dict, List, Optional, Tuple


COURSE_RE = re.compile(r"\b([A-Z]{2,4})\s*(\d{2,3}[A-Z]?)\b")

# Clause boundaries: semicolons are strong AND separators at UIUC
CLAUSE_SPLIT_RE = re.compile(r";+")


def find_course_spans(text: str) -> List[Tuple[str, int, int]]:
    spans: List[Tuple[str, int, int]] = []
    for m in COURSE_RE.finditer(text):
        course = f"{m.group(1)} {m.group(2)}"
        spans.append((course, m.start(), m.end()))
    return spans


def normalize_space(s: str) -> str:
    return re.sub(r"\s+", " ", s).strip()


def parse_clause_into_group(clause: str) -> Dict[str, Any]:
    clause_clean = normalize_space(clause)
    courses = find_course_spans(clause_clean)
    if not courses:
        return {"op": "EMPTY"}

    # Detect "one of" window: treat everything until boundary as OR
    one_of_match = re.search(r"\b(one of|any of)\b", clause_clean, flags=re.IGNORECASE)
    if one_of_match:
        # Take all courses in the clause as OR if they appear after the phrase
        start_idx = one_of_match.end()
        or_list = [c for (c, s, e) in courses if s >= start_idx]
        if or_list:
            # Also include any course tokens that appear BEFORE the one-of phrase as separate AND terms
            prior_courses = [c for (c, s, e) in courses if s < start_idx]
            items: List[Dict[str, Any]] = []
            for c in prior_courses:
                items.append({"op": "COURSE", "course": c})
            items.append({"op": "OR", "items": [{"op": "COURSE", "course": c} for c in or_list]})
            return {"op": "AND", "items": items} if len(items) > 1 else items[0]

    # Otherwise, infer connectors between adjacent course tokens
    # Build pairwise connectors from text between tokens
    connectors: List[str] = []
    for i in range(len(courses) - 1):
        _, _, end_prev = courses[i]
        _, start_next, _ = courses[i + 1]
        between = clause_clean[end_prev:start_next].lower()
        if "and/or" in between:
            connectors.append("OR")
        elif re.search(r"\band\b", between):
            connectors.append("AND")
        elif re.search(r"\bor\b", between):
            connectors.append("OR")
        else:
            # Default: comma-only separation; lean towards OR if followed by or earlier in span
            if "," in between:
                connectors.append("LIST")
            else:
                connectors.append("UNKNOWN")

    course_items = [{"op": "COURSE", "course": c} for (c, _, _) in courses]

    # If there is any explicit AND, group AND chunks; otherwise treat as OR if any OR, else LIST->OR
    if "AND" in connectors and "OR" not in connectors:
        return {"op": "AND", "items": course_items}
    if "OR" in connectors and "AND" not in connectors:
        return {"op": "OR", "items": course_items}
    if "AND" not in connectors and "OR" not in connectors:
        # All LIST/UNKNOWN: choose OR as a safer default for admissions like "A, B, or C" where last token has or
        if any(k == "LIST" for k in connectors):
            return {"op": "OR", "items": course_items}
        return {"op": "AND", "items": course_items} if len(course_items) > 1 else course_items[0]

    # Mixed AND and OR: build small AST by splitting on commas and respecting local conjunctions
    # Simple heuristic: split clause by commas, parse each segment for explicit AND/OR
    segments = [normalize_space(s) for s in re.split(r",+", clause_clean) if normalize_space(s)]
    subitems: List[Dict[str, Any]] = []
    for seg in segments:
        seg_courses = find_course_spans(seg)
        if not seg_courses:
            continue
        if re.search(r"\band\b", seg.lower()) and not re.search(r"\bor\b", seg.lower()):
            subitems.append({"op": "AND", "items": [{"op": "COURSE", "course": c} for (c, _, _) in seg_courses]})
        elif re.search(r"\bor\b", seg.lower()) and not re.search(r"\band\b", seg.lower()):
            subitems.append({"op": "OR", "items": [{"op": "COURSE", "course": c} for (c, _, _) in seg_courses]})
        else:
            # ambiguous within segment; default to OR
            subitems.append({"op": "OR", "items": [{"op": "COURSE", "course": c} for (c, _, _) in seg_courses]})

    if not subitems:
        subitems = [{"op": "COURSE", "course": c} for (c, _, _) in courses]

    # Combine segments with AND if split by semicolons at higher level; here stay at clause level
    # For mixed case within one clause, default to OR-over-segments unless explicit AND dominates
    and_count = sum(1 for s in subitems if s.get("op") == "AND")
    or_count = sum(1 for s in subitems if s.get("op") == "OR")
    if and_count and not or_count:
        return {"op": "AND", "items": subitems}
    if or_count and not and_count:
        return {"op": "OR", "items": subitems}
    # Mixed: wrap in AND of items that are groups; treat OR groups as single requirements groups
    return {"op": "AND", "items": subitems}


def parse_prereq_text(text: str) -> Dict[str, Any]:
    # Split by semicolons into top-level AND clauses
    clauses = [normalize_space(c) for c in CLAUSE_SPLIT_RE.split(text) if normalize_space(c)]
    if not clauses:
        return {"hard": {"op": "EMPTY"}, "coreq_ok": {"op": "EMPTY"}}

    def is_coreq_clause(c: str) -> bool:
        c_low = c.lower()
        return (
            ("concurrent" in c_low) or
            ("co-requisite" in c_low) or
            ("corequisite" in c_low) or
            re.search(r"credit\s+or\s+concurrent\s+(enrollment|registration)\s+in", c_low) is not None
        )

    hard_groups: List[Dict[str, Any]] = []
    coreq_groups: List[Dict[str, Any]] = []
    for clause in clauses:
        grp = parse_clause_into_group(clause)
        if grp.get("op") == "EMPTY":
            continue
        if is_coreq_clause(clause):
            coreq_groups.append(grp)
        else:
            hard_groups.append(grp)

    def fold(groups: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not groups:
            return {"op": "EMPTY"}
        if len(groups) == 1:
            return groups[0]
        return {"op": "AND", "items": groups}

    return {"hard": fold(hard_groups), "coreq_ok": fold(coreq_groups)}


def main() -> int:
    ap = argparse.ArgumentParser(description="Parse course-only prerequisite text into AND/OR groups")
    ap.add_argument("input", default="data/analysis/course_only.json", nargs="?", help="Input JSON array of course-only prereqs")
    ap.add_argument("--output", default="data/parsed/course_only_parsed.json", help="Output JSON path")
    ap.add_argument("--unparsed-output", default="data/parsed/course_only_unparsed.json", help="Unparsed/empty output JSON path")
    args = ap.parse_args()

    with open(args.input, "r", encoding="utf-8") as f:
        data = json.load(f)

    parsed: List[Dict[str, Any]] = []
    unparsed: List[Dict[str, Any]] = []

    for item in data:
        raw = item.get("prerequisites") or ""
        ast = parse_prereq_text(raw)
        record = {
            "index": item.get("index"),
            "name": item.get("name"),
            "raw": raw,
            "ast": ast,
        }
        # Consider unparsed only if both hard and coreq_ok are EMPTY
        if (isinstance(ast, dict) and ast.get("hard", {}).get("op") == "EMPTY" and ast.get("coreq_ok", {}).get("op") == "EMPTY"):
            unparsed.append(record)
        else:
            parsed.append(record)

    import os
    os.makedirs("data/parsed", exist_ok=True)
    with open(args.output, "w", encoding="utf-8") as f:
        json.dump(parsed, f, ensure_ascii=False, indent=2)
    with open(args.unparsed_output, "w", encoding="utf-8") as f:
        json.dump(unparsed, f, ensure_ascii=False, indent=2)

    print(f"parsed: {len(parsed)}")
    print(f"unparsed: {len(unparsed)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


