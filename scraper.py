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

GRAPHQL_QUERY = """query ReviewList($input: ReviewListFrontendInput!) {
  reviewListFrontend(input: $input) {
    ... on ReviewListFrontendResult {
      reviewCard {
        reviewedDate
        reviewScore
        textDetails {
          title
          positiveText
          negativeText
          lang
          __typename
        }
        guestDetails {
          countryName
          guestTypeTranslation
          __typename
        }
        __typename
      }
      __typename
    }
  }
}"""

def parse_score(text):
    if not text: return None
    m = re.search(r"(\d+\.?\d*)", text.strip().replace(",", "."))
    if m:
        val = float(m.group(1))
        if val > 10: val = val / 10
        if 1 <= val <= 10: return round(val, 1)
    return None

def get_hotel_id_and_cookies(page, url):
    """Load the hotel page, intercept GraphQL to get hotel_id and cookies."""
    hotel_id = [None]
    ufi = [None]
    cookies_captured = [None]

    def handle_request(req):
        if "graphql" in req.url and hotel_id[0] is None:
            try:
                body = req.post_data
                if body and "ReviewList" in body:
                    data = json.loads(body)
                    inp = data.get("variables", {}).get("input", {})
                    if inp.get("hotelId"):
                        hotel_id[0] = inp["hotelId"]
                        ufi[0] = inp.get("ufi", -542184)
                        print(f"    Intercepted hotelId={hotel_id[0]}, ufi={ufi[0]}")
            except:
                pass

    page.on("request", handle_request)
    try:
        page.goto(url.split("?")[0] + "#tab-reviews", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        page.evaluate("window.scrollTo(0, 600)")
        time.sleep(3)
    except Exception as e:
        print(f"    Page load error: {e}")
    page.remove_listener("request", handle_request)

    # Get cookies for authenticated requests
    cookies = page.context.cookies()
    cookies_captured[0] = {c["name"]: c["value"] for c in cookies}

    return hotel_id[0], ufi[0], cookies_captured[0]

def fetch_reviews_via_graphql(page, hotel_id, ufi, cookies, cutoff_date, max_reviews=100):
    """Fetch reviews by calling Booking GraphQL API directly with intercepted cookies."""
    if not hotel_id:
        return []

    reviews = []
    skip = 0
    limit = 25
    stop = False

    # Build cookie header string
    cookie_str = "; ".join([f"{k}={v}" for k, v in cookies.items()])

    graphql_url = "https://www.booking.com/dml/graphql?label=cs-row-booking-desktop&lang=cs"

    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "cs,en;q=0.9",
        "Origin": "https://www.booking.com",
        "Referer": f"https://www.booking.com/hotel/cz/hotel.cs.html",
        "Cookie": cookie_str,
        "x-booking-context-action-name": "hotel_irene",
        "x-booking-context-aid": "2311236",
    }

    while not stop and len(reviews) < max_reviews:
        payload = {
            "operationName": "ReviewList",
            "variables": {

                "input": {
                    "hotelId": hotel_id,
                    "ufi": ufi if ufi else -542184,
                    "hotelCountryCode": "cz",
                    "sorter": "MOST_RECENT",
                    "filters": {"text": ""},
                    "skip": skip,
                    "limit": limit,
                    "searchFeatures": {"destId": ufi if ufi else -542184, "destType": "CITY"}
                }
            },
            "extensions": {},
            "query": GRAPHQL_QUERY
        }

        try:
            # Use Python requests with captured cookies for reliability
            import requests as req_lib
            session_headers = {
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
                "Accept": "*/*",
                "Accept-Language": "cs,en;q=0.9",
                "Origin": "https://www.booking.com",
                "Referer": f"https://www.booking.com/hotel/cz/hotel.cs.html#tab-reviews",
                "x-booking-context-action-name": "hotel_irene",
                "x-booking-context-aid": "2311236",
                "Cookie": cookie_str,
            }
            resp = req_lib.post(graphql_url, json=payload, headers=session_headers, timeout=15)
            response = resp.json()

            cards = (response.get("data", {})
                           .get("reviewListFrontend", {})
                           .get("reviewCard", []))

            if not cards:
                # Debug: show what we got back
                keys = list(response.get("data", {}).keys()) if response.get("data") else []
                errors = response.get("errors", [])
                print(f"    No cards at skip={skip}. data keys={keys}, errors={errors[:1] if errors else 'none'}")
                break

            for card in cards:
                reviewed_date = card.get("reviewedDate", "")
                score = card.get("reviewScore")
                text_details = card.get("textDetails", {})
                pos = (text_details.get("positiveText") or "").strip()
                neg = (text_details.get("negativeText") or "").strip()

                # Parse date
                review_month = None
                if reviewed_date:
                    try:
                        # reviewedDate is typically "2026-05-03" or timestamp
                        if "-" in str(reviewed_date):
                            parts = str(reviewed_date).split("-")
                            review_month = f"{parts[0]}-{parts[1]}"
                        elif len(str(reviewed_date)) == 10:
                            dt = datetime.fromtimestamp(int(reviewed_date))
                            review_month = dt.strftime("%Y-%m")
                    except:
                        pass

                # Filter by cutoff
                if review_month:
                    try:
                        review_dt = datetime.strptime(review_month + "-01", "%Y-%m-%d")
                        if review_dt < cutoff_date:
                            stop = True
                            break
                    except:
                        pass

                # Only save if has text
                text = ""
                if neg and len(neg) > 10:
                    text = neg
                elif pos and len(pos) > 10:
                    text = pos

                if text:
                    reviews.append({
                        "date": review_month,
                        "score": score,
                        "negative": neg if len(neg) > 10 else None,
                        "positive": pos if len(pos) > 10 else None,
                        "text": text,
                    })

            print(f"    Fetched {len(cards)} cards at skip={skip}, total={len(reviews)}")
            skip += limit
            time.sleep(1)

        except Exception as e:
            print(f"    GraphQL fetch error at skip={skip}: {e}")
            break

    return reviews

