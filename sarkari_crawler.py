#!/usr/bin/env python3
"""
=============================================================================
Sarkari Result Vacancy Crawler & Intelligence Extractor
=============================================================================
A modular, high-performance web crawler and data extractor tailored for
sarkariresult.com recruitment listings (/latestjob/) and individual vacancy pages.

Features:
- Realistic browser header emulation (bypasses Cloudflare & WAF bot filters)
- Dual listing parser: handles both `<ul class="sarkari-quick-list">` and `<ul class="wp-block-list">`
- Normalizes titles, extracts deadlines, post counts, and categorizes jobs
- Optional Deep Mode (--deep): crawls individual vacancy detail pages to extract
  Advt No, Start/Last dates, Fees, Age criteria, Eligibility, and Official links
  (Notification PDF, Apply Online, Official Portal).
- Multi-threaded worker pool with polite jitter for fast deep crawling.
- Offline Mode (--html-file): parse saved HTML responses instantly without network.
- Exports to clean JSON and CSV.
- Formatted Rich CLI table output.
=============================================================================
"""

import sys
import os
import re
import csv
import json
import time
import random
import argparse
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure UTF-8 stdout/stderr on Windows
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

import requests
from bs4 import BeautifulSoup
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# Anti-Cloudflare TLS fingerprint impersonation (bypasses 403 Forbidden on GitHub Actions / cloud IPs)
try:
    from curl_cffi import requests as cffi_requests
    HAVE_CURL_CFFI = True
except ImportError:
    HAVE_CURL_CFFI = False

# Optional rich formatting for CLI table output
try:
    from rich.console import Console
    from rich.table import Table
    from rich import print as rprint
    HAVE_RICH = True
except ImportError:
    HAVE_RICH = False

# Realistic browser headers identical to genuine user navigation
DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "en-US,en;q=0.9,hi;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.sarkariresult.com/",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "Cache-Control": "max-age=0"
}

CATEGORY_RULES = [
    ("Railways", [r"\brailway\b", r"\brrb\b", r"\brrc\b", r"\bsecr\b", r"\bwr\b", r"\bnfr\b", r"\becr\b"]),
    ("Banking", [r"\bbank\b", r"\bsbi\b", r"\bibps\b", r"\brbi\b", r"\bpnb\b", r"\bbob\b", r"\bcanara\b", r"\bnabard\b", r"\bexim\b", r"\buco\b", r"\bidbi\b", r"\biob\b", r"\bbom\b"]),
    ("Staff Selection Commission (SSC)", [r"\bssc\b", r"\bcgl\b", r"\bchsl\b", r"\bmts\b", r"\bcpo\b", r"\bstenographer\b", r"\bjht\b"]),
    ("UPSC / Civil Services", [r"\bupsc\b", r"\bias\b", r"\bifs\b", r"\bnda\b", r"\bcds\b", r"\bepfo\b", r"\bcms\b", r"\bies\b", r"\biss\b"]),
    ("Defence & Paramilitary", [r"\barmy\b", r"\bnavy\b", r"\bair force\b", r"\bairforce\b", r"\bagniveer\b", r"\bafcat\b", r"\bcrpf\b", r"\bitbp\b", r"\bcisf\b", r"\bssb\b", r"\bassam rifles\b", r"\bcoast guard\b"]),
    ("Police & State Forces", [r"\bpolice\b", r"\bconstable\b", r"\bsi\b", r"\bsub inspector\b", r"\bhead constable\b", r"\bhc\b", r"\basi\b", r"\bhome guard\b", r"\bvanrakshak\b", r"\bjail\b"]),
    ("Teaching & Education", [r"\bteacher\b", r"\btet\b", r"\bctet\b", r"\buptet\b", r"\bstet\b", r"\bjhtet\b", r"\butet\b", r"\bpgt\b", r"\btgt\b", r"\bprt\b", r"\bprofessor\b", r"\blecturer\b", r"\beducator\b", r"\bschool\b", r"\bvidyalaya\b", r"\bnet\b", r"\bset\b"]),
    ("Judicial & Courts", [r"\bhigh court\b", r"\bsupreme court\b", r"\bcourt\b", r"\bjudge\b", r"\bjudicial\b", r"\bjja\b", r"\bdhc\b", r"\bahc\b", r"\bmphc\b", r"\blaw clerk\b"]),
    ("State PSC & Commissions", [r"\bupsssc\b", r"\bmpesb\b", r"\bbpsc\b", r"\bbssc\b", r"\bbpssc\b", r"\brpsc\b", r"\brssb\b", r"\buksssc\b", r"\bukpsc\b", r"\bjssc\b", r"\bjpsc\b", r"\bhssc\b", r"\bhpsc\b", r"\bmppsc\b", r"\buppsc\b", r"\bdsssb\b", r"\bbtsc\b", r"\bcsbc\b", r"\bvyapam\b", r"\bcgpsc\b", r"\bhppsc\b"]),
    ("Engineering & PSUs", [r"\bengineer\b", r"\bengineering\b", r"\btechnician\b", r"\bapprentice\b", r"\bapprentices\b", r"\bscientist\b", r"\bisro\b", r"\bdrdo\b", r"\bntpc\b", r"\biocl\b", r"\bnalco\b", r"\bcsir\b", r"\bnpcil\b", r"\bp какая\b", r"\bpgcil\b", r"\bhcl\b", r"\bcoal india\b", r"\bdfccil\b", r"\biffco\b", r"\bsecl\b", r"\bncl\b", r"\bconcor\b", r"\baai\b"])
]


