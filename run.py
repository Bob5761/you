#!/usr/bin/env python3
"""
Telegram Username Scanner – DNS-based (No Proxy, Ultra-Fast)
Uses NXDOMAIN check on username.t.me for instant availability detection.
"""

import dns.resolver
import requests
import random
import time
import os
import sys
import threading

# ---------- CONFIG ----------
MAX_RUNTIME = 5.5 * 3600
MIN_DELAY = 0.05            # 50ms between DNS queries (20 checks/sec)
FILTER_LEVEL = 7.5
FILTER_LEVEL_6 = 7.0
OUTPUT_FILE = "finds.txt"
REPORT_FILE = "report.md"
TRIED_FILE = "seen.txt"
VIP_CHECK_INTERVAL = 300

TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN", "")
TG_CHAT_ID = os.environ.get("TG_CHAT_ID", "")

WORDLIST_URL = "https://raw.githubusercontent.com/charlesreid1/five-letter-words/master/sgb-words.txt"

# DNS resolver configuration – using multiple public resolvers
DNS_RESOLVERS = ['8.8.8.8', '1.1.1.1', '9.9.9.9', '208.67.222.222']
resolver = dns.resolver.Resolver(configure=False)
resolver.nameservers = DNS_RESOLVERS
resolver.timeout = 2
resolver.lifetime = 4

# ---------- Leet & Phonetic maps ----------
LEET = {'a':'4','e':'3','i':'1','o':'0','s':'5','t':'7','l':'1','b':'8','z':'2','g':'6'}
PHONETIC = {'ph':'f','gh':'g','ch':'k','sh':'x','qu':'kw','ck':'k','wh':'w','th':'d','ng':'n','oo':'u'}

# ---------- Affixes ----------
SUFFIXES = ["fy","ly","io","me","us","co","ai","it","tv","up","or","ic","ed","er","el","en","es","ow","ax","ex","on","ar","in","un","im","il","ia","um","ix","ux","ox","op","ee","oo","ek","id","if","ig","ip","ir","is","ob","od","og","om","os","ot","ov","oy","ub","ud","ug","um","un","up","ur","us","ut","ux","uz"]
PREFIXES = ["my","go","we","in","up","on","be","do","no","so","hi","ok","he","it","re","un","im","il","ir","co","de","ex","en","em","el","er","es","ed","ly","fy","io","ai","tv","me","us"]

# ---------- Brand Atoms (2 & 3 letters) ----------
ATOMS_2 = [
    "lu","me","fi","zo","vu","ki","ra","po","ne","xi","ja","ze","vo","nu","li","ro","bi","co","de","di",
    "fo","ge","ho","jo","ka","le","ma","ni","pe","qi","re","si","to","vi","wo","xu","za","be","ce","fa",
    "ga","ha","je","la","mo","no","pa","qu","ri","sa","ta","va","we","xe","yo","zu",
    "fi","ai","io","dx","ex","ix","ox","ux","fy","ly","ty","cy","sy","zy","ny","ry","py","dy","gy","hy",
    "jy","ky","my","oy","qy","vy","wy","ay","ey","iy","uy"
]
ATOMS_3 = [
    "dax","zil","vor","nex","lux","pix","vox","jax","kio","zen","kai","lev","nox","rax","tiv","sol","nov",
    "ver","lyn","myr","thal","rion","tron","ix","ox","ex","ion","ia","ius","ium","ana","era","ori","ara",
    "ari","ela","ina","ira","ola","ona","ora","ura","yne","ose","ase","ite","ate","ive","ify","ize","ise",
    "acy","ogy","ism","ist","oid","ous","ful","less","ness","ship","tion","sion","ance","ence","ment",
    "able","ible","al","ic","ical","ive","ous","ful","less",
    "chain","swap","flow","base","node","dapp","meta","lab","hub","pay","bit","coin","dex","fi","dao","web",
    "net","sync","mind","rise","peak","core","data","code","nft","defi","crypto","pay","bit","bot","app",
    "pro","max","top","one","run","hub","zip","map","key","pad","tag","box","mix","pop","tip","cap","lap",
    "tap","nap","gap","hip","lip","rip","sip","tip","zip"
]
ATOMS_2 = [a for a in ATOMS_2 if len(a)==2]
ATOMS_3 = [a for a in ATOMS_3 if len(a)==3]

# ---------- VIP Targets (highly valuable words) ----------
VIP_TARGETS = [
    "queen","king","magic","dream","sword","power","blade","ghost","storm","crown",
    "angel","money","ethos","pixel","cyber","crypt","vault","brave","flare","glide",
    "flame","shine","ocean","royal","noble","valor","spark","vivid","zesty","lunar",
    "prime","frost","crisp","brisk","plush","swift","quest","haven","charm","grace",
    "bliss","unity","zonal","vapor","zenith","elite","gloom","mirth","glyph","nymph"
]

# ---------- Word list loader ----------
def load_wordlist():
    try:
        r = requests.get(WORDLIST_URL, timeout=15)
        if r.status_code==200:
            return [w.strip().lower() for w in r.text.splitlines() if len(w.strip())==5]
    except: pass
    return []

# ---------- Beauty scoring ----------
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

