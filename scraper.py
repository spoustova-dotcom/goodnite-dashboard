import json
import re
import time
from datetime import datetime
from playwright.sync_api import sync_playwright

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
    if not text:
        return None
    text = text.strip().replace(",", ".")
    m = re.search(r"(\d+\.?\d*)", text)
    if m:
        val = float(m.group(1))
        if val > 10:
            val = val / 10
        if 1 <= val <= 10:
            return round(val, 1)
    return None

def scrape_all():
    results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="cs-CZ",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for apt in APARTMENTS:
            print(f"Scraping: {apt['name']}")
            score = None
            score_cleanliness = None
            review_count = None
            error = None

            try:
                page.goto(apt["url"], wait_until="domcontentloaded", timeout=30000)
                # wait for review score to appear
                try:
                    page.wait_for_selector("[data-testid='review-score-right-component'], .b5cd09854e, .ac4a7896c7", timeout=8000)
                except:
                    pass
                time.sleep(2)

                content = page.content()

                # Overall score – try JS-rendered selectors
                for sel in [
                    "[data-testid='review-score-right-component']",
                    "div.b5cd09854e.d10a6220b4",
                    "div.ac4a7896c7",
                    "div.b5cd09854e",
                    "span.b5cd09854e",
                ]:
                    el = page.query_selector(sel)
                    if el:
                        txt = el.inner_text()
                        candidate = parse_score(txt)
                        if candidate:
                            score = candidate
                            break

                # Fallback: aria-label on score elements
                if not score:
                    els = page.query_selector_all("[aria-label]")
                    for el in els:
                        label = el.get_attribute("aria-label") or ""
                        if any(w in label.lower() for w in ["hodnocení", "ohodnocen", "score", "rated"]):
                            candidate = parse_score(label)
                            if candidate and 1 <= candidate <= 10:
                                score = candidate
                                break

                # Cleanliness
                import re as re2
                matches = re2.findall(r'[Čč]istota.*?(\d[,.]\d)', content)
                if matches:
                    score_cleanliness = parse_score(matches[0])

                # Review count
                count_matches = re2.findall(r'(\d[\d\s]{0,4})\s*(?:recenz|hodnocen|review)', content, re2.IGNORECASE)
                if count_matches:
                    try:
                        review_count = int(count_matches[0].replace(" ", "").replace("\xa0", ""))
                    except:
                        pass

            except Exception as e:
                error = str(e)
                print(f"  ERROR: {e}")

            print(f"  → score={score}, cleanliness={score_cleanliness}, reviews={review_count}")
            results.append({
                "name": apt["name"],
                "url": apt["url"],
                "score": score,
                "score_cleanliness": score_cleanliness,
                "review_count": review_count,
                "error": error,
            })
            time.sleep(2)

        browser.close()
    return results

def main():
    print(f"Starting scrape at {datetime.utcnow().isoformat()}Z")
    results = scrape_all()

    output = {
        "scraped_at": datetime.utcnow().isoformat() + "Z",
        "apartments": results,
    }
    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\nDone. Saved {len(results)} apartments to data.json")
    scored = [a for a in results if a["score"] is not None]
    if scored:
        avg = sum(a["score"] for a in scored) / len(scored)
        print(f"Average score: {avg:.2f} ({len(scored)}/{len(results)} successful)")
    errors = [a for a in results if a["error"]]
    if errors:
        print(f"Errors: {[a['name'] for a in errors]}")

if __name__ == "__main__":
    main()
