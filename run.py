#!/usr/bin/env python3
import requests, random, time, os, sys, threading, queue
from concurrent.futures import ThreadPoolExecutor, as_completed
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# ---------- CONFIG ----------
MAX_RUNTIME = 5.5 * 3600
MIN_DELAY, MAX_DELAY = 0.9, 1.6
FILTER_LEVEL = 7.5
FILTER_LEVEL_6 = 7.0
OUTPUT_FILE = "finds.txt"
REPORT_FILE = "report.md"
TRIED_FILE = "seen.txt"
VIP_CHECK_INTERVAL = 300

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

WORDLIST_URL = "https://raw.githubusercontent.com/charlesreid1/five-letter-words/master/sgb-words.txt"

PROXY_URLS = [
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    "https://www.proxy-list.download/api/v1/get?type=http",
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
    "https://raw.githubusercontent.com/monosans/proxy-list/main/proxies/http.txt",
    "https://proxylist.geonode.com/api/proxy-list?limit=100&page=1&sort_by=lastChecked&sort_type=desc",
    "https://www.freeproxy.world/?type=http"
]

LEET = {'a':'4','e':'3','i':'1','o':'0','s':'5','t':'7','l':'1','b':'8','z':'2','g':'6'}
PHONETIC = {'ph':'f','gh':'g','ch':'k','sh':'x','qu':'kw','ck':'k','wh':'w','th':'d','ng':'n','oo':'u'}

SUFFIXES = ["fy","ly","io","me","us","co","ai","it","tv","up","or","ic","ed","er","el","en","es","ow","ax","ex","on","ar","in","un","im","il","ia","um","ix","ux","ox","op","ee","oo","ek","id","if","ig","ip","ir","is","ob","od","og","om","os","ot","ov","oy","ub","ud","ug","um","un","up","ur","us","ut","ux","uz"]
PREFIXES = ["my","go","we","in","up","on","be","do","no","so","hi","ok","he","it","re","un","im","il","ir","co","de","ex","en","em","el","er","es","ed","ly","fy","io","ai","tv","me","us"]

ATOMS_2 = ["lu","me","fi","zo","vu","ki","ra","po","ne","xi","ja","ze","vo","nu","li","ro","bi","co","de","di","fo","ge","ho","jo","ka","le","ma","ni","pe","qi","re","si","to","vi","wo","xu","za","be","ce","fa","ga","ha","je","la","mo","no","pa","qu","ri","sa","ta","va","we","xe","yo","zu","fi","ai","io","dx","ex","ix","ox","ux","fy","ly","ty","cy","sy","zy","ny","ry","py","dy","gy","hy","jy","ky","my","oy","qy","vy","wy","ay","ey","iy","uy"]
ATOMS_3 = ["dax","zil","vor","nex","lux","pix","vox","jax","kio","zen","kai","lev","nox","rax","tiv","sol","nov","ver","lyn","myr","thal","rion","tron","ix","ox","ex","ion","ia","ius","ium","ana","era","ori","ara","ari","ela","ina","ira","ola","ona","ora","ura","yne","ose","ase","ite","ate","ive","ify","ize","ise","acy","ogy","ism","ist","oid","ous","ful","less","ness","ship","tion","sion","ance","ence","ment","able","ible","al","ic","ical","ive","ous","ful","less","chain","swap","flow","base","node","dapp","meta","lab","hub","pay","bit","coin","dex","fi","dao","web","net","sync","mind","rise","peak","core","data","code","nft","defi","crypto","pay","bit","bot","app","pro","max","top","one","run","hub","zip","map","key","pad","tag","box","mix","pop","tip","cap","lap","tap","nap","gap","hip","lip","rip","sip","tip","zip"]
ATOMS_2 = [a for a in ATOMS_2 if len(a)==2]
ATOMS_3 = [a for a in ATOMS_3 if len(a)==3]
ALL_ATOMS = ATOMS_2 + ATOMS_3

VIP_TARGETS = ["queen","king","magic","dream","sword","power","blade","ghost","storm","crown","angel","money","ethos","pixel","cyber","crypt","vault","brave","flare","glide","flame","shine","ocean","royal","noble","valor","spark","vivid","zesty","lunar","prime","frost","crisp","brisk","plush","swift","quest","haven","charm","grace","bliss","unity","zonal","vapor","zenith","elite","gloom","mirth","glyph","nymph"]

