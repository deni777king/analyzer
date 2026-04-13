import json
import math
import re
import threading
import time
import random
from collections import Counter, deque
from urllib.parse import urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="Конкурентный Анализатор | 2 пользователя (OpenAI)", layout="wide")
st.title("Конкурентный Анализатор (две линии по 5 сайтов, только OpenAI)")

# ========== 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (парсинг, сравнение) ==========
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}
MARKETPLACE_BLOCKLIST = {
    "avito.ru", "www.avito.ru", "olx.ua", "www.olx.ua", "wildberries.ru", "www.wildberries.ru",
    "ozon.ru", "www.ozon.ru", "market.yandex.ru", "yandex.market", "tiu.ru", "www.tiu.ru",
    "prom.ua", "www.prom.ua", "aliexpress.com", "www.aliexpress.com", "satu.kz", "www.satu.kz",
}
STOPWORDS = {
    "и", "в", "во", "на", "по", "с", "со", "к", "ко", "у", "о", "об", "от", "до", "для",
    "из", "за", "под", "при", "это", "как", "что", "или", "а", "но", "мы", "вы", "они",
    "он", "она", "оно", "их", "его", "ее", "наш", "ваш", "ваши", "наши", "вас", "нам",
    "не", "да", "нет", "же", "ли", "то", "так", "если", "уже", "только", "ещё", "еще",
    "the", "and", "for", "with", "this", "that", "from", "you", "your", "our", "about",
    "home", "main", "index", "официальный", "главная", "меню", "catalog", "shop", "company",
    "контакты", "contact", "contacts", "ru", "com", "org", "net", "www", "http", "https",
}

def build_url_variants(value: str) -> list[str]:
    raw = value.strip()
    if not raw: return []
    raw = re.sub(r"^[\-\s]+", "", raw)
    raw = re.sub(r"[\s/]+$", "", raw)
    raw = raw.replace("http://", "").replace("https://", "")
    raw = raw.replace("www.", "")
    domain = raw.split("/", 1)[0]
    variants = [f"https://{domain}", f"https://www.{domain}", f"http://{domain}", f"http://www.{domain}"]
    return list(dict.fromkeys(variants))

def normalize_root_url(value: str) -> str:
    parsed = urlparse(value if value.startswith(("http://", "https://")) else f"https://{value}")
    netloc = parsed.netloc or parsed.path
    netloc = netloc.lower().strip().replace("http://", "").replace("https://", "").rstrip("/")
    return f"https://{netloc}"

def get_domain_key(value: str) -> str:
    parsed = urlparse(value if value.startswith(("http://", "https://")) else f"https://{value}")
    netloc = (parsed.netloc or parsed.path).lower().strip().replace("http://", "").replace("https://", "").rstrip("/")
    if netloc.startswith("www."): netloc = netloc[4:]
    return netloc

def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()

def count_internal_links(soup: BeautifulSoup, domain: str) -> int:
    count = 0
    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        href_domain = get_domain_key(href) if href.startswith(("http://", "https://")) else domain
        if href_domain == domain: count += 1
    return count

def tokenize(text: str) -> list[str]:
    prepared = clean_text(text.lower().replace("ё", "е"))
    tokens = re.findall(r"[a-zа-я][a-zа-я0-9\-]{1,}", prepared)
    result = []
    for token in tokens:
        if token in STOPWORDS or token.isdigit() or len(token) <= 2: continue
        result.append(token)
    return result

def jaccard_similarity(first: set[str], second: set[str]) -> float:
    if not first or not second: return 0.0
    union = first | second
    if not union: return 0.0
    return len(first & second) / len(union)

def cosine_similarity(counter_a: Counter, counter_b: Counter) -> float:
    if not counter_a or not counter_b: return 0.0
    shared = set(counter_a) & set(counter_b)
    numerator = sum(counter_a[token] * counter_b[token] for token in shared)
    norm_a = math.sqrt(sum(v*v for v in counter_a.values()))
    norm_b = math.sqrt(sum(v*v for v in counter_b.values()))
    if not norm_a or not norm_b: return 0.0
    return numerator / (norm_a * norm_b)

