#!/usr/bin/env python3
"""
Telegram Username Scanner – HTTP with rotating proxies.
Bypasses GitHub IP ban. 30‑minute runs.
"""

import asyncio
import aiohttp
import random
import time
import os
import sys
import threading
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

# ======================= CONFIG =======================
MAX_RUNTIME = 0.5 * 3600      # 30 minutes
BATCH_SIZE = 30               # concurrent checks
BATCH_DELAY = 2.0             # seconds between batches
MAX_CONSECUTIVE_ERRORS = 5
FILTER_LEVEL = 0.0
FILTER_LEVEL_6 = 7.0
OUTPUT_FILE = "finds.txt"
REPORT_FILE = "report.md"
TRIED_FILE = "seen.txt"
VIP_CHECK_INTERVAL = 300

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

WORDLIST_URL = "https://raw.githubusercontent.com/charlesreid1/five-letter-words/master/sgb-words.txt"

# ======================= STATIC DATA =======================
LEET = {'a':'4','e':'3','i':'1','o':'0','s':'5','t':'7','l':'1','b':'8','z':'2','g':'6'}
PHONETIC = {'ph':'f','gh':'g','ch':'k','sh':'x','qu':'kw','ck':'k','wh':'w','th':'d','ng':'n','oo':'u'}

SUFFIXES = ["fy","ly","io","me","us","co","ai","it","tv","up","or","ic","ed","er","el","en","es","ow","ax","ex","on","ar","in","un","im","il","ia","um","ix","ux","ox","op","ee","oo","ek","id","if","ig","ip","ir","is","ob","od","og","om","os","ot","ov","oy","ub","ud","ug","um","un","up","ur","us","ut","ux","uz"]
PREFIXES = ["my","go","we","in","up","on","be","do","no","so","hi","ok","he","it","re","un","im","il","ir","co","de","ex","en","em","el","er","es","ed","ly","fy","io","ai","tv","me","us"]

CONSONANTS = "bcdfghjklmnpqrstvwxyz"
VOWELS = "aeiou"

VIP_TARGETS = [
    "queen","king","magic","dream","sword","power","blade","ghost","storm","crown",
    "angel","money","ethos","pixel","cyber","crypt","vault","brave","flare","glide",
    "flame","shine","ocean","royal","noble","valor","spark","vivid","zesty","lunar",
    "prime","frost","crisp","brisk","plush","swift","quest","haven","charm","grace",
    "bliss","unity","zonal","vapor","zenith","elite","gloom","mirth","glyph","nymph"
]

# ======================= UTILITIES =======================
def load_wordlist():
    try:
        r = requests.get(WORDLIST_URL, timeout=15)
        if r.status_code == 200:
            return [w.strip().lower() for w in r.text.splitlines() if len(w.strip()) == 5]
    except:
        pass
    return []

def calc_score(name, wset=None):
    length = len(name)
    s = 5.0
    vv = set("aeiou")
    v = sum(1 for c in name if c in vv)
    if length > 0:
        ratio = v / length
        if 0.4 <= ratio <= 0.6: s += 1.5
        elif 0.2 <= ratio < 0.4 or 0.6 < ratio <= 0.8: s += 0.5
        else: s -= 2.0
    for i in range(length - 2):
        seg = name[i:i+3]
        if all(c in vv for c in seg) or all(c not in vv and not c.isdigit() for c in seg):
            s -= 1.0
    if name[-1] in 'yxoaeiz': s += 0.8
    d = sum(1 for c in name if c.isdigit())
    if d == 1: s += 1.0 if name[0].isdigit() else 1.5
    elif d > 1: s -= 1.5 * (d - 1)
    s += sum(1 for c in name if c in "iltjf17") * 0.3
    ugly = ['jq','vx','bq','qx','xz','zx','gq','qc','fv','vd','wq','qg','mk','gp','dt','tk','zs','zr']
    for u in ugly:
        if u in name: s -= 1.2
    if name == name[::-1]: s += 1.0
    if name[0] not in 'aeiou' and name[-1] in 'aeiouyx': s += 0.5
    if wset and name in wset: s += 1.5
    return max(0, min(10, s))