# ----- Proxy Pool with background feeder -----
class ProxyPool:
    def __init__(self, min_size=20, refresh_interval=30):
        self.queue = queue.Queue()
        self.min_size = min_size
        self.refresh_interval = refresh_interval
        self._stop_event = threading.Event()
        self._feeder_thread = None

    def start(self):
        self._feeder_thread = threading.Thread(target=self._feeder, daemon=True)
        self._feeder_thread.start()

    def stop(self):
        self._stop_event.set()

    def get(self):
        try:
            return self.queue.get_nowait()
        except queue.Empty:
            return None

    def put(self, proxy):
        self.queue.put(proxy)

    def size(self):
        return self.queue.qsize()

    def _feeder(self):
        while not self._stop_event.is_set():
            if self.queue.qsize() < self.min_size:
                self._refill()
            time.sleep(self.refresh_interval)

    def _refill(self):
        fresh = all_proxies()
        if fresh:
            good = filter_good(fresh, sample=60)
            for p in good:
                if self.queue.qsize() >= self.min_size * 2:
                    break
                self.queue.put(p)

# ----- Utility functions -----
def load_wordlist():
    try:
        r = requests.get(WORDLIST_URL, timeout=15)
        if r.status_code==200:
            return [w.strip().lower() for w in r.text.splitlines() if len(w.strip())==5]
    except: pass
    return []

def calc_score(name, wset=None):
    s = 5.0
    vv = set("aeiou"); v = sum(1 for c in name if c in vv); cc = 5-v
    if v in (2,3): s+=1.5
    elif v in (1,4): s+=0.5
    else: s-=2.0
    for i in range(3):
        seg = name[i:i+3]
        if all(c in vv for c in seg) or all(c not in vv and not c.isdigit() for c in seg): s-=1.0
    if name[-1] in 'yxoaeiz': s+=0.8
    d = sum(1 for c in name if c.isdigit())
    if d==1: s+= 1.0 if name[0].isdigit() else 1.5
    elif d>1: s-=1.5
    s += sum(1 for c in name if c in "iltjf17") * 0.3
    for u in ['jq','vx','bq','qx','xz','zx','gq','qc','fv','vd','wq','qg','mk','gp','dt','tk','zs','zr']:
        if u in name: s-=1.2
    if name==name[::-1]: s+=1.0
    if name[0] not in 'aeiou' and name[-1] in 'aeiouyx': s+=0.5
    if wset and name in wset: s+=1.5
    return max(0,min(10,s))

def variants_from_word(word):
    res=set(); res.add(word); res.add(word[::-1])
    for i,ch in enumerate(word):
        if ch in LEET: res.add(word[:i]+LEET[ch]+word[i+1:])
    idxs=[i for i,ch in enumerate(word) if ch in LEET]
    if len(idxs)>=2:
        for p in range(len(idxs)):
            for q in range(p+1,len(idxs)):
                w=list(word); w[idxs[p]]=LEET[w[idxs[p]]]; w[idxs[q]]=LEET[w[idxs[q]]]; res.add(''.join(w))
    for old,new in PHONETIC.items():
        if old in word: res.add(word.replace(old,new,1))
    if len(word)>=3:
        stems={word[:3],word[1:4],word[2:5]}
        for stem in stems:
            for sfx in SUFFIXES:
                cand=stem+sfx
                if len(cand)==5: res.add(cand)
            for pfx in PREFIXES:
                cand=pfx+stem
                if len(cand)==5: res.add(cand)
    return list(res)

def gen_atom(tried):
    while True:
        if random.random()<0.5:
            a1,a2=random.choice(ATOMS_2),random.choice(ATOMS_3)
            cand=a1+a2
        else:
            a1,a2=random.choice(ATOMS_3),random.choice(ATOMS_2)
            cand=a1+a2
        if len(cand)!=5: continue
        if random.random()<0.3:
            pos=random.randint(1,4)
            cand=cand[:pos]+random.choice("17")+cand[pos+1:]
        if cand not in tried: return cand

