import json, re, time, os
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright
import anthropic

APARTMENTS = [
    {"name": "Enjoy Downtown 12 (SB12)", "url": "https://www.booking.com/hotel/cz/enjoy-downtown-boutique-apartments-12-by-goodnite-cz.cs.html"},
    {"name": "Enjoy Downtown 13 (SB13)", "url": "https://www.booking.com/hotel/cz/enjoy-downtown-apartments.cs.html"},
    {"name": "Enjoy Downtown – Zelný trh", "url": "https://www.booking.com/hotel/cz/apartments-zelny-trh-brno.cs.html"},
    {"name": "Prezidentský mezonet", "url": "https://www.booking.com/hotel/cz/president-mezonet-apartment-brno.cs.html"},
    {"name": "Coco Chanel Boutique", "url": "https://www.booking.com/hotel/cz/coco-chanel-boutique-apartment.cs.html"},
    {"name": "Panorama Apartment", "url": "https://www.booking.com/hotel/cz/panorama-apartment-by-goodnite-cz.cs.html"},
    {"name": "Great Chill (Králova 11)", "url": "https://www.booking.com/hotel/cz/boutique-chill-apartments-br-no-11.cs.html"},
    {"name": "Orange Glow (Šilingrovo 47)", "url": "https://www.booking.com/hotel/cz/boutique-city-apartments-br-no-47.cs.html"},
    {"name": "Old Town Špilberk", "url": "https://www.booking.com/hotel/cz/old-town-apartment-spilberk.cs.html"},
    {"name": "Expo Living 33", "url": "https://www.booking.com/hotel/cz/expo-living-33.cs.html"},
    {"name": "Expo Dream Veletržní", "url": "https://www.booking.com/hotel/cz/veletrzni-boutique-apartments.cs.html"},
    {"name": "Botanica by Goodnite", "url": "https://www.booking.com/hotel/cz/botanica-by-goodnite-cz.cs.html"},
    {"name": "Riverside by Goodnite", "url": "https://www.booking.com/hotel/cz/riverside-by-goodnite.cs.html"},
    {"name": "Penzion u Libušky", "url": "https://www.booking.com/hotel/cz/penzion-u-libusky-29-brno-living-cz.cs.html"},
    {"name": "Sky Apartments Vlhká", "url": "https://www.booking.com/hotel/cz/modern-panorama-residence.cs.html"},
]

CZ_MONTHS = {
    "ledna":1,"února":2,"března":3,"dubna":4,"května":5,"června":6,
    "července":7,"srpna":8,"září":9,"října":10,"listopadu":11,"prosince":12,
    "january":1,"february":2,"march":3,"april":4,"may":5,"june":6,
    "july":7,"august":8,"september":9,"october":10,"november":11,"december":12,
}

def parse_score(text):
    if not text: return None
    m = re.search(r"(\d+\.?\d*)", text.strip().replace(",", "."))
    if m:
        val = float(m.group(1))
        if val > 10: val = val / 10
        if 1 <= val <= 10: return round(val, 1)
    return None

def parse_review_date(text):
    """Try to parse a Czech/English date string into datetime."""
    if not text: return None
    text_lower = text.lower()
    for month_name, month_num in CZ_MONTHS.items():
        if month_name in text_lower:
            year_match = re.search(r"(\d{4})", text)
            if year_match:
                try:
                    return datetime(int(year_match.group(1)), month_num, 1)
                except:
                    pass
    return None