def compare_profiles(our_profile: dict, candidate_profile: dict) -> dict:
    our_counter = Counter(our_profile.get("token_counter", {}))
    candidate_counter = Counter(candidate_profile.get("token_counter", {}))
    our_keywords = our_profile.get("keywords", [])
    candidate_keywords = candidate_profile.get("keywords", [])
    shared_keywords = [kw for kw in our_keywords if kw in candidate_keywords][:10]

    our_head = set(tokenize(" ".join([our_profile.get("title",""), our_profile.get("description",""), " ".join(our_profile.get("headings",[]))])))
    candidate_head = set(tokenize(" ".join([candidate_profile.get("title",""), candidate_profile.get("description",""), " ".join(candidate_profile.get("headings",[]))])))

    body_cosine = cosine_similarity(our_counter, candidate_counter)
    keyword_overlap = 0.0
    if our_keywords and candidate_keywords:
        keyword_overlap = len(set(shared_keywords)) / max(1, min(len(our_keywords), len(candidate_keywords)))
    header_overlap = jaccard_similarity(our_head, candidate_head)

    our_text_len = max(our_profile.get("text_length",0),1)
    cand_text_len = max(candidate_profile.get("text_length",0),1)
    text_ratio = min(our_text_len, cand_text_len) / max(our_text_len, cand_text_len)

    our_links = max(our_profile.get("internal_links",0),1)
    cand_links = max(candidate_profile.get("internal_links",0),1)
    link_ratio = min(our_links, cand_links) / max(our_links, cand_links)
    scale_score = 0.6*text_ratio + 0.4*link_ratio

    thematic_score = 0.55*body_cosine + 0.30*keyword_overlap + 0.15*header_overlap
    final_score = round(((0.8*thematic_score) + (0.2*scale_score)) * 100, 1)

    relevance = "низкая"
    if final_score >= 40: relevance = "высокая"
    elif final_score >= 25: relevance = "средняя"

    scale_comment = "похожий масштаб"
    if scale_score < 0.25: scale_comment = "масштаб заметно отличается"
    elif scale_score < 0.45: scale_comment = "масштаб отличается"

    reason = f"Совпавшие ключи: {', '.join(shared_keywords[:6])}." if shared_keywords else "Мало совпадающих тематических терминов."

    return {
        "score": final_score, "relevance": relevance, "body_cosine": round(body_cosine,3),
        "keyword_overlap": round(keyword_overlap,3), "header_overlap": round(header_overlap,3),
        "scale_score": round(scale_score,3), "scale_comment": scale_comment,
        "shared_keywords": shared_keywords, "reason": reason
    }

def is_blocked_domain(domain: str) -> bool:
    domain = get_domain_key(domain)
    if domain in MARKETPLACE_BLOCKLIST: return True
    return any(domain.endswith(f".{item}") for item in MARKETPLACE_BLOCKLIST)

def summarize_profile(profile: dict) -> str:
    headings = "; ".join(profile.get("headings", [])[:4]) or "нет данных"
    keywords = ", ".join(profile.get("keywords", [])[:12]) or "нет данных"
    snippet = profile.get("snippet", "")[:1200] or "нет данных"
    return (f"Домен: {profile.get('domain','')}\nURL: {profile.get('final_url','')}\nTitle: {profile.get('title','') or 'нет данных'}\n"
            f"Description: {profile.get('description','') or 'нет данных'}\nHeadings: {headings}\nKeywords: {keywords}\nФрагмент текста: {snippet}")

def extract_candidate_urls(text: str) -> list[str]:
    if not text: return []
    pattern = re.compile(r"(?:https?://)?(?:www\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+(?:/[a-zA-Z0-9_./?=&%-]*)?")
    candidates, seen = [], set()
    for raw in pattern.findall(text):
        url = normalize_root_url(raw)
        domain = get_domain_key(url)
        if "." in domain and domain not in seen:
            seen.add(domain)
            candidates.append(url)
    return candidates

def dedupe_urls(urls: list[str]) -> list[str]:
    result, seen = [], set()
    for raw in urls:
        url = normalize_root_url(raw)
        domain = get_domain_key(url)
        if domain and domain not in seen:
            seen.add(domain)
            result.append(url)
    return result

def exclude_domains(urls: list[str], excluded_domains: set[str]) -> list[str]:
    result, seen = [], set()
    for raw in urls:
        url = normalize_root_url(raw)
        domain = get_domain_key(url)
        if domain and domain not in excluded_domains and domain not in seen:
            seen.add(domain)
            result.append(url)
    return result

