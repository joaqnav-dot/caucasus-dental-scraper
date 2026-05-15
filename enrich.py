"""
Enrichment pipeline for dental clinic leads.
For each clinic:
  - Clinics WITH website  → scrape for emails, WhatsApp, Instagram, Facebook
  - Clinics WITHOUT website → DuckDuckGo search to find website + social, then scrape
"""

import csv, re, time, json, sys, os
import requests
from bs4 import BeautifulSoup
from duckduckgo_search import DDGS

INPUT  = os.environ.get('INPUT_FILE',  'output.csv')
OUTPUT = os.environ.get('OUTPUT_FILE', 'enriched.csv')

HEADERS = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36'}

# ── Extractors ────────────────────────────────────────────────────────────────

EMAIL_RE = re.compile(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}')
SKIP_EMAILS = {'example.com','sentry.io','wixpress.com','schema.org','email.com','domain.com'}

def extract_emails(text):
    found = EMAIL_RE.findall(text)
    return list({e.lower() for e in found if not any(s in e for s in SKIP_EMAILS)})

def extract_whatsapp(soup):
    numbers = []
    if not soup: return numbers
    for a in soup.find_all('a', href=True):
        href = a['href']
        if 'wa.me/' in href or 'api.whatsapp.com' in href:
            m = re.search(r'(\d{7,15})', href)
            if m: numbers.append('+' + m.group(1))
    return list(set(numbers))

def extract_instagram(soup):
    links = []
    if not soup: return links
    for a in soup.find_all('a', href=True):
        href = a['href'].rstrip('/')
        if 'instagram.com/' in href:
            m = re.search(r'instagram\.com/([^/?#\s]+)', href)
            handle = m.group(1) if m else ''
            if handle and handle not in ('p','explore','accounts','stories','reels','reel','tv',''):
                links.append('https://instagram.com/' + handle)
    return list(set(links))

def extract_facebook(soup):
    links = []
    if not soup: return links
    for a in soup.find_all('a', href=True):
        href = a['href'].rstrip('/')
        if 'facebook.com/' in href:
            m = re.search(r'facebook\.com/([^/?#\s]+)', href)
            handle = m.group(1) if m else ''
            if handle and handle not in ('sharer','share','dialog','plugins','login','home.php',''):
                links.append('https://facebook.com/' + handle)
    return list(set(links))

# ── Web scraper ───────────────────────────────────────────────────────────────

def scrape_url(url, timeout=12):
    try:
        r = requests.get(url, timeout=timeout, headers=HEADERS, allow_redirects=True)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, 'html.parser')
            return soup, r.text
    except Exception as e:
        pass
    return None, ''

def scrape_contact_pages(base_url, soup):
    """Also try /contact and /about pages for more data."""
    extra_text = ''
    extra_soup = None
    for slug in ['/contact', '/contact-us', '/about', '/kontakt']:
        try:
            url = base_url.rstrip('/') + slug
            s, t = scrape_url(url, timeout=8)
            if t: extra_text += t
        except:
            pass
    return extra_text

# ── DuckDuckGo search ─────────────────────────────────────────────────────────

def ddg_search(query, max_results=3, retries=2):
    for attempt in range(retries):
        try:
            with DDGS() as ddgs:
                results = list(ddgs.text(query, max_results=max_results))
                return results
        except Exception as e:
            time.sleep(3 * (attempt + 1))
    return []

def find_website(name, city, country):
    results = ddg_search(f'"{name}" dental {city} {country} official website', max_results=3)
    for r in results:
        url = r.get('href','')
        if url and not any(x in url for x in ['google.','facebook.','instagram.','maps.','tripadvisor.','yelp.','2gis.']):
            return url
    return ''

def find_instagram(name, city, country):
    results = ddg_search(f'"{name}" dental {city} {country} site:instagram.com', max_results=2)
    for r in results:
        url = r.get('href','')
        if 'instagram.com/' in url:
            m = re.search(r'instagram\.com/([^/?#\s]+)', url)
            handle = m.group(1) if m else ''
            if handle and handle not in ('p','explore','accounts','','reels'):
                return 'https://instagram.com/' + handle
    # fallback: broader search
    results2 = ddg_search(f'{name} {city} dental instagram', max_results=3)
    for r in results2:
        url = r.get('href','')
        if 'instagram.com/' in url:
            m = re.search(r'instagram\.com/([^/?#\s]+)', url)
            handle = m.group(1) if m else ''
            if handle and handle not in ('p','explore','accounts','','reels'):
                return 'https://instagram.com/' + handle
    return ''

