#!/usr/bin/env python3
import argparse
import concurrent.futures
import json
import re
import sys
import time
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import requests
from xml.etree import ElementTree as ET


BASE_URL = "https://courses.illinois.edu/cisapp/explorer/catalog"


@dataclass
class CourseRecord:
    index: str
    name: Optional[str]
    description: Optional[str]
    prerequisites: Optional[str]


def parse_xml(content: bytes) -> ET.Element:
    try:
        return ET.fromstring(content)
    except ET.ParseError as exc:
        raise RuntimeError(f"Failed to parse XML: {exc}")


def fetch(session: requests.Session, url: str) -> bytes:
    resp = session.get(url, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"GET {url} -> {resp.status_code}")
    return resp.content


def get_subject_ids(session: requests.Session, year: str, term: str) -> List[str]:
    url = f"{BASE_URL}/{year}/{term}.xml"
    root = parse_xml(fetch(session, url))
    subjects = []
    for node in root.findall(".//subject"):
        node_id = node.attrib.get("id")
        if node_id:
            subjects.append(node_id)
    return subjects


def get_course_numbers_for_subject(session: requests.Session, year: str, term: str, subject: str) -> List[str]:
    url = f"{BASE_URL}/{year}/{term}/{subject}.xml"
    root = parse_xml(fetch(session, url))
    courses = []
    for node in root.findall(".//course"):
        node_id = node.attrib.get("id")
        if node_id:
            courses.append(node_id)
    return courses


def extract_prerequisite_text(root: ET.Element) -> Optional[str]:
    # Prefer explicitly labeled prerequisite elements if present
    for tag in ["prerequisites", "prerequisite", "Prerequisites", "Prerequisite"]:
        found = root.find(f".//{tag}")
        if found is not None and (found.text and found.text.strip()):
            return found.text.strip()

    # Fallback: courseSectionInformation often contains "Prerequisite:" free text
    csi = root.find(".//courseSectionInformation")
    if csi is not None and csi.text:
        text = csi.text.strip()
        match = re.search(r"Prerequisite[s]?:\s*(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()

    # As a last resort, scan description for a Prerequisite sentence
    desc = root.find(".//description")
    if desc is not None and desc.text:
        text = desc.text.strip()
        match = re.search(r"Prerequisite[s]?:\s*(.*)$", text, flags=re.IGNORECASE | re.DOTALL)
        if match:
            return match.group(1).strip()

    return None


def get_course_details(session: requests.Session, year: str, term: str, subject: str, course_number: str) -> CourseRecord:
    url = f"{BASE_URL}/{year}/{term}/{subject}/{course_number}.xml"
    root = parse_xml(fetch(session, url))

    # Title/name may be in <label> or <title>
    name = None
    label_node = root.find(".//label")
    if label_node is not None and label_node.text:
        name = label_node.text.strip()
    else:
        title_node = root.find(".//title")
        if title_node is not None and title_node.text:
            name = title_node.text.strip()

    description = None
    desc_node = root.find(".//description")
    if desc_node is not None and desc_node.text:
        description = desc_node.text.strip()

    prerequisites_text = extract_prerequisite_text(root)

    return CourseRecord(
        index=f"{subject} {course_number}",
        name=name,
        description=description,
        prerequisites=prerequisites_text,
    )


def try_year_term(session: requests.Session, year: str, term: str) -> bool:
    url = f"{BASE_URL}/{year}/{term}.xml"
    resp = session.get(url, timeout=15)
    return resp.status_code == 200


def detect_default_year_term(session: requests.Session) -> Tuple[str, str]:
    # Try a few common combinations in likely order
    current_year = time.gmtime().tm_year
    candidate_terms = ["fall", "summer", "spring", "winter"]
    candidates: List[Tuple[str, str]] = []
    # Current year candidates first
    for term in candidate_terms:
        candidates.append((str(current_year), term))
    # Then previous year
    for term in candidate_terms:
        candidates.append((str(current_year - 1), term))

    for year, term in candidates:
        if try_year_term(session, year, term):
            return year, term
    # Fallback to a known historical term
    return "2024", "fall"


def main() -> int:
    parser = argparse.ArgumentParser(description="Fetch UIUC course catalog into JSON")
    parser.add_argument("--year", default=None, help="Catalog year, e.g. 2025")
    parser.add_argument("--term", default=None, help="Term, e.g. fall|spring|summer|winter")
    parser.add_argument("--subject", default=None, help="Limit to a single subject (e.g., CS)")
    parser.add_argument("--max-workers", type=int, default=12, help="Max concurrent requests")
    parser.add_argument("--output", default="data/courses.json", help="Output JSON path")
    parser.add_argument("--sleep", type=float, default=0.0, help="Optional per-request sleep seconds")
    args = parser.parse_args()

    session = requests.Session()
    session.headers.update({"Accept": "application/xml, text/xml;q=0.9, */*;q=0.8", "User-Agent": "uiuc-course-scraper/1.0"})

    year = args.year
    term = args.term
    if not year or not term:
        year, term = detect_default_year_term(session)
        print(f"[info] Using detected catalog: {year} {term}")
    else:
        print(f"[info] Using catalog: {year} {term}")

    try:
        subject_ids = [args.subject] if args.subject else get_subject_ids(session, year, term)
    except Exception as exc:
        print(f"[error] Failed to get subjects for {year} {term}: {exc}")
        return 1

    print(f"[info] Found {len(subject_ids)} subject(s)")

    all_course_records: List[CourseRecord] = []

    def process_subject(subject_id: str) -> List[CourseRecord]:
        try:
            if args.sleep:
                time.sleep(args.sleep)
            course_numbers = get_course_numbers_for_subject(session, year, term, subject_id)
        except Exception as exc_subj:
            print(f"[warn] Failed to list courses for {subject_id}: {exc_subj}")
            return []

        subject_records: List[CourseRecord] = []
        for course_number in course_numbers:
            try:
                if args.sleep:
                    time.sleep(args.sleep)
                record = get_course_details(session, year, term, subject_id, course_number)
                subject_records.append(record)
            except Exception as exc_course:
                print(f"[warn] Failed details for {subject_id} {course_number}: {exc_course}")
                continue
        return subject_records

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.max_workers) as executor:
        future_to_subject: Dict[concurrent.futures.Future, str] = {}
        for subject_id in subject_ids:
            future = executor.submit(process_subject, subject_id)
            future_to_subject[future] = subject_id
        for future in concurrent.futures.as_completed(future_to_subject):
            subject_id = future_to_subject[future]
            try:
                subject_records = future.result()
                all_course_records.extend(subject_records)
                print(f"[info] {subject_id}: {len(subject_records)} course(s)")
            except Exception as exc:
                print(f"[warn] Subject {subject_id} failed: {exc}")

    # Sort deterministically
    all_course_records.sort(key=lambda r: (r.index.split()[0], int(re.sub(r"[^0-9]", "", r.index.split()[1])) if len(r.index.split()) > 1 and re.search(r"\d", r.index.split()[1]) else r.index))

    # Serialize to JSON array of objects
    output_path = args.output
    output_dir = output_path.rsplit("/", 1)[0] if "/" in output_path else "."
    try:
        import os
        os.makedirs(output_dir, exist_ok=True)
    except Exception:
        pass

    with open(output_path, "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in all_course_records], f, ensure_ascii=False, indent=2)

    print(f"[done] Wrote {len(all_course_records)} courses -> {output_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())