class SarkariCrawler:
    """
    Crawler and parser for Sarkari Result recruitment vacancies.
    """

    def __init__(self, base_url: str = "https://www.sarkariresult.com", timeout: int = 20, delay_range: tuple = (0.3, 0.8)):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.delay_range = delay_range
        self.session = self._init_session()

    def _init_session(self):
        if HAVE_CURL_CFFI:
            # Emulates genuine Chrome browser TLS fingerprint (JA3/JA4) & HTTP/2 to bypass Cloudflare bot filters
            session = cffi_requests.Session(impersonate="chrome124")
            session.headers.update(DEFAULT_HEADERS)
            return session

        session = requests.Session()
        session.headers.update(DEFAULT_HEADERS)
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "HEAD"]
        )
        adapter = HTTPAdapter(max_retries=retry_strategy, pool_connections=20, pool_maxsize=20)
        session.mount("https://", adapter)
        session.mount("http://", adapter)
        return session

    def fetch_url(self, url: str) -> Optional[str]:
        """
        Fetches a URL and returns raw HTML text.
        """
        try:
            resp = self.session.get(url, timeout=self.timeout)
            resp.raise_for_status()
            if hasattr(resp, "apparent_encoding") and resp.apparent_encoding:
                resp.encoding = resp.apparent_encoding
            elif hasattr(resp, "encoding") and resp.encoding:
                pass
            else:
                resp.encoding = "utf-8"
            return resp.text
        except Exception as e:
            if HAVE_CURL_CFFI:
                try:
                    resp = cffi_requests.get(url, impersonate="chrome124", headers=DEFAULT_HEADERS, timeout=self.timeout)
                    if resp.status_code == 200:
                        return resp.text
                except Exception:
                    pass
            print(f"[!] Request error fetching {url}: {e}", file=sys.stderr)
            return None

    def classify_category(self, text: str) -> str:
        """
        Infers vacancy domain category based on regex taxonomy.
        """
        for cat_name, patterns in CATEGORY_RULES:
            for p in patterns:
                if re.search(p, text, re.IGNORECASE):
                    return cat_name
        return "General / State"

    def infer_organization(self, title: str) -> str:
        """
        Identifies the recruiting organization abbreviation or name from title prefix.
        """
        prefixes = [
            "Railway RRB", "RRB", "Railway RRC", "RRC", "SSC", "UPSC", "UPSSSC", "UPPSC",
            "MPESB", "MPPSC", "BPSC", "BPSSC", "BSSC", "BTSC", "CSBC",
            "RPSC", "RSSB", "RVUNL", "UKSSSC", "UKPSC", "JSSC", "JPSC",
            "HSSC", "HPSC", "DSSSB", "IBPS", "SBI", "RBI", "PNB", "BOB", "Bank of India",
            "Canara Bank", "Union Bank", "Indian Navy", "Indian Army", "Indian Air Force",
            "ITBP", "CRPF", "CISF", "SSB", "Assam Rifles", "ISRO", "DRDO", "NTPC", "IOCL",
            "Supreme Court", "High Court", "CTET", "UPTET", "UTET", "JHTET"
        ]
        for p in prefixes:
            if re.search(r'\b' + re.escape(p) + r'\b', title, re.IGNORECASE):
                return p
        # Fallback: extract first 2 words if capitalized
        words = title.split()
        if len(words) >= 2:
            return " ".join(words[:2])
        return "Government of India / State"

    def parse_listing_item(self, li_elem, source_type: str) -> Optional[Dict[str, Any]]:
        """
        Extracts structured record from an <li> tag within Sarkari Result listings.
        """
        a_elem = li_elem.find("a", href=True)
        if not a_elem:
            return None

        href = a_elem["href"].strip()
        full_url = urljoin(self.base_url, href)
        raw_text = li_elem.get_text(" ", strip=True)

        # 1. Extract Last Date
        last_date = None
        m_date = re.search(r"Last Date\s*:\s*([^|\n]+)", raw_text, re.IGNORECASE)
        if m_date:
            last_date = m_date.group(1).strip()
            # Clean trailing spaces / punctuation
            last_date = re.sub(r"[\s\.\-]+$", "", last_date)

        # 2. Extract Total Posts count if mentioned in the listing line
        posts = None
        m_posts = re.search(r"(\d+)\s*(?:Post|Posts|Vacancy|Vacancies)", raw_text, re.IGNORECASE)
        if m_posts:
            try:
                posts = int(m_posts.group(1))
            except ValueError:
                posts = None

        # 3. Clean Title: remove trailing "| Last Date : ...", "Last Date : ...", etc.
        clean_title = re.sub(r"\|\s*Last Date\s*:.*", "", raw_text, flags=re.IGNORECASE)
        clean_title = re.sub(r"Last Date\s*:.*", "", clean_title, flags=re.IGNORECASE)
        clean_title = clean_title.strip(" |-\t\n\r")
        if not clean_title:
            clean_title = a_elem.get_text(" ", strip=True)

        NAV_TITLES = {"latest jobs", "admit card", "result", "answer key", "syllabus", "search", "home", "contact us", "recruitments", "admit cards", "results", "upcoming", "sarkari yojna", "admission", "about us", "privacy policy"}
        if clean_title.lower() in NAV_TITLES:
            return None

        # Ensure item matches recruitment taxonomy or contains posts/dates
        is_recruitment = any(k in clean_title.lower() for k in [
            "online form", "recruitment", "vacancy", "bharti", "post", "exam", "admit",
            "constable", "officer", "apprentice", "teacher", "clerk", "engineer", "rally",
            "assistant", "subedar", "scholarship", "inspector", "cpo", "cgl", "chsl", "mts"
        ]) or bool(posts) or bool(last_date)
        if not is_recruitment:
            return None

        # 4. Status determination
        status = "Active"
        raw_lower = raw_text.lower()
        if "date extended" in raw_lower or "extended" in raw_lower:
            status = "Date Extended"
        elif "correction" in raw_lower or "edit form" in raw_lower:
            status = "Correction Form"
        elif "re open" in raw_lower or "re-open" in raw_lower or "re apply" in raw_lower:
            status = "Re-Opened"
        elif "cancelled" in raw_lower:
            status = "Cancelled"
        elif "answer key" in raw_lower:
            status = "Answer Key"
        elif "option form" in raw_lower or "preference" in raw_lower:
            status = "Preference Form"
        elif "document upload" in raw_lower or "dv " in raw_lower:
            status = "DV Document Upload"

        # 5. Is direct PDF or external portal
        is_direct_pdf = href.lower().endswith(".pdf") or "doc.sarkariresults" in href.lower()

        # 6. Slug / ID
        slug = href.strip("/").split("/")[-1].replace(".pdf", "").replace(".html", "")
        job_id = f"job-{slug}" if slug else f"job-{abs(hash(clean_title)) % 1000000}"

        category = self.classify_category(clean_title)
        org = self.infer_organization(clean_title)

        return {
            "id": job_id,
            "title": clean_title,
            "organization": org,
            "category": category,
            "posts": posts,
            "last_date": last_date,
            "url": full_url,
            "status": status,
            "is_direct_pdf": is_direct_pdf,
            "source_type": source_type,
            "raw_text": raw_text
        }

    def parse_listings_html(self, html_content: str) -> List[Dict[str, Any]]:
        """
        Parses all vacancy listings from /latestjob/ HTML content.
        Combines <ul class="sarkari-quick-list"> and <ul class="wp-block-list">.
        """
        soup = BeautifulSoup(html_content, "lxml")
        results = []
        seen_urls = set()

        # Target list containers:
        # 1. Quick list (top featured jobs)
        for ul in soup.find_all("ul", class_="sarkari-quick-list"):
            for li in ul.find_all("li"):
                item = self.parse_listing_item(li, source_type="quick_list")
                if item and item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    results.append(item)

        # 2. Main list (comprehensive chronological listings)
        for ul in soup.find_all("ul", class_="wp-block-list"):
            for li in ul.find_all("li"):
                item = self.parse_listing_item(li, source_type="main_list")
                if item and item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    results.append(item)

        # 3. Fallback: Any remaining <li> with recruitment links inside .entry-content
        entry_content = soup.find("div", class_="entry-content")
        if entry_content and len(results) == 0:
            for li in entry_content.find_all("li"):
                item = self.parse_listing_item(li, source_type="generic_list")
                if item and item["url"] not in seen_urls:
                    seen_urls.add(item["url"])
                    results.append(item)

        # 4. Heading links (handles mirror portals like rojgarresult & portal homepages)
        if len(results) < 25:
            for tag in soup.find_all(["h2", "h3", "p", "div"]):
                a_elem = tag.find("a", href=True)
                if not a_elem:
                    continue
                txt = a_elem.get_text(" ", strip=True)
                if any(k in txt.lower() for k in ["online form", "recruitment", "vacancy", "bharti", "post"]):
                    href = a_elem["href"].strip()
                    full_url = urljoin(self.base_url, href)
                    if full_url not in seen_urls and not full_url.endswith("/latestjob/"):
                        raw_text = tag.get_text(" ", strip=True)
                        m_posts = re.search(r"(\d+)\s*(?:Post|Posts|Vacancy|Vacancies)", raw_text, re.IGNORECASE)
                        posts = int(m_posts.group(1)) if m_posts else None
                        clean_title = re.sub(r"for\s+\d+\s+Post.*", "", txt, flags=re.IGNORECASE).strip(" |-\t\n\r")
                        slug = href.strip("/").split("/")[-1].replace(".html", "")
                        job_id = f"job-{slug}" if slug else f"job-{abs(hash(clean_title)) % 1000000}"
                        seen_urls.add(full_url)
                        results.append({
                            "id": job_id,
                            "title": clean_title,
                            "organization": self.infer_organization(clean_title),
                            "category": self.classify_category(clean_title),
                            "posts": posts,
                            "last_date": None,
                            "url": full_url,
                            "status": "Active",
                            "is_direct_pdf": False,
                            "source_type": "heading_list",
                            "raw_text": raw_text
                        })

        return results

    def parse_job_detail_html(self, html_content: str, job_url: str) -> Dict[str, Any]:
        """
        Extracts deep recruitment fields from a Sarkari Result job detail page.
        """
        soup = BeautifulSoup(html_content, "lxml")

        detail = {
            "post_name": "",
            "post_date": "",
            "short_info": "",
            "advt_no": "",
            "application_begin": None,
            "last_date_apply": None,
            "last_date_fee": None,
            "correction_last_date": None,
            "exam_date": None,
            "fee_general_obc": None,
            "fee_sc_st": None,
            "fee_ph": None,
            "min_age": None,
            "max_age": None,
            "age_cutoff": None,
            "total_posts": None,
            "category_vacancies": {},
            "eligibility": "",
            "official_links": {}
        }

        # 1. Post Name / Title
        h1 = soup.find("h1")
        if h1:
            detail["post_name"] = h1.get_text(strip=True)
        elif soup.title:
            detail["post_name"] = soup.title.get_text(strip=True)

        # 2. Extract Top Meta Info (Post Date, Short Information)
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) >= 2:
                label = cells[0].get_text(strip=True).lower()
                val = cells[1].get_text(" ", strip=True)
                if "post date" in label or "update" in label:
                    detail["post_date"] = val
                elif "short information" in label:
                    detail["short_info"] = val

        # 3. Dates, Fees, Age extraction from Table cells
        for td in soup.find_all("td"):
            text = td.get_text("\n", strip=True)

            # Dates block
            if "Important Dates" in text or "Application Begin" in text:
                m_begin = re.search(r"Application Begin\s*:\s*\n*([^\n]+)", text, re.I)
                if m_begin:
                    detail["application_begin"] = m_begin.group(1).strip()

                m_last = re.search(r"Last Date for Apply Online\s*:\s*\n*([^\n]+)", text, re.I)
                if not m_last:
                    m_last = re.search(r"Last Date\s*:\s*\n*([^\n]+)", text, re.I)
                if m_last:
                    detail["last_date_apply"] = m_last.group(1).strip()

                m_fee = re.search(r"(?:Pay Exam Fee Last Date|Last Date Pay Exam Fee)\s*:\s*\n*([^\n]+)", text, re.I)
                if m_fee:
                    detail["last_date_fee"] = m_fee.group(1).strip()

                m_corr = re.search(r"(?:Correction Last Date|Form Correction Last Date)\s*:\s*\n*([^\n]+)", text, re.I)
                if m_corr:
                    detail["correction_last_date"] = m_corr.group(1).strip()

                m_exam = re.search(r"(?:Exam Date|Date of Exam)\s*:\s*\n*([^\n]+)", text, re.I)
                if m_exam:
                    detail["exam_date"] = m_exam.group(1).strip()

            # Application Fee block
            if "Application Fee" in text:
                m_gen = re.search(r"(?:General|UR)[^:\n]*\s*:\s*\n*([^\n]+)", text, re.I)
                if m_gen:
                    detail["fee_general_obc"] = m_gen.group(1).strip()

                m_sc = re.search(r"(?:(?:OBC\s*/\s*)?SC\s*/\s*ST|Reserved)[^:\n]*\s*:\s*\n*([^\n]+)", text, re.I)
                if m_sc:
                    detail["fee_sc_st"] = m_sc.group(1).strip()

                m_ph = re.search(r"(?:PH|Divyang)[^:\n]*\s*:\s*\n*([^\n]+)", text, re.I)
                if m_ph:
                    detail["fee_ph"] = m_ph.group(1).strip()

            # Age Limit block
            if "Age Limit" in text:
                m_as_on = re.search(r"Age Limit as on\s*([^\n:]+)", text, re.I)
                if m_as_on:
                    detail["age_cutoff"] = m_as_on.group(1).strip()

                m_min_age = re.search(r"Minimum Age\s*:\s*\n*([^\n]+)", text, re.I)
                if m_min_age:
                    detail["min_age"] = m_min_age.group(1).strip()

                m_max_age = re.search(r"Maximum Age\s*:\s*\n*([^\n]+)", text, re.I)
                if m_max_age:
                    detail["max_age"] = m_max_age.group(1).strip()

                # Fallback: check for age ranges like '18-30 Years', '20-25 Years'
                if not detail["min_age"] or not detail["max_age"]:
                    age_ranges = re.findall(r"(\d{2})\s*-\s*(\d{2})\s*Years", text, re.I)
                    if age_ranges:
                        mins = [int(r[0]) for r in age_ranges]
                        maxs = [int(r[1]) for r in age_ranges]
                        if not detail["min_age"]:
                            detail["min_age"] = f"{min(mins)} Years"
                        if not detail["max_age"]:
                            detail["max_age"] = f"{max(maxs)} Years"

        # 4. Advt No / Total Posts
        m_advt = re.search(r"Advt\.?\s*No\.?\s*:?\s*([^\n]+)", soup.get_text(), re.I)
        if m_advt:
            detail["advt_no"] = m_advt.group(1).strip()[:50]

        m_tot = re.search(r"(?:Total\s*:\s*|Total Vacancy\s*:\s*)(\d+)\s*Post", soup.get_text(), re.I)
        if m_tot:
            try:
                detail["total_posts"] = int(m_tot.group(1))
            except ValueError:
                pass

        # 4b. 2-Cell Key-Value Row Parsing (handles mirror format: Apply Online Start Date, Fees, Age)
        for tr in soup.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            if len(cells) >= 2:
                lbl = cells[0].lower().strip()
                val = cells[1].strip()
                if ("apply online start" in lbl or "application begin" in lbl) and not detail["application_begin"]:
                    detail["application_begin"] = val
                elif ("apply online last" in lbl or "last date" in lbl) and not detail["last_date_apply"]:
                    detail["last_date_apply"] = val
                elif "fee" in lbl and "last date" in lbl and not detail["last_date_fee"]:
                    detail["last_date_fee"] = val
                elif "exam date" in lbl and not detail["exam_date"]:
                    detail["exam_date"] = val
                elif (("general" in lbl or "obc" in lbl) and "fee" in lbl) or lbl in ["general / obc", "general / obc / ews"]:
                    if not detail["fee_general_obc"]:
                        detail["fee_general_obc"] = val
                elif ("sc" in lbl or "st" in lbl) and not detail["fee_sc_st"]:
                    detail["fee_sc_st"] = val
                elif "minimum age" in lbl and not detail["min_age"]:
                    detail["min_age"] = val
                elif "maximum age" in lbl and not detail["max_age"]:
                    detail["max_age"] = val
                elif "age as on" in lbl and not detail["age_reference_date"]:
                    detail["age_reference_date"] = val

        # 5. Extract Eligibility & Post-Wise Vacancy Breakdown from Tables
        detail["post_wise_vacancies"] = []
        for tr in soup.find_all("tr"):
            cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
            cells_lower = [c.lower() for c in cells]

            # Eligibility table
            if not detail["eligibility"] and len(cells) >= 3 and any("eligibility" in c for c in cells_lower):
                next_tr = tr.find_next_sibling("tr")
                if next_tr:
                    next_cells = [td.get_text(" ", strip=True) for td in next_tr.find_all(["td", "th"])]
                    if len(next_cells) >= 3:
                        detail["eligibility"] = next_cells[2]

            # Category Wise Breakdown table: e.g. ['Post Name', 'UR', 'EWS', 'OBC', 'SC', 'ST', 'Total Post']
            if len(cells) >= 6 and any("ur" == c for c in cells_lower):
                headers = [c.strip() for c in cells]
                curr = tr.find_next_sibling("tr")
                while curr:
                    c_cells = [td.get_text(" ", strip=True) for td in curr.find_all(["td", "th"])]
                    if len(c_cells) == len(headers):
                        post_name = c_cells[0]
                        row_dict = {"post_name": post_name}
                        for h, val in zip(headers[1:], c_cells[1:]):
                            num = re.sub(r"[^0-9]", "", val)
                            row_dict[h] = int(num) if num else val
                        detail["post_wise_vacancies"].append(row_dict)
                        curr = curr.find_next_sibling("tr")
                    else:
                        break

                if detail["post_wise_vacancies"] and not detail["category_vacancies"]:
                    # Keep first row or aggregate as summary
                    detail["category_vacancies"] = {k: v for k, v in detail["post_wise_vacancies"][0].items() if k != "post_name"}

        # 6. Extract Official Action Links (Notification PDF, Syllabus, Apply Online, Official Portal)
        for tr in soup.find_all("tr"):
            cells = tr.find_all(["td", "th"])
            if len(cells) >= 2:
                label = cells[0].get_text(" ", strip=True).lower()
                a_tags = cells[1].find_all("a", href=True)
                for a in a_tags:
                    href = a["href"].strip()
                    if "apply online" in label or "apply" in label:
                        detail["official_links"]["apply_online"] = href
                    elif "download notification" in label or "notification" in label:
                        detail["official_links"]["notification_pdf"] = href
                    elif "official website" in label:
                        detail["official_links"]["official_website"] = href
                    elif "download syllabus" in label or "syllabus" in label:
                        detail["official_links"]["syllabus"] = href
                    elif "download exam date" in label or "exam date" in label:
                        detail["official_links"]["exam_date_notice"] = href
                    elif "admit card" in label:
                        detail["official_links"]["admit_card"] = href
                        detail["official_links"]["syllabus"] = href
                    elif "admit card" in label:
                        detail["official_links"]["admit_card"] = href

        return detail

    def download_pdf(self, pdf_url: str, output_path: str) -> Optional[int]:
        """
        Downloads an official notification PDF file to disk.
        Handles state government portal SSL certificates gracefully.
        Returns size in bytes if successful, or None on failure.
        """
        import urllib3
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        
        try:
            os.makedirs(os.path.dirname(output_path), exist_ok=True)
            # Try with standard session first
            try:
                resp = self.session.get(pdf_url, stream=True, timeout=40)
            except Exception:
                # State government portals (nic.in / gov.in) frequently have outdated cert chains
                resp = requests.get(pdf_url, headers=DEFAULT_HEADERS, stream=True, timeout=40, verify=False)

            if resp.status_code != 200:
                return None
            total_bytes = 0
            with open(output_path, "wb") as f:
                if hasattr(resp, "iter_content"):
                    for chunk in resp.iter_content(chunk_size=65536):
                        if chunk:
                            f.write(chunk)
                            total_bytes += len(chunk)
                else:
                    f.write(resp.content)
                    total_bytes = len(resp.content)
            return total_bytes
        except Exception as e:
            print(f"[!] Error downloading notification PDF from {pdf_url}: {e}", file=sys.stderr)
            return None

    def crawl(
        self,
        url: Optional[str] = None,
        html_file: Optional[str] = None,
        limit: Optional[int] = None,
        deep: bool = False,
        download_pdfs: bool = False,
        pdf_dir: str = "data/notifications",
        category: Optional[str] = None,
        search_query: Optional[str] = None,
        max_workers: int = 5
    ) -> List[Dict[str, Any]]:
        """
        Executes vacancy crawl. Reads from live URL or local HTML file.
        Optionally scrapes deep details and dumps official notification PDFs locally.
        """
        # Step 1: Load main listings HTML with automatic mirror failover
        if html_file:
            print(f"[*] Reading offline HTML file: {html_file}")
            with open(html_file, "r", encoding="utf-8", errors="ignore") as f:
                html_content = f.read()
        else:
            candidates = [
                url or f"{self.base_url}/latestjob/",
                "https://www.rojgarresult.com/latestjob/",
                "https://www.sarkariresult.com/"
            ]
            html_content = None
            for target_url in candidates:
                print(f"[*] Fetching vacancy catalog from: {target_url}")
                html_content = self.fetch_url(target_url)
                if html_content and len(html_content) > 1000:
                    print(f"[✓] Connected successfully to catalog: {target_url}")
                    break
                print(f"[!] Access restricted / forbidden on {target_url}. Trying next mirror source...")

            if not html_content:
                print("[-] Failed to fetch listings HTML from all sources. Exiting.", file=sys.stderr)
                return []

        # Step 2: Parse all listings
        jobs = self.parse_listings_html(html_content)
        print(f"[+] Total vacancies found in catalog: {len(jobs)}")

        # Step 3: Apply Filters (Category, Search query)
        if category:
            cat_lower = category.lower()
            jobs = [j for j in jobs if cat_lower in j["category"].lower()]
            print(f"[*] Filtered by category '{category}': {len(jobs)} remaining")

        if search_query:
            q_lower = search_query.lower()
            jobs = [j for j in jobs if q_lower in j["title"].lower() or q_lower in j["organization"].lower()]
            print(f"[*] Filtered by search '{search_query}': {len(jobs)} remaining")

        # Step 4: Apply Limit
        if limit and limit > 0:
            jobs = jobs[:limit]
            print(f"[*] Truncated to first {len(jobs)} vacancies (as per --limit {limit})")

        # Step 5: Deep Crawl detail pages if requested or if download_pdfs is enabled
        if (deep or download_pdfs) and jobs:
            print(f"[*] Deep scraping detailed criteria for {len(jobs)} jobs using {max_workers} threads...")
            self._enrich_jobs_deep(jobs, max_workers)

        # Step 6: Download official notification PDFs if requested
        if download_pdfs and jobs:
            print(f"[*] Downloading notification PDFs to '{pdf_dir}' for Gemini / DB ingestion...")
            os.makedirs(pdf_dir, exist_ok=True)
            download_count = 0
            for j in jobs:
                pdf_url = None
                if j.get("is_direct_pdf"):
                    pdf_url = j.get("url")
                elif "details" in j:
                    pdf_url = j["details"].get("official_links", {}).get("notification_pdf")

                if pdf_url and pdf_url.startswith("http"):
                    pdf_filename = f"{j['id']}.pdf"
                    target_pdf_path = os.path.join(pdf_dir, pdf_filename)
                    print(f"    --> Downloading Gazette PDF for '{j['title'][:40]}...'")
                    size = self.download_pdf(pdf_url, target_pdf_path)
                    if size and size > 1000:
                        j["local_pdf_path"] = target_pdf_path
                        j["pdf_size_bytes"] = size
                        j["pdf_status"] = "downloaded"
                        download_count += 1
                        print(f"        [✓] Saved Gazette {round(size / 1024, 1)} KB -> {target_pdf_path}")
                    else:
                        j["pdf_status"] = "failed_or_empty"
                else:
                    j["pdf_status"] = "no_pdf_url"

                # Also download Syllabus PDF if available
                syllabus_url = j.get("details", {}).get("official_links", {}).get("syllabus")
                if syllabus_url and syllabus_url.startswith("http"):
                    syllabus_filename = f"{j['id']}-syllabus.pdf"
                    target_syl_path = os.path.join(pdf_dir, syllabus_filename)
                    print(f"    --> Downloading Syllabus PDF for '{j['title'][:40]}...'")
                    syl_size = self.download_pdf(syllabus_url, target_syl_path)
                    if syl_size and syl_size > 1000:
                        j["local_syllabus_path"] = target_syl_path
                        j["syllabus_size_bytes"] = syl_size
                        print(f"        [✓] Saved Syllabus {round(syl_size / 1024, 1)} KB -> {target_syl_path}")
            print(f"[✓] Downloaded {download_count} notification PDFs into '{pdf_dir}'.")

        return jobs

    def _enrich_jobs_deep(self, jobs: List[Dict[str, Any]], max_workers: int):
        """
        Fetches individual vacancy pages concurrently to populate deep fields.
        """
        def fetch_and_parse(job: Dict[str, Any]):
            # Skip direct PDF links
            if job.get("is_direct_pdf") or not job["url"].startswith("http"):
                return job

            # Add jitter between 0.1s and 0.4s to be courteous
            time.sleep(random.uniform(*self.delay_range))
            html = self.fetch_url(job["url"])
            if html:
                details = self.parse_job_detail_html(html, job["url"])
                # Merge details into job dictionary
                job["details"] = details
                if details.get("total_posts") and not job.get("posts"):
                    job["posts"] = details["total_posts"]
                if details.get("last_date_apply") and not job.get("last_date"):
                    job["last_date"] = details["last_date_apply"]
            return job

        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_job = {executor.submit(fetch_and_parse, job): job for job in jobs}
            done_count = 0
            for future in as_completed(future_to_job):
                done_count += 1
                if done_count % 5 == 0 or done_count == len(jobs):
                    print(f"    Progress: {done_count}/{len(jobs)} detail pages scraped")


