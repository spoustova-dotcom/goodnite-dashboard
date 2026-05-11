import json, re, time, os, requests
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

# Exact query copied from browser network tab
GRAPHQL_QUERY = (
    "query ReviewList($input: ReviewListFrontendInput!, "
    "$shouldShowReviewListPhotoAltText: Boolean = false) {"
    "reviewListFrontend(input: $input) {"
    "... on ReviewListFrontendResult {"
    "reviewCard {"
    "reviewedDate reviewScore "
    "textDetails { title positiveText negativeText lang __typename } "
    "guestDetails { countryName guestTypeTranslation __typename } "
    "__typename"
    "} __typename } } }"
)

GRAPHQL_URL = "https://www.booking.com/dml/graphql"

def parse_score(text):
    if not text: return None
    m = re.search(r"(\d+\.?\d*)", text.strip().replace(",", "."))
    if m:
        val = float(m.group(1))
        if val > 10: val = val / 10
        if 1 <= val <= 10: return round(val, 1)
    return None

def get_hotel_info(page, url):
    """Intercept GraphQL request to get hotelId, ufi, and session cookies."""
    captured = {"hotel_id": None, "ufi": None, "full_payload": None}

    def on_request(req):
        if "graphql" in req.url and captured["hotel_id"] is None:
            try:
                body = req.post_data
                if body and "ReviewList" in body:
                    data = json.loads(body)
                    inp = data.get("variables", {}).get("input", {})
                    if inp.get("hotelId"):
                        captured["hotel_id"] = inp["hotelId"]
                        captured["ufi"] = inp.get("ufi", -542184)
                        # Save the full original input for reference
                        captured["full_payload"] = inp
                        print(f"    hotelId={inp['hotelId']}, ufi={inp.get('ufi')}")
            except Exception as e:
                pass

    page.on("request", on_request)
    try:
        page.goto(url.split("?")[0] + "#tab-reviews", wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)
        page.evaluate("window.scrollTo(0, 800)")
        time.sleep(3)
    except Exception as e:
        print(f"    Page load error: {e}")
    page.remove_listener("request", on_request)

    cookies = {c["name"]: c["value"] for c in page.context.cookies()}
    return captured["hotel_id"], captured["ufi"], captured["full_payload"], cookies