def variants_from_word(word):
    res = set()
    res.add(word); res.add(word[::-1])
    for i,ch in enumerate(word):
        if ch in LEET:
            res.add(word[:i] + LEET[ch] + word[i+1:])
    idxs = [i for i,ch in enumerate(word) if ch in LEET]
    if len(idxs) >= 2:
        for p in range(len(idxs)):
            for q in range(p+1, len(idxs)):
                w = list(word)
                w[idxs[p]] = LEET[w[idxs[p]]]
                w[idxs[q]] = LEET[w[idxs[q]]]
                res.add(''.join(w))
    for old,new in PHONETIC.items():
        if old in word: res.add(word.replace(old, new, 1))
    if len(word) >= 3:
        stems = {word[:3], word[1:4], word[2:5]}
        for stem in stems:
            for sfx in SUFFIXES:
                cand = stem + sfx
                if len(cand) == 5: res.add(cand)
            for pfx in PREFIXES:
                cand = pfx + stem
                if len(cand) == 5: res.add(cand)
    return list(res)

def gen_pronounceable(tried):
    for _ in range(1000):
        if random.random() < 0.5:
            pattern = "CVCVC"
        else:
            pattern = "VCVCV"
        name = []
        for p in pattern:
            if p == 'C':
                name.append(random.choice(CONSONANTS))
            else:
                name.append(random.choice(VOWELS))
        cand = ''.join(name)
        if random.random() < 0.3:
            pos = random.randint(1, 4)
            cand = cand[:pos] + random.choice("123456789") + cand[pos+1:]
        if cand not in tried and len(cand) == 5:
            return cand
    return None

# ======================= PROXY HANDLING =======================
PROXY_URLS = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://www.proxy-list.download/api/v1/get?type=http",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
]

def fetch_proxies():
    proxies = []
    for url in PROXY_URLS:
        try:
            r = requests.get(url, timeout=8)
            if r.status_code == 200:
                proxies.extend([line.strip() for line in r.text.splitlines() if line.strip()])
        except:
            pass
    return list(set(proxies))

def test_proxy(p):
    try:
        r = requests.get("https://t.me/telegram", proxies={"http": f"http://{p}", "https": f"http://{p}"}, timeout=4)
        return r.status_code == 200 and "telegram" in r.text.lower()
    except:
        return False

def get_working_proxies(min_count=20):
    proxies = fetch_proxies()
    if not proxies:
        return []
    good = []
    with ThreadPoolExecutor(max_workers=30) as ex:
        futures = {ex.submit(test_proxy, p): p for p in proxies[:100]}
        for f in as_completed(futures):
            p = futures[f]
            if f.result():
                good.append(p)
                if len(good) >= min_count:
                    break
    return good

# ======================= HTTP CHECK WITH PROXY =======================
async def check_one(session, username, proxy_addr):
    url = f"https://t.me/{username}"
    headers = {"User-Agent": "Mozilla/5.0"}
    proxy = f"http://{proxy_addr}"
    try:
        async with session.get(url, headers=headers, proxy=proxy, timeout=8) as resp:
            text = await resp.text()
            if "doesn't exist" in text.lower():
                return True
            return False
    except:
        return None

async def check_bulk(usernames, proxy_list):
    """Check a batch using random proxies from the given list."""
    async with aiohttp.ClientSession() as session:
        tasks = []
        for u in usernames:
            if not proxy_list:
                # no proxies left? skip
                tasks.append(asyncio.sleep(0, result=None))
                continue
            p = random.choice(proxy_list)
            tasks.append(check_one(session, u, p))
        results = await asyncio.gather(*tasks)
    return list(zip(usernames, results))

# ======================= SANITY CHECK (direct IP) =======================
async def sanity_check():
    """Check if direct IP is banned. We assume it is."""
    # We just verify that we have proxies
    proxies = get_working_proxies(min_count=10)
    if len(proxies) < 5:
        print("❌ Not enough working proxies. Aborting.")
        return False
    print(f"✅ {len(proxies)} proxies ready.")
    return True