def gen_6char(tried):
    """تولید آیدی ۶ کاراکتری: ۴ حرف + ۲ عدد یا ۵ حرف + ۱ عدد، الگوی برندی"""
    while True:
        # ۴ حرف + ۲ عدد
        if random.random()<0.5:
            letters = ''.join(random.choices("abcdefghijklmnopqrstuvwxyz", k=4))
            digits = ''.join(random.choices("0123456789", k=2))
            cand = letters + digits
        else:
            # ۵ حرف + ۱ عدد
            letters = ''.join(random.choices("abcdefghijklmnopqrstuvwxyz", k=5))
            digit = random.choice("0123456789")
            pos = random.randint(0,5)
            cand = letters[:pos] + digit + letters[pos:]
        if len(cand)==6 and cand not in tried:
            return cand

def fetch_proxies(url):
    try:
        r = requests.get(url, timeout=8)
        if r.status_code == 200:
            return [l.strip() for l in r.text.splitlines() if l.strip()]
    except Exception:
        pass
    return []

def all_proxies():
    p=[]
    for u in PROXY_URLS: p.extend(fetch_proxies(u))
    return list(set(p))

def test_proxy(p):
    try:
        r = requests.get("https://t.me/",
                         proxies={"http": f"http://{p}", "https": f"http://{p}"},
                         timeout=4)
        return r.status_code == 200 and "telegram" in r.text.lower()
    except:
        return False

def filter_good(pool, sample=50):
    if not pool: return []
    sample = min(sample, len(pool))
    test_s = random.sample(pool, sample)
    good = []
    with ThreadPoolExecutor(max_workers=20) as ex:
        futures = {ex.submit(test_proxy, p): p for p in test_s}
        for f in as_completed(futures):
            p = futures[f]
            if f.result():
                good.append(p)
    return good

def check(name, proxy_pool, retries=2):
    session = requests.Session()
    retry_strategy = Retry(total=1, backoff_factor=0.3, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)

    for _ in range(retries):
        p = proxy_pool.get()
        if not p:
            break
        proxy = {"http": f"http://{p}", "https": f"http://{p}"}
        try:
            r = session.get(f"https://t.me/{name}", headers={"User-Agent": "Mozilla/5.0"}, timeout=6, proxies=proxy)
            if "doesn't exist" in r.text.lower():
                proxy_pool.put(p)
                return True
            else:
                proxy_pool.put(p)
                return False
        except:
            continue

    # fallback مستقیم
    try:
        r = session.get(f"https://t.me/{name}", headers={"User-Agent": "Mozilla/5.0"}, timeout=6)
        if "doesn't exist" in r.text.lower():
            return True
        return False
    except:
        return None

def alert(name,score):
    if not TG_BOT_TOKEN or not TG_CHAT_ID: return
    txt=f"💎 *Luxury Diamond!*\n`@{name}`\nScore: {score:.1f}"
    try: requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",json={"chat_id":TG_CHAT_ID,"text":txt,"parse_mode":"Markdown"},timeout=10)
    except: pass

def vip_sniper(vips, lock, proxy_pool, tried, found, wset, stop):
    while not stop.is_set():
        random.shuffle(vips)
        for user in vips:
            if stop.is_set(): break
            if user in tried: continue
            st = check(user, proxy_pool)
            if st is not None:      # فقط در صورت نتیجهٔ قطعی به tried اضافه کن
                with lock: tried.add(user)
            if st is True:
                sc = calc_score(user, wset)
                if sc >= FILTER_LEVEL:
                    with lock: found.append((user, sc))
                    alert(user, sc)
                    print(f"🎯 VIP SNIPE: @{user} (score {sc:.1f})")
            elif st is False:
                print(f"🔒 VIP still taken: @{user}")
            else:
                print(f"⚠️ VIP check failed: @{user}")
            time.sleep(random.uniform(1.0, 2.0))
        time.sleep(VIP_CHECK_INTERVAL)