# ========== 2. ЗАГРУЗКА ПРОФИЛЕЙ ==========
@st.cache_data(show_spinner=False, ttl=3600)
def fetch_site_profile(url_or_domain: str) -> dict:
    variants = build_url_variants(url_or_domain)
    last_error = "Не удалось открыть сайт"
    for candidate in variants:
        try:
            response = requests.get(candidate, headers=REQUEST_HEADERS, timeout=15, allow_redirects=True)
            if response.status_code >= 400:
                last_error = f"HTTP {response.status_code}"
                continue
            content_type = response.headers.get("Content-Type","")
            if "html" not in content_type and "text" not in content_type:
                last_error = f"Неподдерживаемый Content-Type: {content_type}"
                continue
            html = response.text
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script","style","noscript","svg","iframe"]): tag.decompose()
            title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
            description = clean_text((soup.find("meta", attrs={"name":"description"}) or soup.find("meta", attrs={"property":"og:description"}) or {}).get("content",""))
            headings = [clean_text(tag.get_text(" ", strip=True)) for tag in soup.find_all(["h1","h2"], limit=8) if clean_text(tag.get_text(" ", strip=True))]
            text = clean_text(soup.get_text(" ", strip=True))[:15000]
            final_url = response.url
            final_domain = get_domain_key(final_url)
            internal_links = count_internal_links(soup, final_domain)
            if len(text) < 180:
                last_error = "Сайт почти пустой"
                continue
            weighted_text = " ".join([title]*6 + [description]*5 + headings*3 + [text])
            token_counter = Counter(tokenize(weighted_text))
            keywords = [token for token,_ in token_counter.most_common(25)]
            return {
                "ok": True, "live": True, "requested_url": candidate, "final_url": normalize_root_url(final_url),
                "domain": final_domain, "title": title, "description": description, "headings": headings[:5],
                "text": text, "snippet": text[:1500], "status_code": response.status_code,
                "internal_links": internal_links, "text_length": len(text), "keywords": keywords,
                "token_counter": dict(token_counter), "issue": ""
            }
        except Exception as exc:
            last_error = str(exc)
    return {
        "ok": False, "live": False, "requested_url": normalize_root_url(url_or_domain),
        "final_url": normalize_root_url(url_or_domain), "domain": get_domain_key(url_or_domain),
        "title": "", "description": "", "headings": [], "text": "", "snippet": "",
        "status_code": None, "internal_links": 0, "text_length": 0, "keywords": [],
        "token_counter": {}, "issue": last_error
    }

# ========== 3. ВЫЗОВ OPENAI (с обработкой ошибок) ==========
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

def call_openai(messages, api_key, temperature=0.3, max_tokens=4096):
    if not api_key:
        raise Exception("API-ключ не указан")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": "gpt-4o", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    try:
        response = requests.post(OPENAI_API_URL, json=payload, headers=headers, timeout=90)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]
        elif response.status_code == 401:
            raise Exception("Неверный API-ключ. Проверьте ключ в настройках.")
        elif response.status_code == 429:
            raise Exception("Превышена квота использования (insufficient_quota). Пополните баланс или используйте другой ключ.")
        else:
            raise Exception(f"OpenAI ошибка {response.status_code}: {response.text}")
    except requests.exceptions.RequestException as e:
        raise Exception(f"Ошибка сети: {e}")