# ---------- Variant generators ----------
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
    """6-char username: 4 letters + 2 digits, or 5 letters + 1 digit"""
    while True:
        if random.random()<0.5:
            letters = ''.join(random.choices("abcdefghijklmnopqrstuvwxyz", k=4))
            digits = ''.join(random.choices("0123456789", k=2))
            cand = letters + digits
        else:
            letters = ''.join(random.choices("abcdefghijklmnopqrstuvwxyz", k=5))
            digit = random.choice("0123456789")
            pos = random.randint(0,5)
            cand = letters[:pos] + digit + letters[pos:]
        if len(cand)==6 and cand not in tried:
            return cand

# ---------- DNS checker ----------
def check_username_dns(username):
    domain = f"{username}.t.me"
    try:
        resolver.resolve(domain, 'A')
        return False
    except dns.resolver.NXDOMAIN:
        return True
    except dns.resolver.NoAnswer:
        return False
    except Exception:
        return None

def check_username_http_head(username):
    try:
        r = requests.head(f"https://t.me/{username}", timeout=5, headers={"User-Agent": "Mozilla/5.0"})
        if r.status_code == 200:
            return False
        elif r.status_code == 404:
            return True
        return False
    except Exception:
        return None

def check(username):
    res = check_username_dns(username)
    if res is None:
        res = check_username_http_head(username)
    return res

# ---------- Alert via Telegram bot ----------
def alert(name,score):
    if not TG_BOT_TOKEN or not TG_CHAT_ID: return
    txt=f"💎 *Luxury Diamond!*\n`@{name}`\nScore: {score:.1f}"
    try:
        requests.post(f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage",
                      json={"chat_id":TG_CHAT_ID,"text":txt,"parse_mode":"Markdown"}, timeout=10)
    except: pass

# ---------- VIP sniper thread ----------
def vip_sniper(vips, lock, tried, found, wset, stop):
    while not stop.is_set():
        random.shuffle(vips)
        for user in vips:
            if stop.is_set(): break
            if user in tried: continue
            st = check(user)
            if st is not None:
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
            time.sleep(random.uniform(0.3, 0.6))
        time.sleep(VIP_CHECK_INTERVAL)

# ---------- Main scanner ----------
def main():
    start = time.time()
    scrabble = load_wordlist()
    dream_words = list(set(scrabble + VIP_TARGETS))
    wset = set(scrabble)
    print(f"📚 Seed words: {len(dream_words)}")

    tried = set()
    if os.path.exists(TRIED_FILE):
        with open(TRIED_FILE) as f: tried = set(line.strip() for line in f)

    lock = threading.Lock()
    found = []
    chk = 0
    stop = threading.Event()
    vip = threading.Thread(target=vip_sniper, args=(VIP_TARGETS, lock, tried, found, wset, stop), daemon=True)
    vip.start()

    phase1_end = start + MAX_RUNTIME * 0.8
    try:
        # Phase 1: Brand Atoms (5 chars) – 80% of time
        print("\n⚛️ Phase 1: Brand Atoms (DNS fast)...")
        while time.time() - start < phase1_end:
            cand = gen_atom(tried)
            st = check(cand)
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
                print(f"⚠️ @{cand} (fallback failed)")
            if chk % 20 == 0:
                with open(TRIED_FILE, "a") as f:
                    for u in list(tried)[-20:]: f.write(u + "\n")
            time.sleep(random.uniform(MIN_DELAY, MIN_DELAY*2))

        # Phase 2: Words & Palindromes (5 chars)
        print("\n💎 Phase 2: Words & Palindromes...")
        combined = list(set(dream_words + [w for w in scrabble if w == w[::-1]]))
        random.shuffle(combined)
        for w in combined:
            if time.time() - start > MAX_RUNTIME: break
            for cand in variants_from_word(w):
                if time.time() - start > MAX_RUNTIME: break
                if cand in tried: continue
                st = check(cand)
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
                if chk % 20 == 0:
                    with open(TRIED_FILE, "a") as f:
                        for u in list(tried)[-20:]: f.write(u + "\n")
                time.sleep(random.uniform(MIN_DELAY, MIN_DELAY*2))

        # Phase 3: 6-char usernames (remaining time)
        print("\n🔢 Phase 3: 6-char usernames...")
        while time.time() - start < MAX_RUNTIME:
            cand = gen_6char(tried)
            st = check(cand)
            chk += 1
            if st is not None:
                with lock: tried.add(cand)
            if st is True:
                sc = calc_score(cand, wset)
                if sc >= FILTER_LEVEL_6:
                    with lock: found.append((cand, sc))
                    if sc >= 8.5: alert(cand, sc)
                    print(f"🔢 6CHAR: @{cand} (score {sc:.1f})")
            elif st is False:
                print(f"❌ @{cand}")
            else:
                print(f"⚠️ @{cand}")
            if chk % 20 == 0:
                with open(TRIED_FILE, "a") as f:
                    for u in list(tried)[-20:]: f.write(u + "\n")
            time.sleep(random.uniform(MIN_DELAY, MIN_DELAY*2))

    finally:
        stop.set()
        vip.join(timeout=5)

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
