import { XMLParser } from "fast-xml-parser";
import fs from "fs/promises";
import path from "path";
import dns from "node:dns";
import { ProxyAgent } from "undici";

dns.setDefaultResultOrder("ipv4first");

const proxy = process.env.HTTPS_PROXY || process.env.https_proxy || process.env.HTTP_PROXY || process.env.http_proxy;
const dispatcher = proxy ? new ProxyAgent(proxy) : undefined;

const [ , , YEAR = "2025", TERM = "fall" ] = process.argv;
// UIUC's API uses XML namespaces (e.g. `<ns2:term>`). In order for the
// returned object to have plain keys like `term` and `subject`, we instruct
// fast-xml-parser to strip the namespace prefixes.
const parser = new XMLParser({ ignoreAttributes: false, removeNSPrefix: true });
const BASE = `https://courses.illinois.edu/cisapp/explorer`;

async function getXML(url) {
  const res = await fetch(url, { dispatcher });
  if (!res.ok) throw new Error(`Request failed: ${res.status} ${url}`);
  return parser.parse(await res.text());
}

async function scrapeSchedule(year, term) {
  const catalog = {};
  const termRoot = await getXML(`${BASE}/schedule/${year}/${term}.xml`);
  const subjects = termRoot.term?.subjects?.subject;
  if (!subjects) throw new Error(`Unexpected XML structure for ${year} ${term}`);
  const subjHrefs = Array.isArray(subjects) ? subjects.map(s => s['@_href']) : [subjects['@_href']];

  for (const subjURL of subjHrefs) {
    const subjXML = await getXML(subjURL);
    const courses = subjXML.subject?.courses?.course || [];
    const courseList = Array.isArray(courses) ? courses : [courses];
    for (const c of courseList) {
      const courseURL = c['@_href'];
      const courseXML = await getXML(courseURL);
      const id = courseXML.course['@_id'];
      const desc = courseXML.course.description ?? "";
      const m = desc.match(/Prerequisite[s]?:\s*([^.;]*)/i);
      if (!m) continue;
      const prereqs = m[1]
        .match(/[A-Z]{2,4}\s?\d{2,3}[A-Z]?/g)
        ?.map(s => s.replace(/\s+/, "")) ?? [];
      if (prereqs.length) catalog[id.replace(/\s+/, "")] = prereqs;
    }
    await new Promise(r => setTimeout(r, 300));
  }
  return catalog;
}

const data = await scrapeSchedule(YEAR, TERM);
const outDir = path.resolve("data");
await fs.mkdir(outDir, { recursive: true });
await fs.writeFile(path.join(outDir, `catalog_${YEAR}_${TERM}.json`), JSON.stringify(data, null, 2));
console.log(`Saved ${Object.keys(data).length} courses`);
