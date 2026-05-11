import requests
from bs4 import BeautifulSoup
import json
import time
import re
from datetime import datetime

APARTMENTS = [
    {
        "name": "Enjoy Downtown 12 (SB12)",
        "url": "https://www.booking.com/hotel/cz/enjoy-downtown-boutique-apartments-12-by-goodnite-cz.cs.html"
    },
    {
        "name": "Enjoy Downtown 13 (SB13)",
        "url": "https://www.booking.com/hotel/cz/enjoy-downtown-apartments.cs.html"
    },
    {
        "name": "Enjoy Downtown – Zelný trh",
        "url": "https://www.booking.com/hotel/cz/apartments-zelny-trh-brno.cs.html"
    },
    {
        "name": "Prezidentský mezonet",
        "url": "https://www.booking.com/hotel/cz/president-mezonet-apartment-brno.cs.html"
    },
    {
        "name": "Coco Chanel Boutique",
        "url": "https://www.booking.com/hotel/cz/coco-chanel-boutique-apartment.cs.html"
    },
    {
        "name": "Panorama Apartment",
        "url": "https://www.booking.com/hotel/cz/panorama-apartment-by-goodnite-cz.cs.html"
    },
    {
        "name": "Great Chill (Králova 11)",
        "url": "https://www.booking.com/hotel/cz/boutique-chill-apartments-br-no-11.cs.html"
    },
    {
        "name": "Orange Glow (Šilingrovo 47)",
        "url": "https://www.booking.com/hotel/cz/boutique-city-apartments-br-no-47.cs.html"
    },
    {
        "name": "Old Town Špilberk",
        "url": "https://www.booking.com/hotel/cz/old-town-apartment-spilberk.cs.html"
    },
    {
        "name": "Expo Living 33",
        "url": "https://www.booking.com/hotel/cz/expo-living-33.cs.html"
    },
    {
        "name": "Expo Dream Veletržní",
        "url": "https://www.booking.com/hotel/cz/veletrzni-boutique-apartments.cs.html"
    },
    {
        "name": "Botanica by Goodnite",
        "url": "https://www.booking.com/hotel/cz/botanica-by-goodnite-cz.cs.html"
    },
    {
        "name": "Riverside by Goodnite",
        "url": "https://www.booking.com/hotel/cz/riverside-by-goodnite.cs.html"
    },
    {
        "name": "Penzion u Libušky",
        "url": "https://www.booking.com/hotel/cz/penzion-u-libusky-29-brno-living-cz.cs.html"
    },
    {
        "name": "Sky Apartments Vlhká",
        "url": "https://www.booking.com/hotel/cz/modern-panorama-residence.cs.html"
    },
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "cs,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


def parse_score(text):
    if not text:
        return None
    text = text.strip().replace(",", ".")
    match = re.search(r"(\d+\.?\d*)", text)
    if match:
        val = float(match.group(1))
        if val > 10:
            val = val / 10
        return round(val, 1)
    return None


def scrape_apartment(apt):
    url = apt["url"]
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        resp.raise_for_status()
    except Exception as e:
        print(f"  ERROR fetching {apt['name']}: {e}")
        return {
            "name": apt["name"],
            "url": url,
            "score": None,
            "score_cleanliness": None,
            "review_count": None,
            "error": str(e),
        }

    soup = BeautifulSoup(resp.text, "html.parser")

    # --- Overall score ---
    score = None
    for selector in [
        "[data-testid='review-score-right-component'] div[aria-label]",
        "div.b5cd09854e.d10a6220b4",
        "div.ac4a7896c7",
        "span.b5cd09854e",
        "div.b5cd09854e",
    ]:
        el = soup.select_one(selector)
        if el:
            candidate = parse_score(el.get_text())
            if candidate and 1 <= candidate <= 10:
                score = candidate
                break

    if not score:
        for el in soup.find_all(attrs={"aria-label": True}):
            label = el["aria-label"]
            if any(w in label.lower() for w in ["hodnocení", "score", "rated", "rating"]):
                candidate = parse_score(label)
                if candidate and 1 <= candidate <= 10:
                    score = candidate
                    break

    # --- Cleanliness score ---
    score_cleanliness = None
    for el in soup.find_all(string=re.compile(r"[Čč]istota|[Cc]leanliness")):
        parent = el.find_parent()
        if parent:
            container = parent.find_parent()
            if container:
                numbers = re.findall(r"\b(\d[,.]?\d)\b", container.get_text())
                for n in numbers:
                    val = parse_score(n)
                    if val and 1 <= val <= 10:
                        score_cleanliness = val
                        break
        if score_cleanliness:
            break

    # --- Review count ---
    review_count = None
    for el in soup.find_all(string=re.compile(r"\d+\s*(recenz|hodnocen|review|comment)", re.I)):
        numbers = re.findall(r"(\d[\d\s]*)", el)
        for n in numbers:
            val = int(n.replace(" ", ""))
            if val > 0:
                review_count = val
                break
        if review_count:
            break

    print(f"  {apt['name']}: score={score}, cleanliness={score_cleanliness}, reviews={review_count}")
    return {
        "name": apt["name"],
        "url": url,
        "score": score,
        "score_cleanliness": score_cleanliness,
        "review_count": review_count,
        "error": None,
    }


def main():
    print(f"Starting scrape at {datetime.utcnow().isoformat()}Z")
    results = []
    for apt in APARTMENTS:
        print(f"Scraping: {apt['name']}")
        data = scrape_apartment(apt)
        results.append(data)
        time.sleep(3)

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
        print(f"Average score: {avg:.2f} ({len(scored)}/{len(results)} scraped successfully)")
    errors = [a for a in results if a["error"]]
    if errors:
        print(f"Errors ({len(errors)}): {[a['name'] for a in errors]}")


if __name__ == "__main__":
    main()