# ----- Main -----
def main():
    start = time.time()
    scrabble = load_wordlist()
    dream_words = list(set(scrabble + VIP_TARGETS))
    wset = set(scrabble)
    print(f"📚 Seed words: {len(dream_words)}")

    tried = set()
    if os.path.exists(TRIED_FILE):
        with open(TRIED_FILE) as f:
            tried = set(line.strip() for line in f)

    proxy_pool = ProxyPool(min_size=20, refresh_interval=30)
    proxy_pool.start()
    time.sleep(5)
    print(f"✅ Initial proxies: {proxy_pool.size()}")

    lock = threading.Lock()
    found = []
    chk = 0
    stop = threading.Event()
    vip = threading.Thread(target=vip_sniper, args=(VIP_TARGETS, lock, proxy_pool, tried, found, wset, stop), daemon=True)
    vip.start()

    # زمان‌بندی فازها: 80% اتم ۵ حرفی، 20% شش‌حرفی
    phase1_end = start + MAX_RUNTIME * 0.8
    try:
        # فاز ۱: Brand Atoms (۵ حرفی)
        print("\n⚛️ Phase 1: Brand Atoms (80% time)...")
        while time.time() - start < phase1_end:
            cand = gen_atom(tried)
            st = check(cand, proxy_pool)
            chk += 1
            if st is not None:
                with lock: tried.add(cand)
            if st is True:
                sc = calc_score(cand, wset)
                if sc >= FILTER_LEVEL:
                    with lock: found.append((cand, sc))
                    if sc >= 9.0: alert(cand, sc)
                    print(f"⚛️ ATOM: @{cand} (score {sc:.1f})")
            elif st is False:
                print(f"❌ @{cand}")
            else:
                print(f"⚠️ @{cand}")
            if chk % 10 == 0:
                with open(TRIED_FILE, "a") as f:
                    for u in list(tried)[-10:]: f.write(u + "\n")
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        # فاز ۲: Words & Palindromes (۵ حرفی)
        print("\n💎 Phase 2: Words & Palindromes...")
        combined = list(set(dream_words + [w for w in scrabble if w == w[::-1]]))
        random.shuffle(combined)
        for w in combined:
            if time.time() - start > MAX_RUNTIME: break
            for cand in variants_from_word(w):
                if time.time() - start > MAX_RUNTIME: break
                if cand in tried: continue
                st = check(cand, proxy_pool)
                chk += 1
                if st is not None:
                    with lock: tried.add(cand)
                if st is True:
                    sc = calc_score(cand, wset)
                    if sc >= FILTER_LEVEL:
                        with lock: found.append((cand, sc))
                        if sc >= 9.0: alert(cand, sc)
                        print(f"✨ WORD/PAL: @{cand} (score {sc:.1f})")
                elif st is False:
                    print(f"❌ @{cand}")
                else:
                    print(f"⚠️ @{cand}")
                if chk % 10 == 0:
                    with open(TRIED_FILE, "a") as f:
                        for u in list(tried)[-10:]: f.write(u + "\n")
                time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

        # فاز ۳: ۶ رقمی (۲۰٪ زمان باقی‌مانده)
        print("\n🔢 Phase 3: 6-char usernames (remaining time)...")
        while time.time() - start < MAX_RUNTIME:
            cand = gen_6char(tried)
            st = check(cand, proxy_pool)
            chk += 1
            if st is not None:
                with lock: tried.add(cand)
            if st is True:
                sc = calc_score(cand, wset)  # استفاده از همان تابع (با طول ۶ ممکن است کمی انحراف داشته باشد، ولی همچنان فیلتر می‌کند)
                if sc >= FILTER_LEVEL_6:
                    with lock: found.append((cand, sc))
                    if sc >= 8.5: alert(cand, sc)
                    print(f"🔢 6CHAR: @{cand} (score {sc:.1f})")
            elif st is False:
                print(f"❌ @{cand}")
            else:
                print(f"⚠️ @{cand}")
            if chk % 10 == 0:
                with open(TRIED_FILE, "a") as f:
                    for u in list(tried)[-10:]: f.write(u + "\n")
            time.sleep(random.uniform(MIN_DELAY, MAX_DELAY))

    finally:
        stop.set()
        vip.join(timeout=5)
        proxy_pool.stop()

    with open(TRIED_FILE, "w") as f:
        for u in tried: f.write(u + "\n")
    found.sort(key=lambda x: x[1], reverse=True)
    with open(OUTPUT_FILE, "w") as f:
        for n,s in found: f.write(f"{n} (score {s:.1f})\n")
    with open(REPORT_FILE, "w") as f:
        f.write("# Report\n")
        f.write(f"**Found:** {len(found)}\n\n")
        f.write("| Rank | Username | Beauty | Est. Value |\n")
        f.write("|------|----------|--------|------------|\n")
        for i,(n,s) in enumerate(found,1):
            f.write(f"| {i} | @{n} | {s:.1f} | ${int(s*15+random.randint(0,10))} |\n")
    print(f"\n🏁 Done. Checked: {chk}, Diamonds: {len(found)}")

if __name__=="__main__":
    main()