# ======================= MAIN =======================
async def main_async():
    start = time.time()

    if not await sanity_check():
        sys.exit(1)

    scrabble = load_wordlist()
    dream_words = list(set(scrabble + VIP_TARGETS))
    wset = set(scrabble)
    print(f"📚 Seed words: {len(dream_words)}")

    tried = set()
    if os.path.exists(TRIED_FILE):
        with open(TRIED_FILE) as f:
            tried = set(line.strip() for line in f)

    lock = threading.Lock()
    found = []
    chk = 0
    stop_event = threading.Event()
    # VIP sniper disabled for brevity (can be added later)

    # Initial proxy pool
    proxy_pool = get_working_proxies(min_count=20)

    phase1_end = start + MAX_RUNTIME * 0.2
    consecutive_errors = 0
    stop_early = False

    try:
        # Phase 1: Words & Palindromes
        print("\n💎 Phase 1: Words & Palindromes (proxied)...")
        combined = list(set(dream_words + [w for w in scrabble if w == w[::-1]]))
        random.shuffle(combined)
        batch = []
        for w in combined:
            if time.time() - start > phase1_end or stop_early:
                break
            for cand in variants_from_word(w):
                if time.time() - start > phase1_end or stop_early:
                    break
                if cand in tried: continue
                batch.append(cand)
                if len(batch) >= BATCH_SIZE:
                    results = await check_bulk(batch, proxy_pool)
                    for cand, status in results:
                        chk += 1
                        if status is not None:
                            with lock: tried.add(cand)
                            consecutive_errors = 0
                        else:
                            consecutive_errors += 1
                        if status is True:
                            sc = calc_score(cand, wset)
                            with lock: found.append((cand, sc))
                            print(f"✨ WORD/PAL: @{cand} (score {sc:.1f})")
                        elif status is False:
                            print(f"❌ @{cand}")
                        else:
                            print(f"⚠️ @{cand}")
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            # refresh proxy pool
                            new_pool = get_working_proxies(min_count=20)
                            if new_pool:
                                proxy_pool = new_pool
                                consecutive_errors = 0
                            else:
                                print("❌ No proxies left, stopping.")
                                stop_early = True
                                break
                        if chk % 100 == 0:
                            with open(TRIED_FILE, "a") as f:
                                for u in list(tried)[-100:]:
                                    f.write(u + "\n")
                    batch.clear()
                    await asyncio.sleep(BATCH_DELAY)
        # Phase 2: Pronounceable
        if not stop_early:
            print("\n🗣️ Phase 2: Pronounceable 5‑char names (proxied)...")
            while time.time() - start < MAX_RUNTIME and not stop_early:
                cand = gen_pronounceable(tried)
                if cand is None: break
                batch.append(cand)
                if len(batch) >= BATCH_SIZE:
                    results = await check_bulk(batch, proxy_pool)
                    for cand, status in results:
                        chk += 1
                        if status is not None:
                            with lock: tried.add(cand)
                            consecutive_errors = 0
                        else:
                            consecutive_errors += 1
                        if status is True:
                            sc = calc_score(cand, wset)
                            with lock: found.append((cand, sc))
                            if sc >= 9.0:
                                try:
                                    requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                                                  json={"chat_id": TG_CHAT_ID, "text": f"💎 PRON: @{cand} ({sc:.1f})",
                                                        "parse_mode": "Markdown"}, timeout=10)
                                except: pass
                            print(f"🗣️ PRON: @{cand} (score {sc:.1f})")
                        elif status is False:
                            print(f"❌ @{cand}")
                        else:
                            print(f"⚠️ @{cand}")
                        if consecutive_errors >= MAX_CONSECUTIVE_ERRORS:
                            new_pool = get_working_proxies(min_count=20)
                            if new_pool:
                                proxy_pool = new_pool
                                consecutive_errors = 0
                            else:
                                stop_early = True
                                break
                        if chk % 100 == 0:
                            with open(TRIED_FILE, "a") as f:
                                for u in list(tried)[-100:]:
                                    f.write(u + "\n")
                    batch.clear()
                    await asyncio.sleep(BATCH_DELAY)

    finally:
        stop_event.set()

    with open(TRIED_FILE, "w") as f:
        for u in tried:
            f.write(u + "\n")
    found.sort(key=lambda x: x[1], reverse=True)
    with open(OUTPUT_FILE, "w") as f:
        for n, s in found:
            f.write(f"{n} (score {s:.1f})\n")
    with open(REPORT_FILE, "w") as f:
        f.write("# Report\n")
        f.write(f"**Found:** {len(found)}\n\n")
        f.write("| Rank | Username | Beauty | Est. Value |\n")
        f.write("|------|----------|--------|------------|\n")
        for i, (n, s) in enumerate(found, 1):
            f.write(f"| {i} | @{n} | {s:.1f} | ${int(s*15+random.randint(0,10))} |\n")
    print(f"\n🏁 Done. Checked: {chk}, Diamonds: {len(found)}")

def main():
    asyncio.run(main_async())

if __name__ == "__main__":
    main()
