# GitHub Actions IP Rotation Proxy Farm for Web Scraping

A production-ready GitHub Actions workflow that uses GitHub's infrastructure to get free rotating IP addresses for web scraping. Each workflow run executes on a fresh Microsoft Azure VM, giving you a unique IP address per job.

## How It Works

GitHub Actions runners run on Azure VMs with dynamic IPs. By using a matrix strategy with parallel jobs, you get multiple unique IPs simultaneously — no proxy service needed.

## Project Structure

```
proxy-farm/
├── .github/
│   └── workflows/
│       ├── run-scraper.yml
│       └── proxy-test.yml
├── scraper/
│   ├── angi_scraper.py
│   ├── proxy_receiver.py
│   └── requirements.txt
├── results/
│   └── .gitkeep
└── README.md
```

## Setup

1. Create a new GitHub repository
2. Upload all files in the structure above
3. Go to **Settings > Secrets and variables > Actions**
4. Add a repository secret named `WEBHOOK_URL` (see n8n section below)

## Workflows

### 1. Run Scraper (`run-scraper.yml`)

- **Triggers:** Manual (`workflow_dispatch`) + every 6 hours (`schedule`)
- **Matrix:** 7 parallel jobs, one per Ohio city:
  - Columbus
  - Cleveland
  - Cincinnati
  - Toledo
  - Akron
  - Dayton
  - Youngstown
- Each job:
  1. Checks out the repo
  2. Sets up Python 3.11
  3. Installs dependencies
  4. Runs `scraper/angi_scraper.py` with the `CITY` env variable
  5. Uploads results as `results-{city}` artifact
  6. POSTs CSV to your webhook URL (if configured)

**Manual trigger:** Go to **Actions > Run Angi Scraper > Run workflow**, select the branch, and click **Run workflow**.

### 2. Proxy Test (`proxy-test.yml`)

- **Trigger:** Manual only (`workflow_dispatch`)
- **Matrix:** 10 parallel jobs
- Each job runs `curl https://api.ipify.org?format=json` to show its IP
- After all jobs complete, an `ips.txt` artifact is uploaded containing all 10 IPs
- Checks for duplicate IPs and warns if any are found

**Manual trigger:** Go to **Actions > Proxy Test > Run workflow**.

## Download Artifacts

After a run completes:

1. Go to the workflow run summary
2. Scroll to the **Artifacts** section
3. Click the artifact name (e.g., `results-columbus`) to download
4. Extract the ZIP to get the CSV files

## Scraper Details

`angi_scraper.py` scrapes Angi's roofing contractors listing for a given Ohio city:

- Reads the target city from the `CITY` environment variable
- Uses `httpx` with realistic browser headers
- Scrapes paginated results (`?page=2`, `?page=3`, etc.)
- Parses `<script id="__NEXT_DATA__">` JSON for structured data
- Falls back to BeautifulSoup CSS selectors (`.provider-card`) if `__NEXT_DATA__` is missing
- Extracts these fields per contractor:
  - businessName
  - phoneNumber
  - overallStarRating
  - reviewCount
  - yearsInBusiness
  - website
  - address (street, city, state, zip)
  - licenseNumber (if available)
  - serviceAreas
- Marks `is_new_roofer = True` if reviewCount <= 15 OR yearsInBusiness <= 3
- Saves two CSVs:
  - `all_{city}_roofing.csv` — all contractors
  - `new_roofers_{city}.csv` — filtered new/small roofers only
- Retries 3 times with 5s delay on failure
- Random delay between pages: 1.5–4 seconds

## Proxy Receiver

`proxy_receiver.py` is a helper for processing webhook payloads:

```bash
python proxy_receiver.py <webhook_payload.json>
```

It:
- Decodes base64 CSV from webhook payload
- Deduplicates by `businessName` + `phoneNumber`
- Merges into `results/ohio_all_cities_master.csv`
- Filters and saves `results/ohio_new_roofers_master.csv`

## Connect to n8n

### Step 1: Set Up Webhook URL

1. In n8n, create a new workflow with a **Webhook** node
2. Set **HTTP Method** to `POST`
3. Set **Response Mode** to `Respond when webhook is called`
4. Copy the webhook URL (e.g., `https://your-n8n.com/webhook/proxy-farm`)
5. Add this URL as the `WEBHOOK_URL` repository secret in GitHub

### Step 2: Configure n8n Workflow

After the Webhook node, add these nodes in sequence:

1. **Function node** — decode base64 CSV:

```javascript
// Decode base64 CSV from webhook payload
const csvBase64 = items[0].json.data;
const csvText = Buffer.from(csvBase64, 'base64').toString('utf-8');
const lines = csvText.split('\n').filter(l => l.trim());

const headers = lines[0].split(',');
const records = [];
for (let i = 1; i < lines.length; i++) {
  const values = lines[i].split(',');
  const record = {};
  headers.forEach((h, idx) => {
    record[h] = values[idx] || '';
  });
  record.city = items[0].json.city;
  record.run_id = items[0].json.run_id;
  records.push({ json: record });
}
return records;
```

2. **CSV Parse node** (optional if using Function above) — parse CSV data

3. **Filter node** — keep only rows where `is_new_roofer` is true

4. **Output node** — send to Google Sheets, Airtable, or any destination

### Step 3: Test the Connection

1. Run the **Proxy Test** workflow to confirm IP rotation
2. Run the **Run Angi Scraper** workflow manually
3. Check n8n execution history for incoming webhook events
4. Verify data appears in your destination

## Configuration

| Variable | Description | Required |
|----------|-------------|----------|
| `CITY` | Target city name (lowercase) | Set per matrix job |
| `WEBHOOK_URL` | n8n webhook URL for POSTing results | Optional (GitHub Secret) |
| `GITHUB_RUN_ID` | Current run ID | Auto-provided by GitHub |

## Requirements

- Python 3.11+
- httpx 0.27.0
- beautifulsoup4 4.12.3
- pandas 2.2.2
- lxml 5.2.1

## Notes

- Each matrix job runs on a **fresh** `ubuntu-latest` runner with a **unique** Azure IP
- Jobs have `continue-on-error: true` so one city failing doesn't stop others
- Artifacts are retained for 30 days (scraper) or 7 days (proxy test)
- Use `actions/upload-artifact@v4` (v3 is deprecated)
- The webhook POST sends CSV as base64 in JSON body:
  ```json
  {"city": "columbus", "data": "<base64_csv>", "run_id": "123456789"}
  ```