def fetch_reviews(hotel_id, ufi, original_input, cookies, cutoff_date, max_reviews=100):
    """Fetch reviews via Booking GraphQL API using intercepted session."""
    if not hotel_id:
        return []

    cookie_str = "; ".join(f"{k}={v}" for k, v in cookies.items())
    headers = {
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "cs,en;q=0.9",
        "Origin": "https://www.booking.com",
        "Referer": "https://www.booking.com/",
        "x-booking-context-action-name": "hotel_irene",
        "x-booking-context-aid": "2311236",
        "Cookie": cookie_str,
    }

    reviews = []
    skip = 0
    limit = 25

    # Build input from original intercepted payload to ensure correct types
    base_input = {
        "hotelId": hotel_id,
        "ufi": ufi if ufi else -542184,
        "hotelCountryCode": original_input.get("hotelCountryCode", "cz") if original_input else "cz",
        "sorter": "MOST_RECENT",
        "filters": {"text": ""},
        "hotelScore": original_input.get("hotelScore") if original_input else None,
        "upSortReviewUrl": original_input.get("upSortReviewUrl", "") if original_input else "",
        "searchFeatures": original_input.get("searchFeatures", {
            "destId": ufi if ufi else -542184,
            "destType": "CITY"
        }) if original_input else {
            "destId": ufi if ufi else -542184,
            "destType": "CITY"
        },
    }

    while len(reviews) < max_reviews:
        current_input = {**base_input, "skip": skip, "limit": limit}
        # Remove None values to avoid type errors
        current_input = {k: v for k, v in current_input.items() if v is not None}

        payload = {
            "operationName": "ReviewList",
            "variables": {
                "shouldShowReviewListPhotoAltText": True,
                "input": current_input,
            },
            "extensions": {},
            "query": GRAPHQL_QUERY,
        }

        try:
            resp = requests.post(
                GRAPHQL_URL,
                json=payload,
                headers=headers,
                timeout=20,
                params={"label": "cs-row-booking-desktop", "lang": "cs"}
            )
            resp.raise_for_status()
            data = resp.json()

            errors = data.get("errors", [])
            if errors:
                print(f"    GraphQL errors: {[e.get('message','?') for e in errors[:2]]}")
                break

            cards = (data.get("data") or {}).get("reviewListFrontend", {}).get("reviewCard", [])
            if not cards:
                print(f"    No more cards at skip={skip}")
                break

            stop = False
            for card in cards:
                reviewed_date = str(card.get("reviewedDate") or "")
                score = card.get("reviewScore")
                td = card.get("textDetails") or {}
                pos = (td.get("positiveText") or "").strip()
                neg = (td.get("negativeText") or "").strip()

                # Parse YYYY-MM from date
                review_month = None
                try:
                    if re.match(r"\d{4}-\d{2}-\d{2}", reviewed_date):
                        review_month = reviewed_date[:7]
                    elif reviewed_date.isdigit():
                        review_month = datetime.fromtimestamp(int(reviewed_date)).strftime("%Y-%m")
                except:
                    pass

                # Stop if older than cutoff
                if review_month:
                    try:
                        if datetime.strptime(review_month + "-01", "%Y-%m-%d") < cutoff_date:
                            stop = True
                            break
                    except:
                        pass

                if pos or neg:
                    reviews.append({
                        "date": review_month,
                        "score": score,
                        "positive": pos if len(pos) > 10 else None,
                        "negative": neg if len(neg) > 10 else None,
                        "text": neg if len(neg) > 10 else pos,
                    })

            print(f"    skip={skip}: got {len(cards)} cards, total={len(reviews)}")
            if stop:
                print(f"    Reached cutoff date, stopping")
                break

            skip += limit
            time.sleep(1)

        except Exception as e:
            print(f"    Fetch error at skip={skip}: {e}")
            break

    return reviews

def analyze_with_claude(apt_name, reviews):
    """Analyze negative review texts with Claude."""
    if not reviews:
        return {"issues": [], "summary": None, "issue_counts": {}}

    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        print("    No ANTHROPIC_API_KEY")
        return {"issues": [], "summary": None, "issue_counts": {}}

    neg_texts = [r["negative"] for r in reviews if r.get("negative")]
    texts = neg_texts if neg_texts else [r["text"] for r in reviews if r.get("text")]
    if not texts:
        return {"issues": [], "summary": None, "issue_counts": {}}

    sample = "\n---\n".join(texts[:20])
    prompt = f"""Analyzuj negativní části recenzí ubytování "{apt_name}" z Booking.com.

RECENZE:
{sample}

Vrať POUZE JSON (bez markdown, bez komentářů):
{{"summary":"1-2 věty o hlavních problémech","issues":["problém 1","problém 2"],"issue_counts":{{"Vůně":0,"Čistota":0,"Hluk":0,"Údržba/vybavení":0,"Komunikace":0,"Parkování":0,"Jiné":0}}}}

Max 5 issues, česky, stručně. Pokud žádné problémy → issues=[], summary=null."""

    try:
        client = anthropic.Anthropic(api_key=api_key)
        msg = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = re.sub(r"```json|```", "", msg.content[0].text).strip()
        result = json.loads(raw)
        print(f"    Claude: {len(result.get('issues', []))} issues found")
        return result
    except Exception as e:
        print(f"    Claude error: {e}")
        return {"issues": [], "summary": None, "issue_counts": {}}

def merge_archive(archive, apt_name, new_reviews):
    """Add reviews to monthly archive, max 30 per month, no duplicates."""
    apt = archive.setdefault(apt_name, {})
    for r in new_reviews:
        month = r.get("date") or datetime.utcnow().strftime("%Y-%m")
        month_list = apt.setdefault(month, [])
        entry = {"score": r.get("score"), "negative": r.get("negative"), "positive": r.get("positive")}
        existing = [e.get("negative") for e in month_list]
        if entry["negative"] and entry["negative"] not in existing:
            month_list.append(entry)
        elif not entry["negative"] and entry.get("positive"):
            pos_existing = [e.get("positive") for e in month_list]
            if entry["positive"] not in pos_existing:
                month_list.append(entry)
        if len(month_list) > 30:
            apt[month] = month_list[-30:]
    return archive