# ── Main pipeline ─────────────────────────────────────────────────────────────

def enrich_row(row, idx, total):
    name    = row.get('title','').strip()
    city    = ''
    country = ''
    try:
        ca = json.loads(row.get('complete_address','{}'))
        city    = ca.get('city','')
        country_map = {'GE':'Georgia','AM':'Armenia','AZ':'Azerbaijan'}
        country = country_map.get(ca.get('country',''), ca.get('country',''))
    except:
        pass

    website  = row.get('website','').strip()
    emails   = row.get('emails','').strip()
    whatsapp = row.get('whatsapp','').strip()
    instagram = row.get('instagram','').strip()
    facebook  = row.get('facebook','').strip()

    print(f'[{idx}/{total}] {name} | {city} | website={"YES" if website else "no"} | ig={"YES" if instagram else "no"}')

    all_text = ''
    all_soup = None

    # 1) Find website if missing
    if not website and name:
        time.sleep(1.5)
        website = find_website(name, city, country)
        if website:
            print(f'  → Found website: {website}')

    # 2) Scrape website
    if website:
        all_soup, all_text = scrape_url(website)
        extra_text = scrape_contact_pages(website, all_soup)
        all_text += extra_text
        time.sleep(0.5)

    # 3) Extract from website
    if all_text:
        new_emails = extract_emails(all_text)
        merged_emails = list(set(
            [e for e in emails.split(',') if e.strip()] + new_emails
        ))
        emails = ', '.join(merged_emails)

        if not whatsapp:
            wa = extract_whatsapp(all_soup)
            if wa: whatsapp = ', '.join(wa)

        if not instagram:
            ig = extract_instagram(all_soup)
            if ig: instagram = ig[0]

        if not facebook:
            fb = extract_facebook(all_soup)
            if fb: facebook = fb[0]

    # 4) Search Instagram if still missing
    if not instagram and name:
        time.sleep(1.5)
        instagram = find_instagram(name, city, country)
        if instagram:
            print(f'  → Found Instagram: {instagram}')

    row['website']   = website
    row['emails']    = emails
    row['whatsapp']  = whatsapp
    row['instagram'] = instagram
    row['facebook']  = facebook
    return row

def main():
    with open(INPUT, encoding='utf-8') as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames + [
            f for f in ['whatsapp','instagram','facebook']
            if f not in reader.fieldnames
        ]
        rows = list(reader)

    total = len(rows)
    print(f'Enriching {total} clinics...')

    enriched = []
    for i, row in enumerate(rows, 1):
        try:
            enriched.append(enrich_row(row, i, total))
        except Exception as e:
            print(f'  ERROR on row {i}: {e}')
            enriched.append(row)

        # Save progress every 50 rows
        if i % 50 == 0:
            with open(OUTPUT, 'w', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=fieldnames)
                writer.writeheader()
                writer.writerows(enriched)
            print(f'  Progress saved: {i}/{total}')

    with open(OUTPUT, 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched)

    with_email    = sum(1 for r in enriched if r.get('emails','').strip())
    with_whatsapp = sum(1 for r in enriched if r.get('whatsapp','').strip())
    with_instagram= sum(1 for r in enriched if r.get('instagram','').strip())
    with_facebook = sum(1 for r in enriched if r.get('facebook','').strip())
    with_website  = sum(1 for r in enriched if r.get('website','').strip())

    print('\n=== ENRICHMENT COMPLETE ===')
    print(f'Total:       {total}')
    print(f'Website:     {with_website} ({round(with_website/total*100)}%)')
    print(f'Email:       {with_email} ({round(with_email/total*100)}%)')
    print(f'WhatsApp:    {with_whatsapp} ({round(with_whatsapp/total*100)}%)')
    print(f'Instagram:   {with_instagram} ({round(with_instagram/total*100)}%)')
    print(f'Facebook:    {with_facebook} ({round(with_facebook/total*100)}%)')

if __name__ == '__main__':
    main()
