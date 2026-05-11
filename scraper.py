import json, re, time, os
from datetime import datetime
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

def parse_score(text):
    if not text: return None
    m = re.search(r"(\d+\.?\d*)", text.strip().replace(",", "."))
    if m:
        val = float(m.group(1))
        if val > 10: val = val / 10
        if 1 <= val <= 10: return round(val, 1)
    return None

def scrape_reviews(page, url):
    """Scrape written reviews from Booking.com reviews page."""
    reviews = []
    try:
        reviews_url = url.split("?")[0] + "#tab-reviews"
        page.goto(reviews_url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector(".review_list_new_item_block, [data-testid='review-card'], .c-review-block", timeout=8000)
        except:
            pass
        time.sleep(2)

        # Try multiple selectors for review text
        for sel in [
            ".review_list_new_item_block .c-review__body",
            "[data-testid='review-card'] .a53cbfa6de",
            ".c-review-block .c-review__body",
            ".review_item_review_content",
            ".bui-review__text",
        ]:
            els = page.query_selector_all(sel)
            if els:
                for el in els[:20]:  # max 20 reviews
                    txt = el.inner_text().strip()
                    if txt and len(txt) > 20:
                        reviews.append(txt)
                if reviews:
                    break

        # Fallback: look for negative review sections specifically
        if not reviews:
            for sel in [
                ".review_neg .review_body",
                "[data-testid='review-negative-text']",
                ".c-review-block__negative .c-review__body",
            ]:
                els = page.query_selector_all(sel)
                for el in els[:20]:
                    txt = el.inner_text().strip()
                    if txt and len(txt) > 20:
                        reviews.append(txt)
                if reviews:
                    break

    except Exception as e:
        print(f"    Reviews error: {e}")

    return reviews

def analyze_reviews_with_claude(apt_name, reviews):
    """Use Claude to analyze reviews and extract issues."""
    if not reviews:
        return {"issues": [], "summary": None, "issue_counts": {}}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("    No ANTHROPIC_API_KEY found, skipping analysis")
        return {"issues": [], "summary": None, "issue_counts": {}}

    client = anthropic.Anthropic(api_key=api_key)

    reviews_text = "\n---\n".join(reviews[:15])  # max 15 reviews

    prompt = f"""Analyzuj tyto recenze ubytování "{apt_name}" z Booking.com a extrahuj hlavní problémy, které hosté zmiňují.

RECENZE:
{reviews_text}

Vrať POUZE JSON v tomto formátu (bez markdown, bez komentářů):
{{
  "summary": "1-2 věty shrnující hlavní problémy",
  "issues": ["konkrétní problém 1", "konkrétní problém 2", ...],
  "issue_counts": {{
    "Vůně": 0,
    "Čistota": 0,
    "Hluk": 0,
    "Údržba/vybavení": 0,
    "Komunikace": 0,
    "Parkování": 0,
    "Jiné": 0
  }}
}}

Pravidla:
- issues: max 5 nejdůležitějších konkrétních problémů (česky, stručně)
- issue_counts: kolik recenzí zmiňuje danou kategorii
- Pokud nejsou žádné problémy, issues je prázdný seznam a summary je null
- Pouze negativní zpětná vazba, pozitivní ignoruj"""

    try:
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = message.content[0].text.strip()
        raw = re.sub(r"```json|```", "", raw).strip()
        result = json.loads(raw)
        print(f"    Claude analysis: {len(result.get('issues',[]))} issues found")
        return result
    except Exception as e:
        print(f"    Claude analysis error: {e}")
        return {"issues": [], "summary": None, "issue_counts": {}}

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

        # Overall score
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

        # Cleanliness – look for subscores
        clean_matches = re.findall(r'[Čč]istota[^0-9]*?(\d[,.]\d)', content)
        if clean_matches:
            score_cleanliness = parse_score(clean_matches[0])
        
        # Try dedicated cleanliness elements
        if not score_cleanliness:
            for sel in ["[data-testid='review-subscore-cleanliness'] .b5cd09854e", ".cleanliness .b5cd09854e"]:
                el = page.query_selector(sel)
                if el:
                    score_cleanliness = parse_score(el.inner_text())
                    if score_cleanliness: break

        # Review count
        count_m = re.findall(r'(\d[\d\s]{0,4})\s*(?:recenz|hodnocen|review)', content, re.IGNORECASE)
        if count_m:
            try: review_count = int(count_m[0].replace(" ","").replace("\xa0",""))
            except: pass

        # Scrape written reviews
        reviews_raw = scrape_reviews(page, apt["url"])
        print(f"  → score={score}, cleanliness={score_cleanliness}, reviews={review_count}, texts={len(reviews_raw)}")

    except Exception as e:
        error = str(e)
        print(f"  ERROR: {e}")

    # Analyze reviews with Claude
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

    # Load existing data to preserve history
    existing = {}
    if os.path.exists("data.json"):
        with open("data.json", encoding="utf-8") as f:
            try: existing = json.load(f)
            except: pass

    history = existing.get("history", [])
    history.append({
        "scraped_at": now,
        "apartments": [{
            "name": a["name"], "url": a["url"],
            "score": a["score"], "score_cleanliness": a["score_cleanliness"],
            "review_count": a["review_count"], "error": a["error"]
        } for a in results]
    })

    output = {
        "scraped_at": now,
        "apartments": results,
        "history": history
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    scored = [a for a in results if a["score"] is not None]
    print(f"\nDone. {len(results)} apartments, {len(history)} snapshots.")
    if scored:
        print(f"Average: {sum(a['score'] for a in scored)/len(scored):.2f} ({len(scored)}/{len(results)} OK)")

if __name__ == "__main__":
    main()
