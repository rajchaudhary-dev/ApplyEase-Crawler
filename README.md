# ApplyEase — Sarkari Result Vacancy Crawler & Supabase Ingestion

Autonomous recruitment intelligence crawler for Indian government job updates (UPSC, SSC, State PSCs, IBPS, Railways).

Crawls vacancy postings, parses deep criteria (application dates, category fees, age limits, post-wise vacancy matrices), downloads official Gazette & Syllabus PDFs, and dumps structured records directly into **Supabase DB & Storage**.

---

## ⚡ Architecture

```
[ Sarkari Result ]
       │  (Runs every 6 hours via GitHub Actions)
       ▼
[ sarkari_crawler.py ] ──► Dumps rows & PDFs ──► [ Supabase DB & Storage ]
                                                          │
                                                          ▼
                                                  [ Gemini Agent ]
                                            (Reads data & PDFs directly 
                                             to send personalized job 
                                             alerts & audits)
```

---

## 🚀 Features

- **Anti-Bot Resilience**: Authenticates with Chrome browser headers (`Sec-Ch-Ua`, `Accept`, `Referer`, `User-Agent`).
- **Dual-Listing Parsing**: Handles both `<ul class="sarkari-quick-list">` and `<ul class="wp-block-list">`.
- **Deep Extraction (`--deep`)**:
  - Application start date, last date, fee last date, exam date
  - Reservation-wise fees (General, OBC, SC/ST, PH)
  - Age limits (Min, Max, Cutoff date)
  - Multi-row force / post-wise matrices
  - Essential educational eligibility
- **Document Harvesting (`--download-pdfs`)**:
  - Official Gazette Notification PDFs
  - Official Paper I & II Syllabus PDFs
  - SSL-fallback for state government portals (`nic.in`, `gov.in`)
- **Direct Supabase Sync (`--supabase`)**:
  - Upserts structured JSONB rows into `public.vacancies`
  - Uploads PDFs to `recruitment-docs` Supabase Storage bucket
- **Cloud Cron (`.github/workflows/sarkari_sync_cron.yml`)**:
  - Runs automatically on GitHub Actions every 6 hours (`0 */6 * * *`).

---

## 📦 Setup & Usage

### 1. Local Run
```bash
pip install -r requirements.txt

# Crawl 20 vacancies and save locally
python sarkari_crawler.py --limit 20 --deep --download-pdfs --output-json vacancies.json

# Sync directly to Supabase
python sarkari_crawler.py --limit 30 --deep --download-pdfs --supabase
```

### 2. GitHub Actions Automation
Add these 2 repository secrets under **Settings ➔ Secrets and variables ➔ Actions**:
- `SUPABASE_URL`: Your Supabase Project URL (`https://xyz.supabase.co`)
- `SUPABASE_SERVICE_ROLE_KEY`: Your Supabase service role secret key

The workflow will run every 6 hours automatically, or trigger manually from the **Actions** tab.