def scrape_scores(page, url):
    """Get numerical scores from hotel page."""
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
                c = parse_score(el.inner_text())
                if c:
                    score = c
                    break
        if not score:
            for el in page.query_selector_all("[aria-label]"):
                lbl = el.get_attribute("aria-label") or ""
                if any(w in lbl.lower() for w in ["hodnocení", "score", "rated"]):
                    c = parse_score(lbl)
                    if c:
                        score = c
                        break

        m = re.search(r'[Čč]istota[^0-9]*?(\d[,.]\d)', content)
        if m:
            score_cleanliness = parse_score(m.group(1))

        m2 = re.search(r'(\d[\d\s]{0,4})\s*(?:recenz|hodnocen|review)', content, re.IGNORECASE)
        if m2:
            try:
                review_count = int(m2.group(1).replace(" ", "").replace("\xa0", ""))
            except:
                pass
    except Exception as e:
        print(f"    Score error: {e}")
    return score, score_cleanliness, review_count

def main():
    now = datetime.utcnow().isoformat() + "Z"
    cutoff = datetime(2026, 2, 1)
    print(f"Scrape at {now}, reviews from {cutoff.strftime('%Y-%m')}")

    existing = {}
    if os.path.exists("data.json"):
        with open("data.json", encoding="utf-8") as f:
            try:
                existing = json.load(f)
            except:
                pass

    archive = existing.get("reviews_archive", {})
    history = existing.get("history", [])
    results = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx = browser.new_context(
            locale="cs-CZ",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
        page = ctx.new_page()

        for apt in APARTMENTS:
            print(f"\n── {apt['name']}")

            score, clean, count = scrape_scores(page, apt["url"])
            print(f"   score={score}, clean={clean}, count={count}")

            hotel_id, ufi, orig_input, cookies = get_hotel_info(page, apt["url"])

            reviews = []
            if hotel_id:
                reviews = fetch_reviews(hotel_id, ufi, orig_input, cookies, cutoff)
                print(f"   {len(reviews)} reviews fetched")
            else:
                print("   no hotel_id found")

            analysis = analyze_with_claude(apt["name"], reviews)

            if reviews:
                archive = merge_archive(archive, apt["name"], reviews)

            results.append({
                "name": apt["name"],
                "url": apt["url"],
                "score": score,
                "score_cleanliness": clean,
                "review_count": count,
                "error": None,
                "review_issues": analysis["issues"],
                "review_summary": analysis["summary"],
                "issue_counts": analysis["issue_counts"],
                "reviews_analyzed": len(reviews),
            })
            time.sleep(2)

        browser.close()

    today = now[:10]
    history = [s for s in history if s["scraped_at"][:10] != today]
    history.append({
        "scraped_at": now,
        "apartments": [{
            "name": a["name"], "url": a["url"],
            "score": a["score"], "score_cleanliness": a["score_cleanliness"],
            "review_count": a["review_count"], "error": a["error"],
            "review_issues": a["review_issues"],
            "issue_counts": a["issue_counts"],
            "review_summary": a["review_summary"],
        } for a in results]
    })

    with open("data.json", "w", encoding="utf-8") as f:
        json.dump({"scraped_at": now, "apartments": results, "history": history, "reviews_archive": archive},
                  f, ensure_ascii=False, indent=2)

    scored = [a for a in results if a["score"]]
    arch_total = sum(len(v) for apt in archive.values() for v in apt.values())
    print(f"\nDone: {len(results)} apts, {len(history)} snapshots, {arch_total} review-months")
    if scored:
        print(f"Avg score: {sum(a['score'] for a in scored)/len(scored):.2f}")

if __name__ == "__main__":
    main()