def scrape_reviews(page, url, days=90):
    """Scrape written reviews with dates. Returns list of {text, date_str}."""
    cutoff = datetime.utcnow() - timedelta(days=days)
    reviews = []
    try:
        reviews_url = url.split("?")[0] + "#tab-reviews"
        page.goto(reviews_url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector(".review_list_new_item_block, [data-testid='review-card'], .c-review-block", timeout=8000)
        except:
            pass
        time.sleep(2)

        review_blocks = []
        for block_sel in [".review_list_new_item_block", "[data-testid='review-card']", ".c-review-block"]:
            blocks = page.query_selector_all(block_sel)
            if blocks:
                review_blocks = blocks[:25]
                break

        for block in review_blocks:
            # Get date
            review_date = None
            date_str = None
            for date_sel in [".c-review-block__date", "[data-testid='review-date']", ".review_item_date", ".bui-review__date", "span[class*='date']"]:
                try:
                    date_el = block.query_selector(date_sel)
                    if date_el:
                        date_str = date_el.inner_text().strip()
                        review_date = parse_review_date(date_str)
                        break
                except:
                    pass

            # Get text
            txt = None
            for text_sel in [".c-review__body", ".a53cbfa6de", ".review_item_review_content", ".bui-review__text"]:
                try:
                    text_el = block.query_selector(text_sel)
                    if text_el:
                        t = text_el.inner_text().strip()
                        if t and len(t) > 20:
                            txt = t
                            break
                except:
                    pass

            if txt:
                if review_date is None or review_date >= cutoff:
                    reviews.append({
                        "text": txt,
                        "date": review_date.strftime("%Y-%m") if review_date else None,
                    })

        # Fallback without date
        if not reviews:
            for sel in [
                ".review_list_new_item_block .c-review__body",
                "[data-testid='review-card'] .a53cbfa6de",
                ".c-review-block .c-review__body",
                ".review_item_review_content",
                ".review_neg .review_body",
            ]:
                els = page.query_selector_all(sel)
                if els:
                    for el in els[:20]:
                        t = el.inner_text().strip()
                        if t and len(t) > 20:
                            reviews.append({"text": t, "date": None})
                    if reviews:
                        break

    except Exception as e:
        print(f"    Reviews error: {e}")

    print(f"    Found {len(reviews)} reviews (last {days} days)")
    return reviews

def analyze_reviews_with_claude(apt_name, reviews):
    if not reviews:
        return {"issues": [], "summary": None, "issue_counts": {}}
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"issues": [], "summary": None, "issue_counts": {}}

    client = anthropic.Anthropic(api_key=api_key)
    reviews_text = "\n---\n".join([r["text"] for r in reviews[:15]])

    prompt = f"""Analyzuj tyto recenze ubytování "{apt_name}" z Booking.com a extrahuj hlavní problémy.

RECENZE:
{reviews_text}

Vrať POUZE JSON (bez markdown):
{{
  "summary": "1-2 věty shrnující hlavní problémy",
  "issues": ["konkrétní problém 1", "konkrétní problém 2"],
  "issue_counts": {{"Vůně":0,"Čistota":0,"Hluk":0,"Údržba/vybavení":0,"Komunikace":0,"Parkování":0,"Jiné":0}}
}}
Pravidla: max 5 issues, pouze negativní, issues=[] pokud žádné problémy."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = re.sub(r"```json|```", "", msg.content[0].text.strip()).strip()
        result = json.loads(raw)
        print(f"    Claude: {len(result.get('issues',[]))} issues")
        return result
    except Exception as e:
        print(f"    Claude error: {e}")
        return {"issues": [], "summary": None, "issue_counts": {}}

def merge_reviews_archive(existing_archive, apt_name, new_reviews):
    """
    Merge new reviews into the archive, grouped by YYYY-MM.
    Archive structure: { "apt_name": { "YYYY-MM": ["text1", "text2", ...] } }
    Keeps max 20 reviews per month per apartment to limit file size.
    """
    if apt_name not in existing_archive:
        existing_archive[apt_name] = {}

    apt_archive = existing_archive[apt_name]
    for r in new_reviews:
        month_key = r.get("date") or datetime.utcnow().strftime("%Y-%m")
        if month_key not in apt_archive:
            apt_archive[month_key] = []
        # Avoid duplicates
        if r["text"] not in apt_archive[month_key]:
            apt_archive[month_key].append(r["text"])
        # Cap at 20 per month
        if len(apt_archive[month_key]) > 20:
            apt_archive[month_key] = apt_archive[month_key][-20:]

    return existing_archive

def scrape_apartment(page, apt):
    print(f"Scraping: {apt['name']}")
    score = score_cleanliness = review_count = error = None
    reviews_raw = []

    try:
        page.goto(apt["url"], wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector("[data-testid='review-score-right-component'], .b5cd09854e, .ac4a7896c7", timeout=8000)
        except:
            pass
        time.sleep(2)
        content = page.content()

        for sel in ["[data-testid='review-score-right-component']", "div.b5cd09854e.d10a6220b4", "div.ac4a7896c7", "div.b5cd09854e", "span.b5cd09854e"]:
            el = page.query_selector(sel)
            if el:
                candidate = parse_score(el.inner_text())
                if candidate: score = candidate; break
        if not score:
            for el in page.query_selector_all("[aria-label]"):
                label = el.get_attribute("aria-label") or ""
                if any(w in label.lower() for w in ["hodnocení","ohodnocen","score","rated"]):
                    candidate = parse_score(label)
                    if candidate: score = candidate; break

        clean_matches = re.findall(r'[Čč]istota[^0-9]*?(\d[,.]\d)', content)
        if clean_matches:
            score_cleanliness = parse_score(clean_matches[0])
        if not score_cleanliness:
            for sel in ["[data-testid='review-subscore-cleanliness'] .b5cd09854e", ".cleanliness .b5cd09854e"]:
                el = page.query_selector(sel)
                if el:
                    score_cleanliness = parse_score(el.inner_text())
                    if score_cleanliness: break

        count_m = re.findall(r'(\d[\d\s]{0,4})\s*(?:recenz|hodnocen|review)', content, re.IGNORECASE)
        if count_m:
            try: review_count = int(count_m[0].replace(" ","").replace("\xa0",""))
            except: pass

        reviews_raw = scrape_reviews(page, apt["url"])
        print(f"  → score={score}, clean={score_cleanliness}, reviews={review_count}, texts={len(reviews_raw)}")

    except Exception as e:
        error = str(e)
        print(f"  ERROR: {e}")

    analysis = analyze_reviews_with_claude(apt["name"], reviews_raw)

    return {
        "name": apt["name"],
        "url": apt["url"],
        "score": score,
        "score_cleanliness": score_cleanliness,
        "review_count": review_count,
        "error": error,
        "review_issues": analysis.get("issues", []),
        "review_summary": analysis.get("summary"),
        "issue_counts": analysis.get("issue_counts", {}),
        "reviews_analyzed": len(reviews_raw),
        "reviews_raw": reviews_raw,
    }

def main():
    now = datetime.utcnow().isoformat() + "Z"
    print(f"Starting scrape at {now}")

    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="cs-CZ",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        for apt in APARTMENTS:
            result = scrape_apartment(page, apt)
            results.append(result)
            time.sleep(2)
        browser.close()

    # Load existing data
    existing = {}
    if os.path.exists("data.json"):
        with open("data.json", encoding="utf-8") as f:
            try: existing = json.load(f)
            except: pass

    # Update reviews archive (grouped by month)
    reviews_archive = existing.get("reviews_archive", {})
    for a in results:
        if a.get("reviews_raw"):
            reviews_archive = merge_reviews_archive(reviews_archive, a["name"], a["reviews_raw"])

    # Update history (weekly snapshots)
    history = existing.get("history", [])
    today = now[:10]
    history = [s for s in history if s["scraped_at"][:10] != today]
    history.append({
        "scraped_at": now,
        "apartments": [{
            "name": a["name"], "url": a["url"],
            "score": a["score"], "score_cleanliness": a["score_cleanliness"],
            "review_count": a["review_count"], "error": a["error"],
            "review_issues": a.get("review_issues", []),
            "issue_counts": a.get("issue_counts", {}),
            "review_summary": a.get("review_summary"),
        } for a in results]
    })

    # Strip reviews_raw from output apartments (already in archive)
    clean_results = [{k: v for k, v in a.items() if k != "reviews_raw"} for a in results]

    output = {
        "scraped_at": now,
        "apartments": clean_results,
        "history": history,
        "reviews_archive": reviews_archive,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    scored = [a for a in results if a["score"] is not None]
    archive_total = sum(len(months) for apt in reviews_archive.values() for months in apt.values())
    print(f"\nDone. {len(results)} apts, {len(history)} snapshots, {archive_total} review-months archived.")
    if scored:
        print(f"Average: {sum(a['score'] for a in scored)/len(scored):.2f} ({len(scored)}/{len(results)} OK)")

if __name__ == "__main__":
    main()