def export_to_json(jobs: List[Dict[str, Any]], filepath: str):
    """
    Saves vacancies to structured JSON file.
    """
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(jobs, f, indent=2, ensure_ascii=False)
    print(f"[✓] Exported {len(jobs)} vacancies to JSON: {filepath}")


def export_to_csv(jobs: List[Dict[str, Any]], filepath: str):
    """
    Flattens and saves vacancies to CSV file.
    """
    fieldnames = [
        "id", "title", "organization", "category", "posts", "last_date",
        "status", "url", "is_direct_pdf", "application_begin",
        "fee_general", "fee_sc_st", "min_age", "max_age",
        "apply_online_url", "notification_pdf_url"
    ]
    with open(filepath, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for j in jobs:
            row = {
                "id": j.get("id"),
                "title": j.get("title"),
                "organization": j.get("organization"),
                "category": j.get("category"),
                "posts": j.get("posts") or "",
                "last_date": j.get("last_date") or "",
                "status": j.get("status"),
                "url": j.get("url"),
                "is_direct_pdf": j.get("is_direct_pdf")
            }
            # Unpack details if present
            details = j.get("details", {})
            row["application_begin"] = details.get("application_begin", "")
            row["fee_general"] = details.get("fee_general_obc", "")
            row["fee_sc_st"] = details.get("fee_sc_st", "")
            row["min_age"] = details.get("min_age", "")
            row["max_age"] = details.get("max_age", "")
            links = details.get("official_links", {})
            row["apply_online_url"] = links.get("apply_online", "")
            row["notification_pdf_url"] = links.get("notification_pdf", "")
            writer.writerow(row)
    print(f"[✓] Exported {len(jobs)} vacancies to CSV: {filepath}")


def sync_to_supabase(
    jobs: List[Dict[str, Any]],
    supabase_url: Optional[str] = None,
    supabase_key: Optional[str] = None,
    bucket_name: str = "recruitment-docs"
):
    """
    Upserts crawled vacancy records and uploads PDFs directly to Supabase DB & Storage.
    Reads from environment variables SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY if not passed.
    """
    sb_url = (supabase_url or os.environ.get("SUPABASE_URL", "")).rstrip("/")
    sb_key = supabase_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get("SUPABASE_KEY", "")

    if not sb_url or not sb_key:
        print("[!] Supabase URL or Key missing. Set SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY to sync.", file=sys.stderr)
        return

    headers = {
        "apikey": sb_key,
        "Authorization": f"Bearer {sb_key}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates"
    }

    print(f"\n[*] ⚡ Syncing {len(jobs)} vacancies to Supabase ({sb_url})...")
    
    success_count = 0
    for j in jobs:
        job_id = j["id"]

        # 1. Upload Notification PDF to Supabase Storage if present
        local_pdf = j.get("local_pdf_path")
        if local_pdf and os.path.exists(local_pdf):
            storage_path = f"notifications/{job_id}.pdf"
            bucket_url = f"{sb_url}/storage/v1/object/{bucket_name}/{storage_path}"
            try:
                with open(local_pdf, "rb") as f:
                    file_data = f.read()
                upload_resp = requests.post(
                    bucket_url,
                    headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}", "Content-Type": "application/pdf"},
                    data=file_data,
                    timeout=30
                )
                if upload_resp.status_code in [200, 201]:
                    cdn_url = f"{sb_url}/storage/v1/object/public/{bucket_name}/{storage_path}"
                    j["supabase_notification_pdf_url"] = cdn_url
                    print(f"    [✓] Uploaded Gazette PDF to Supabase: {storage_path}")
            except Exception as e:
                print(f"    [!] Error uploading PDF to Supabase Storage: {e}", file=sys.stderr)

        # 2. Upload Syllabus PDF to Supabase Storage if present
        local_syl = j.get("local_syllabus_path")
        if local_syl and os.path.exists(local_syl):
            syl_storage_path = f"syllabus/{job_id}-syllabus.pdf"
            bucket_url = f"{sb_url}/storage/v1/object/{bucket_name}/{syl_storage_path}"
            try:
                with open(local_syl, "rb") as f:
                    file_data = f.read()
                upload_resp = requests.post(
                    bucket_url,
                    headers={"apikey": sb_key, "Authorization": f"Bearer {sb_key}", "Content-Type": "application/pdf"},
                    data=file_data,
                    timeout=30
                )
                if upload_resp.status_code in [200, 201]:
                    cdn_url = f"{sb_url}/storage/v1/object/public/{bucket_name}/{syl_storage_path}"
                    j["supabase_syllabus_pdf_url"] = cdn_url
                    print(f"    [✓] Uploaded Syllabus PDF to Supabase: {syl_storage_path}")
            except Exception as e:
                print(f"    [!] Error uploading Syllabus to Supabase Storage: {e}", file=sys.stderr)

        # 3. Upsert record into 'vacancies' table
        det = j.get("details", {})
        dates_payload = {
            "application_begin": det.get("application_begin"),
            "last_date_apply": det.get("last_date_apply"),
            "last_date_fee": det.get("last_date_fee"),
            "exam_date": det.get("exam_date"),
            "listing_last_date": j.get("last_date")
        }
        fees_payload = {
            "general_obc": det.get("fee_general_obc"),
            "sc_st": det.get("fee_sc_st"),
            "ph": det.get("fee_ph")
        }
        age_payload = {
            "min_age": det.get("min_age"),
            "max_age": det.get("max_age"),
            "reference_date": det.get("age_reference_date")
        }

        payload = {
            "id": job_id,
            "title": j["title"],
            "org": j.get("organization") or "",
            "post_name": j["title"],
            "total_posts": str(j.get("posts") or det.get("total_posts") or ""),
            "detail_url": j.get("url") or "",
            "dates": dates_payload,
            "fees": fees_payload,
            "age_limit": age_payload,
            "posts_matrix": det.get("post_wise_vacancies", []),
            "links": det.get("official_links", {}),
            "notification_pdf_storage_url": j.get("supabase_notification_pdf_url") or det.get("official_links", {}).get("notification_pdf"),
            "syllabus_storage_url": j.get("supabase_syllabus_pdf_url") or det.get("official_links", {}).get("syllabus"),
            "source_tag": j.get("category", "sarkari_result"),
            "updated_at": "now()"
        }

        endpoint = f"{sb_url}/rest/v1/vacancies?on_conflict=id"
        try:
            resp = requests.post(endpoint, headers=headers, json=payload, timeout=15)
            if resp.status_code in [200, 201]:
                success_count += 1
                print(f"    [✓] Supabase DB Upserted: {job_id}")
            else:
                print(f"    [!] Supabase DB Warning ({resp.status_code}): {resp.text[:100]}")
        except Exception as e:
            print(f"    [!] Failed to upsert {job_id} to Supabase: {e}", file=sys.stderr)

    print(f"[✓] Supabase sync completed: {success_count}/{len(jobs)} records upserted successfully!\n")