def analyze_reviews_with_claude(apt_name, reviews):
    if not reviews:
        return {"issues": [], "summary": None, "issue_counts": {}}
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("    No ANTHROPIC_API_KEY, skipping")
        return {"issues": [], "summary": None, "issue_counts": {}}

    client = anthropic.Anthropic(api_key=api_key)

    # Use negative texts preferentially
    neg_texts = [r["negative"] for r in reviews if r.get("negative")]
    all_texts = neg_texts if neg_texts else [r["text"] for r in reviews]
    reviews_text = "\n---\n".join(all_texts[:20])

    prompt = f"""Analyzuj tyto negativní části recenzí ubytování "{apt_name}" z Booking.com.

RECENZE (negativní části):
{reviews_text}

Vrať POUZE JSON (bez markdown):
{{
  "summary": "1-2 věty shrnující hlavní opakující se problémy",
  "issues": ["konkrétní problém 1", "konkrétní problém 2"],
  "issue_counts": {{"Vůně":0,"Čistota":0,"Hluk":0,"Údržba/vybavení":0,"Komunikace":0,"Parkování":0,"Jiné":0}}
}}
Max 5 issues, stručně česky. Pokud žádné problémy, issues=[]."""

    try:
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = re.sub(r"```json|```", "", msg.content[0].text.strip()).strip()
        result = json.loads(raw)
        print(f"    Claude: {len(result.get('issues', []))} issues")
        return result
    except Exception as e:
        print(f"    Claude error: {e}")
        return {"issues": [], "summary": None, "issue_counts": {}}

def merge_reviews_archive(archive, apt_name, new_reviews):
    """Merge new reviews into monthly archive. Max 30 per month."""
    if apt_name not in archive:
        archive[apt_name] = {}
    apt = archive[apt_name]
    for r in new_reviews:
        month = r.get("date") or datetime.utcnow().strftime("%Y-%m")
        if month not in apt:
            apt[month] = []
        # Store structured review
        entry = {
            "score": r.get("score"),
            "negative": r.get("negative"),
            "positive": r.get("positive"),
        }
        # Avoid duplicates by negative text
        existing_negs = [e.get("negative") for e in apt[month]]
        if entry["negative"] not in existing_negs:
            apt[month].append(entry)
        if len(apt[month]) > 30:
            apt[month] = apt[month][-30:]
    return archive