# ========== 4. ЕДИНЫЙ ПРОМТ ДЛЯ ВСЕХ ПУНКТОВ ==========
def analyze_site_with_openai(domain: str, profile: dict, api_key: str) -> dict:
    summary = summarize_profile(profile)
    prompt = f"""
Твоя роль - аналитик сайтов / SEO-специалист.

1) Проанализируй сайт {profile['final_url']} и выяви его тематику, регион работы.
Обязательно учитывай:
- Блок «О компании», тексты на первом экране, раздел «Услуги / География работ»,
- Упоминания «работаем по России», «по всей территории РФ», «выезд по регионам», «обслуживаем объекты федерального уровня»,
- Кейсы, портфолио, страницу доставки.
Контакты ≠ география бизнеса, контакты = базовый офис. География определяется оффером услуг.
Если сайт имеет домен .uz или .kz, ориентируйся на Google Analytics/Ads.

2) Сделай конкурентный анализ, исходя из тематики и региона. Требования:
- Если сайт работает только в одном городе/регионе, ищи конкурентов только в этом городе/регионе.
- Если на сайте есть указание «по России» или «по всей РФ», ищи по всей России.
- Найди 10 прямых конкурентов с собственными рабочими сайтами (проверь доступность, исключи маркетплейсы, доски объявлений, госучреждения).
- Оцени релевантность каждого конкурента по 5-балльной системе (1 — не релевантен, 5 — идеальный конкурент).

3) Дай по этому сайту самые релевантные коммерческие запросы (10 штук) — только средне- и низкочастотные, с коммерческим интентом (купить, заказать, получить расчёт/консультацию). Не используй названия регионов/городов. Формат: "запрос — количество просмотров в месяц" (если нет данных, просто фраза).

4) Найди мессенджеры и соц.сети, которые размещены на сайтах конкурентов (перечисли основные, без процентов).

5) Найди маркетплейсы и площадки, где размещены сайты конкурентов (каталоги-агрегаторы, справочники, доски объявлений).

Верни результат строго в следующем формате, без лишних комментариев:

Тематика:
Регион:

Конкуренты (с релевантностью):
1. URL — релевантность X/5
2. URL — релевантность X/5
...

Коммерческие запросы:
1. запрос — количество
2. запрос — количество
...

Мессенджеры и соц.сети:
- название
- название

Площадки:
- название
- название

Данные сайта:
{summary}
"""
    try:
        message = call_openai([{"role": "user", "content": prompt}], api_key, temperature=0.2, max_tokens=2000)
        content = message.get("content", "")
        # Парсим ответ
        result = {"topic": "", "region": "", "competitors": [], "queries": [], "messengers": [], "platforms": []}
        lines = content.split("\n")
        section = None
        for line in lines:
            line = line.strip()
            if line.startswith("Тематика:"):
                result["topic"] = line.replace("Тематика:", "").strip()
            elif line.startswith("Регион:"):
                result["region"] = line.replace("Регион:", "").strip()
            elif line.startswith("Конкуренты"):
                section = "competitors"
            elif line.startswith("Коммерческие запросы"):
                section = "queries"
            elif line.startswith("Мессенджеры"):
                section = "messengers"
            elif line.startswith("Площадки"):
                section = "platforms"
            elif section == "competitors" and line and line[0].isdigit():
                # Формат: "1. https://... — релевантность 4/5"
                parts = re.split(r'\s*[—\-]\s*', line, 1)
                url_part = parts[0].strip()
                # Извлекаем URL
                url_match = re.search(r'(https?://[^\s]+)', url_part)
                if url_match:
                    url = url_match.group(1)
                    score_match = re.search(r'релевантность\s*(\d+)/5', line, re.IGNORECASE)
                    score = int(score_match.group(1)) if score_match else 0
                    result["competitors"].append((url, score))
            elif section == "queries" and line and line[0].isdigit():
                result["queries"].append(line)
            elif section == "messengers" and line.startswith("-"):
                result["messengers"].append(line.lstrip("- ").strip())
            elif section == "platforms" and line.startswith("-"):
                result["platforms"].append(line.lstrip("- ").strip())
        return result
    except Exception as e:
        raise Exception(f"Ошибка анализа: {e}")

# ========== 5. АНАЛИЗ ОДНОГО САЙТА (только OpenAI) ==========
def analyze_single_site(domain: str, api_key: str) -> dict:
    results = {"domain": domain, "status": "ok", "error": None, "data": {}}
    try:
        profile = fetch_site_profile(domain)
        if not profile.get("ok"):
            raise RuntimeError(f"Не удалось открыть сайт: {profile.get('issue', 'ошибка')}")

        analysis = analyze_site_with_openai(domain, profile, api_key)
        results["data"]["topic"] = analysis.get("topic", "")
        results["data"]["region"] = analysis.get("region", "")
        results["data"]["competitors"] = analysis.get("competitors", [])
        results["data"]["queries"] = analysis.get("queries", [])
        results["data"]["messengers"] = analysis.get("messengers", [])
        results["data"]["platforms"] = analysis.get("platforms", [])

    except Exception as e:
        results["status"] = "error"
        results["error"] = str(e)
    return results

# ========== 6. ИНТЕРФЕЙС ДЛЯ ДВУХ ПОЛЬЗОВАТЕЛЕЙ ==========
st.sidebar.header("Настройки OpenAI")
api_key_line1 = st.sidebar.text_input("API‑ключ OpenAI (линия 1)", type="password", key="api_key_line1", 
                                      help="Ключ для первого пользователя")
api_key_line2 = st.sidebar.text_input("API‑ключ OpenAI (линия 2)", type="password", key="api_key_line2",
                                      help="Ключ для второго пользователя")
st.sidebar.info("Каждая линия использует свой ключ. Анализ выполняется только через OpenAI (GPT-4o).")

