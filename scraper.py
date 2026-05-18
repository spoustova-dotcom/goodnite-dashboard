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

def parse_date(text):
    """Parse Czech/English date string into YYYY-MM."""
    if not text: return None
    text_lower = text.lower()
    for month_name, month_num in CZ_MONTHS.items():
        if month_name in text_lower:
            year_m = re.search(r"(\d{4})", text)
            if year_m:
                return f"{year_m.group(1)}-{month_num:02d}"
    return None

def scrape_reviews_playwright(page, url, cutoff_date):
    """Scrape reviews directly from Booking.com page using Playwright."""
    reviews = []
    reviews_url = url.split("?")[0] + "#tab-reviews"

    try:
        page.goto(reviews_url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        # Scroll to load reviews
        for _ in range(4):
            page.evaluate("window.scrollBy(0, 600)")
            time.sleep(0.8)

        # Wait for review content
        try:
            page.wait_for_selector(
                ".review_list_new_item_block, [data-testid='review-card'], .c-review-block, li.review_item",
                timeout=8000
            )
        except:
            pass
        time.sleep(2)

        # Try to find review blocks using multiple selectors
        block_selectors = [
            ".review_list_new_item_block",
            "[data-testid='review-card']",
            ".c-review-block",
            "li.review_item",
            "div[class*='review_item']",
        ]

        blocks = []
        used_sel = None
        for sel in block_selectors:
            found = page.query_selector_all(sel)
            if found and len(found) > 0:
                blocks = found[:30]
                used_sel = sel
                print(f"    Found {len(found)} blocks with '{sel}'")
                break

        if blocks:
            for block in blocks:
                # Get date
                review_month = None
                for date_sel in [
                    ".c-review-block__date",
                    "[data-testid='review-date']",
                    ".review_item_date",
                    ".bui-review__date",
                    "span[class*='date']",
                    "span[class*='Date']",
                ]:
                    try:
                        date_el = block.query_selector(date_sel)
                        if date_el:
                            review_month = parse_date(date_el.inner_text())
                            if review_month:
                                break
                    except:
                        pass

                # Check cutoff
                if review_month:
                    try:
                        if datetime.strptime(review_month + "-01", "%Y-%m-%d") < cutoff_date:
                            continue
                    except:
                        pass

                # Get positive text
                pos = None
                for sel in [".c-review__body--positive", ".review_pos .review_body", "[data-testid='review-positive-text']", ".review_pos"]:
                    try:
                        el = block.query_selector(sel)
                        if el:
                            t = el.inner_text().strip()
                            if len(t) > 10:
                                pos = t
                                break
                    except:
                        pass

                # Get negative text
                neg = None
                for sel in [".c-review__body--negative", ".review_neg .review_body", "[data-testid='review-negative-text']", ".review_neg"]:
                    try:
                        el = block.query_selector(sel)
                        if el:
                            t = el.inner_text().strip()
                            if len(t) > 10:
                                neg = t
                                break
                    except:
                        pass

                # Fallback: get any review text from block
                if not pos and not neg:
                    for sel in [".c-review__body", ".a53cbfa6de", ".review_item_review_content", ".bui-review__text"]:
                        try:
                            el = block.query_selector(sel)
                            if el:
                                t = el.inner_text().strip()
                                if len(t) > 20:
                                    neg = t
                                    break
                        except:
                            pass

                # Get score
                score = None
                for sel in [".bui-review__score", ".review-score-badge", "[data-testid='review-score']", "span[class*='score']"]:
                    try:
                        el = block.query_selector(sel)
                        if el:
                            score = parse_score(el.inner_text())
                            if score:
                                break
                    except:
                        pass

                if pos or neg:
                    reviews.append({
                        "date": review_month,
                        "score": score,
                        "positive": pos,
                        "negative": neg,
                        "text": neg if neg else pos,
                    })

        # Fallback: grab all text directly if no blocks found
        if not reviews:
            print(f"    No blocks found, trying direct text selectors")
            for sel in [
                ".c-review__body",
                "span.a53cbfa6de",
                ".review_item_review_content",
                ".bui-review__text",
            ]:
                els = page.query_selector_all(sel)
                if els:
                    print(f"    Fallback: {len(els)} items with '{sel}'")
                    for el in els[:20]:
                        t = el.inner_text().strip()
                        if len(t) > 20:
                            reviews.append({"date": None, "score": None, "positive": None, "negative": t, "text": t})
                    if reviews:
                        break

    except Exception as e:
        print(f"    Review scrape error: {e}")

    print(f"    Total: {len(reviews)} reviews")
    return reviews

def scrape_scores(page, url):
    """Scrape numerical scores."""
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

def analyze_with_claude(apt_name, reviews):
    if not reviews:
        return {"issues": [], "summary": None, "issue_counts": {}}
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        return {"issues": [], "summary": None, "issue_counts": {}}

    neg_texts = [r["negative"] for r in reviews if r.get("negative")]
    texts = neg_texts if neg_texts else [r["text"] for r in reviews if r.get("text")]
    if not texts:
        return {"issues": [], "summary": None, "issue_counts": {}}

    sample = "\n---\n".join(texts[:20])
    prompt = f"""Analyzuj negativní části recenzí ubytování "{apt_name}" z Booking.com.

RECENZE:
{sample}

Vrať POUZE JSON (bez markdown):
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
        print(f"    Claude: {len(result.get('issues', []))} issues")
        return result
    except Exception as e:
        print(f"    Claude error: {e}")
        return {"issues": [], "summary": None, "issue_counts": {}}

def merge_archive(archive, apt_name, new_reviews):
    apt = archive.setdefault(apt_name, {})
    for r in new_reviews:
        if not isinstance(r, dict):
            continue
        month = r.get("date") or datetime.utcnow().strftime("%Y-%m")
        month_list = apt.setdefault(month, [])
        # Filter out any non-dict entries from existing list
        month_list = [e for e in month_list if isinstance(e, dict)]
        apt[month] = month_list
        entry = {
            "score": r.get("score"),
            "negative": r.get("negative"),
            "positive": r.get("positive"),
        }
        existing_negs = [e.get("negative") for e in month_list]
        if entry.get("negative") and entry["negative"] not in existing_negs:
            month_list.append(entry)
        elif not entry.get("negative") and entry.get("positive"):
            existing_pos = [e.get("positive") for e in month_list]
            if entry["positive"] not in existing_pos:
                month_list.append(entry)
        if len(month_list) > 30:
            apt[month] = month_list[-30:]
    return archive

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

            reviews = scrape_reviews_playwright(page, apt["url"], cutoff)
            print(f"   {len(reviews)} reviews found")

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
        json.dump({
            "scraped_at": now,
            "apartments": results,
            "history": history,
            "reviews_archive": archive,
        }, f, ensure_ascii=False, indent=2)

    scored = [a for a in results if a["score"]]
    arch_total = sum(len(v) for apt in archive.values() for v in apt.values())
    print(f"\nDone: {len(results)} apts, {len(history)} snapshots, {arch_total} review-months archived")
    if scored:
        print(f"Avg: {sum(a['score'] for a in scored)/len(scored):.2f}")

if __name__ == "__main__":
    main()