def scrape_scores(page, url):
    """Scrape numerical scores from hotel page."""
    score = score_cleanliness = review_count = None
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        try:
            page.wait_for_selector("[data-testid='review-score-right-component'], .b5cd09854e", timeout=8000)
        except:
            pass
        time.sleep(2)
        content = page.content()

        for sel in ["[data-testid='review-score-right-component']", "div.b5cd09854e.d10a6220b4", "div.ac4a7896c7", "div.b5cd09854e"]:
            el = page.query_selector(sel)
            if el:
                candidate = parse_score(el.inner_text())
                if candidate:
                    score = candidate
                    break
        if not score:
            for el in page.query_selector_all("[aria-label]"):
                label = el.get_attribute("aria-label") or ""
                if any(w in label.lower() for w in ["hodnocení", "score", "rated"]):
                    candidate = parse_score(label)
                    if candidate:
                        score = candidate
                        break

        clean_m = re.findall(r'[Čč]istota[^0-9]*?(\d[,.]\d)', content)
        if clean_m:
            score_cleanliness = parse_score(clean_m[0])

        count_m = re.findall(r'(\d[\d\s]{0,4})\s*(?:recenz|hodnocen|review)', content, re.IGNORECASE)
        if count_m:
            try:
                review_count = int(count_m[0].replace(" ", "").replace("\xa0", ""))
            except:
                pass

    except Exception as e:
        print(f"    Score scrape error: {e}")

    return score, score_cleanliness, review_count

def main():
    now = datetime.utcnow().isoformat() + "Z"
    print(f"Starting scrape at {now}")

    # Cutoff: reviews from February onwards
    cutoff_date = datetime(2026, 2, 1)
    print(f"Fetching reviews from {cutoff_date.strftime('%Y-%m')} onwards")

    # Load existing data
    existing = {}
    if os.path.exists("data.json"):
        with open("data.json", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except:
                pass

    reviews_archive = existing.get("reviews_archive", {})
    history = existing.get("history", [])
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            locale="cs-CZ",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for apt in APARTMENTS:
            print(f"\nScraping: {apt['name']}")

            # 1. Get scores
            score, score_cleanliness, review_count = scrape_scores(page, apt["url"])
            print(f"  scores: {score}, clean={score_cleanliness}, count={review_count}")

            # 2. Get hotel_id by intercepting GraphQL
            hotel_id, ufi, cookies = get_hotel_id_and_cookies(page, apt["url"])

            # 3. Fetch reviews via GraphQL
            reviews_raw = []
            if hotel_id:
                reviews_raw = fetch_reviews_via_graphql(page, hotel_id, ufi, cookies, cutoff_date)
                print(f"  fetched {len(reviews_raw)} reviews via GraphQL")
            else:
                print(f"  could not get hotel_id, skipping reviews")

            # 4. Analyze with Claude
            analysis = analyze_reviews_with_claude(apt["name"], reviews_raw)

            # 5. Merge into archive
            if reviews_raw:
                reviews_archive = merge_reviews_archive(reviews_archive, apt["name"], reviews_raw)

            results.append({
                "name": apt["name"],
                "url": apt["url"],
                "score": score,
                "score_cleanliness": score_cleanliness,
                "review_count": review_count,
                "error": None,
                "review_issues": analysis.get("issues", []),
                "review_summary": analysis.get("summary"),
                "issue_counts": analysis.get("issue_counts", {}),
                "reviews_analyzed": len(reviews_raw),
            })

            time.sleep(2)

        browser.close()

    # Update history
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

    output = {
        "scraped_at": now,
        "apartments": results,
        "history": history,
        "reviews_archive": reviews_archive,
    }

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    scored = [a for a in results if a["score"] is not None]
    total_reviews = sum(
        len(months)
        for apt in reviews_archive.values()
        for months in apt.values()
    )
    print(f"\nDone. {len(results)} apts, {len(history)} snapshots.")
    print(f"Archive: {total_reviews} review-months stored.")
    if scored:
        print(f"Average: {sum(a['score'] for a in scored)/len(scored):.2f}")

if __name__ == "__main__":
    main()