# Линия 1
st.header("👤 Пользователь 1 (линия 1)")
domains1 = []
cols1 = st.columns(5)
for i in range(5):
    with cols1[i]:
        domains1.append(st.text_input(f"Сайт {i+1}", key=f"line1_domain_{i}", placeholder="example.com"))

if st.button("Анализировать (пользователь 1)", key="btn_line1"):
    if not api_key_line1:
        st.error("❌ Введите API-ключ OpenAI для линии 1 в боковой панели")
    else:
        valid = [d.strip() for d in domains1 if d.strip()]
        if not valid:
            st.warning("Введите хотя бы один домен")
        else:
            with st.spinner("Анализируем сайты (это может занять время)..."):
                results_dict = {}
                progress_bar = st.progress(0)
                for idx, domain in enumerate(valid):
                    st.write(f"Обработка {domain}...")
                    try:
                        res = analyze_single_site(domain, api_key_line1)
                        results_dict[domain] = res
                    except Exception as e:
                        results_dict[domain] = {"domain": domain, "status": "error", "error": str(e), "data": {}}
                    progress_bar.progress((idx + 1) / len(valid))
                    time.sleep(0.5)
                # Вывод результатов
                for domain in valid:
                    res = results_dict.get(domain, {"status": "error", "error": "Неизвестная ошибка"})
                    with st.expander(f"📊 {domain}", expanded=True):
                        if res["status"] == "error":
                            st.error(f"Ошибка: {res['error']}")
                            continue
                        data = res["data"]
                        st.markdown(f"**Тематика:** {data.get('topic', '—')}")
                        st.markdown(f"**Регион:** {data.get('region', '—')}")
                        st.markdown("**Конкуренты:**")
                        for url, score in data.get("competitors", []):
                            st.markdown(f"- [{url}]({url}) — релевантность {score}/5")
                        st.markdown("**Коммерческие запросы:**")
                        for q in data.get("queries", []):
                            st.markdown(f"- {q}")
                        st.markdown("**Мессенджеры и соц.сети:**")
                        for m in data.get("messengers", []):
                            st.markdown(f"- {m}")
                        st.markdown("**Площадки:**")
                        for p in data.get("platforms", []):
                            st.markdown(f"- {p}")
            st.success("Анализ завершён!")

# Линия 2
st.header("👤 Пользователь 2 (линия 2)")
domains2 = []
cols2 = st.columns(5)
for i in range(5):
    with cols2[i]:
        domains2.append(st.text_input(f"Сайт {i+1}", key=f"line2_domain_{i}", placeholder="example.com"))

if st.button("Анализировать (пользователь 2)", key="btn_line2"):
    if not api_key_line2:
        st.error("❌ Введите API-ключ OpenAI для линии 2 в боковой панели")
    else:
        valid = [d.strip() for d in domains2 if d.strip()]
        if not valid:
            st.warning("Введите хотя бы один домен")
        else:
            with st.spinner("Анализируем сайты (это может занять время)..."):
                results_dict = {}
                progress_bar = st.progress(0)
                for idx, domain in enumerate(valid):
                    st.write(f"Обработка {domain}...")
                    try:
                        res = analyze_single_site(domain, api_key_line2)
                        results_dict[domain] = res
                    except Exception as e:
                        results_dict[domain] = {"domain": domain, "status": "error", "error": str(e), "data": {}}
                    progress_bar.progress((idx + 1) / len(valid))
                    time.sleep(0.5)
                for domain in valid:
                    res = results_dict.get(domain, {"status": "error", "error": "Неизвестная ошибка"})
                    with st.expander(f"📊 {domain}", expanded=True):
                        if res["status"] == "error":
                            st.error(f"Ошибка: {res['error']}")
                            continue
                        data = res["data"]
                        st.markdown(f"**Тематика:** {data.get('topic', '—')}")
                        st.markdown(f"**Регион:** {data.get('region', '—')}")
                        st.markdown("**Конкуренты:**")
                        for url, score in data.get("competitors", []):
                            st.markdown(f"- [{url}]({url}) — релевантность {score}/5")
                        st.markdown("**Коммерческие запросы:**")
                        for q in data.get("queries", []):
                            st.markdown(f"- {q}")
                        st.markdown("**Мессенджеры и соц.сети:**")
                        for m in data.get("messengers", []):
                            st.markdown(f"- {m}")
                        st.markdown("**Площадки:**")
                        for p in data.get("platforms", []):
                            st.markdown(f"- {p}")
            st.success("Анализ завершён!")