def display_results_table(jobs: List[Dict[str, Any]], show_details: bool = False):
    """
    Renders a clean terminal summary table.
    """
    if not jobs:
        print("[!] No jobs to display.")
        return

    if HAVE_RICH:
        console = Console()
        table = Table(title=f"🏛️ Sarkari Result Recruitment Feed ({len(jobs)} Items)", show_lines=True)
        table.add_column("#", style="dim", width=4)
        table.add_column("Category", style="cyan", width=22)
        table.add_column("Job Title & Organization", style="bold white", width=46)
        table.add_column("Posts", style="magenta", justify="right", width=8)
        table.add_column("Last Date", style="yellow", width=14)
        table.add_column("Status", style="green", width=14)
        if show_details:
            table.add_column("Age & Fees", style="blue", width=18)
            table.add_column("Official Links", style="underline blue", width=24)

        for i, j in enumerate(jobs[:50], 1):
            posts_str = str(j.get("posts")) if j.get("posts") else "—"
            last_date_str = j.get("last_date") or "—"
            status_str = j.get("status", "Active")
            title_text = f"{j['title']}\n[dim]{j['organization']}[/dim]"

            if show_details and "details" in j:
                det = j["details"]
                age_str = f"Age: {det.get('min_age') or '?'}-{det.get('max_age') or '?'}\nFee: {det.get('fee_general_obc') or '—'}"
                links = det.get("official_links", {})
                apply_str = f"Apply: {links.get('apply_online', '—')[:20]}...\nPDF: {links.get('notification_pdf', '—')[:20]}..."
                table.add_row(str(i), j["category"], title_text, posts_str, last_date_str, status_str, age_str, apply_str)
            else:
                table.add_row(str(i), j["category"], title_text, posts_str, last_date_str, status_str)

        console.print(table)
        if len(jobs) > 50:
            console.print(f"[dim]Showing first 50 of {len(jobs)} items in console. Full dataset saved to file.[/dim]")
    else:
        # Standard ASCII format
        print("\n" + "=" * 110)
        print(f"{'#':<4} {'Category':<22} {'Posts':<7} {'Last Date':<14} {'Title'}")
        print("=" * 110)
        for i, j in enumerate(jobs[:40], 1):
            posts_str = str(j.get("posts") or "—")
            last_date = j.get("last_date") or "—"
            print(f"{i:<4} {j['category'][:21]:<22} {posts_str:<7} {last_date[:13]:<14} {j['title'][:60]}")
        print("=" * 110 + "\n")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Sarkari Result Vacancy Crawler & Data Ingestion Tool",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # 1. Fetch live jobs and save to vacancies.json:
  python sarkari_crawler.py --limit 30 --output-json vacancies.json

  # 2. Offline Mode: Parse the local response snippet provided by user:
  python sarkari_crawler.py --html-file data/sample_latestjob_response.html

  # 3. Filter by category (e.g. Railways, Banking, Police):
  python sarkari_crawler.py --category railways --limit 20

  # 4. Deep crawl top 10 vacancies to get age, fee, and apply links:
  python sarkari_crawler.py --limit 10 --deep --output-json deep_vacancies.json --output-csv deep_vacancies.csv
        """
    )
    parser.add_argument("--url", default="https://www.sarkariresult.com/latestjob/", help="Target URL (default: /latestjob/)")
    parser.add_argument("--html-file", help="Path to local HTML file to parse (Offline Mode)")
    parser.add_argument("--limit", type=int, default=None, help="Limit number of vacancies to extract")
    parser.add_argument("--category", help="Filter by category (e.g. Railways, Banking, SSC, Police, Teaching)")
    parser.add_argument("--search", help="Search keyword in title or organization")
    parser.add_argument("--deep", action="store_true", help="Crawl detail pages to extract fees, age limits, and official links")
    parser.add_argument("--download-pdfs", action="store_true", help="Download official notification PDF files locally for Gemini / DB ingestion")
    parser.add_argument("--pdf-dir", default="data/notifications", help="Directory where notification PDFs will be saved (default: data/notifications)")
    parser.add_argument("--supabase", action="store_true", help="Upsert crawled vacancies and upload PDFs to Supabase DB & Storage")
    parser.add_argument("--supabase-url", help="Supabase Project URL (or set SUPABASE_URL env var)")
    parser.add_argument("--supabase-key", help="Supabase Service Role Key (or set SUPABASE_SERVICE_ROLE_KEY env var)")
    parser.add_argument("--interval-hours", type=float, default=None, help="Run as a continuous recurring cron daemon every N hours (e.g. --interval-hours 4)")
    parser.add_argument("--workers", type=int, default=5, help="Number of concurrent workers for deep scraping (default: 5)")
    parser.add_argument("--output-json", default="vacancies.json", help="Path to save JSON output (default: vacancies.json)")
    parser.add_argument("--output-csv", help="Path to save CSV output (optional)")
    parser.add_argument("--no-table", action="store_true", help="Suppress terminal table output")
    return parser


def run_pipeline(crawler: SarkariCrawler, args):
    """
    Executes a single crawl & export cycle.
    """
    jobs = crawler.crawl(
        url=args.url,
        html_file=args.html_file,
        limit=args.limit,
        deep=args.deep,
        download_pdfs=args.download_pdfs or args.supabase,
        pdf_dir=args.pdf_dir,
        category=args.category,
        search_query=args.search,
        max_workers=args.workers
    )

    if not jobs:
        print("[!] No vacancies found or matched the criteria.")
        return

    # Display table in terminal
    if not args.no_table:
        display_results_table(jobs, show_details=args.deep)

    # Save JSON
    if args.output_json:
        export_to_json(jobs, args.output_json)

    # Save CSV if specified
    if args.output_csv:
        export_to_csv(jobs, args.output_csv)

    # Sync directly to Supabase if requested or env vars present
    if args.supabase or os.environ.get("SUPABASE_URL"):
        sync_to_supabase(jobs, supabase_url=args.supabase_url, supabase_key=args.supabase_key)

    print(f"\n[✓] Crawl cycle complete! Successfully processed {len(jobs)} vacancies.\n")


def main():
    parser = build_arg_parser()
    args = parser.parse_args()

    crawler = SarkariCrawler()

    if args.interval_hours and args.interval_hours > 0:
        interval_secs = int(args.interval_hours * 3600)
        print(f"\n[*] ⏰ Running in DAEMON / CRON MODE. Schedule: Every {args.interval_hours} hours ({interval_secs}s).")
        print("[*] Press Ctrl+C at any time to stop.\n")
        
        cycle = 1
        while True:
            current_time = time.strftime('%Y-%m-%d %H:%M:%S')
            print(f"\n{'='*65}\n[⏰ CRON CYCLE #{cycle}] Starting automated crawl at {current_time}...\n{'='*65}")
            try:
                run_pipeline(crawler, args)
            except Exception as e:
                print(f"[!] Error in cron cycle #{cycle}: {e}", file=sys.stderr)
            
            next_time = time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(time.time() + interval_secs))
            print(f"[*] Cycle #{cycle} finished. Sleeping for {args.interval_hours} hours. Next run at: {next_time}\n")
            cycle += 1
            try:
                time.sleep(interval_secs)
            except KeyboardInterrupt:
                print("\n[!] Daemon stopped by user. Exiting cleanly.")
                break
    else:
        # Standard one-off execution
        run_pipeline(crawler, args)


if __name__ == "__main__":
    main()
