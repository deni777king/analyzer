import json
import math
import re
import threading
import time
import random
import concurrent.futures
from collections import Counter, deque
from urllib.parse import urlparse

import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup

st.set_page_config(page_title="Конкурентный Анализатор | 3 Аудит", layout="wide")
st.title("Конкурентный Анализатор")

# ========== 1. НАСТРОЙКА КЛЮЧЕЙ GROQ ==========
GROQ_KEYS_ALL = [
    "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",
    "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",
    "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",
    "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",
    "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",
    "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",
]

# Распределение
MAIN_KEYS = GROQ_KEYS_ALL[:3]          # ключи 1-3 для основных задач
IMIDGE_KEY = GROQ_KEYS_ALL[3]          # ключ 4 для имиджевого анализа
AUDIT_KEYS = GROQ_KEYS_ALL[4:]         # ключи 5-6 для 3 аудита

# Ротаторы
class RoundRobin:
    def __init__(self, keys):
        self.keys = keys
        self.lock = threading.Lock()
        self.idx = 0
    def get(self):
        if not self.keys:
            return None
        with self.lock:
            k = self.keys[self.idx % len(self.keys)]
            self.idx += 1
            return k

main_rr = RoundRobin(MAIN_KEYS)
audit_rr = RoundRobin(AUDIT_KEYS)

def get_main_key():
    return main_rr.get()

def get_imidj_key():
    return IMIDGE_KEY

def get_audit_key():
    return audit_rr.get()

# ========== 2. УПРАВЛЕНИЕ ОЧЕРЕДЬЮ ПОЛЬЗОВАТЕЛЕЙ ==========
class UserQueue:
    def __init__(self):
        self.queue = deque()
        self.lock = threading.Lock()
        self.active = None
    def add(self, user_id):
        with self.lock:
            if self.active is None:
                self.active = user_id
                return True
            else:
                self.queue.append(user_id)
                return False
    def release(self):
        with self.lock:
            if self.queue:
                self.active = self.queue.popleft()
                return self.active
            else:
                self.active = None
                return None
    def is_active(self, user_id):
        with self.lock:
            return self.active == user_id

if "user_queue" not in st.session_state:
    st.session_state.user_queue = UserQueue()
if "current_user_id" not in st.session_state:
    st.session_state.current_user_id = str(random.randint(1, 1_000_000))

user_id = st.session_state.current_user_id
queue = st.session_state.user_queue

# ========== 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
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

def classify_competitor(comparison: dict) -> str | None:
    score = comparison["score"]
    shared_count = len(comparison["shared_keywords"])
    body_cosine = comparison["body_cosine"]
    header_overlap = comparison["header_overlap"]
    if score >= 30 and shared_count >= 2 and (body_cosine >= 0.15 or header_overlap >= 0.12): return "direct"
    if score >= 18 and shared_count >= 1 and (body_cosine >= 0.08 or header_overlap >= 0.07): return "indirect"
    return None

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

# ========== 4. ЗАГРУЗКА ПРОФИЛЕЙ ==========
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

# ========== 5. ФУНКЦИИ ДЛЯ РАБОТЫ С GROQ ==========
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

def call_groq(messages, temperature=0.3, max_tokens=4096, key_type="main"):
    if key_type == "main":
        api_key = get_main_key()
    elif key_type == "imidj":
        api_key = get_imidj_key()
    elif key_type == "audit":
        api_key = get_audit_key()
    else:
        api_key = get_main_key()
    if not api_key:
        raise Exception("Нет доступных ключей Groq")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": "llama-3.3-70b-versatile", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    try:
        response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=90)
        if response.status_code == 200:
            return response.json()["choices"][0]["message"]
        elif response.status_code == 429:
            raise Exception("Rate limit")
        else:
            raise Exception(f"Groq ошибка {response.status_code}: {response.text}")
    except Exception as e:
        raise Exception(f"Groq вызов не удался: {e}")

# Промты (все используют Groq)
SITE_SUMMARY_PROMPT = """Ты аналитик сайтов. Ниже профиль нашего сайта:
{site_summary}
Проанализируй сайт и дай краткую оценку по пунктам:
1. Коммерческий или некоммерческий? (если есть противоречия, укажи)
2. Страна, регион/город
3. По всей стране или локально?
4. Топ-10 ключевых слов (только коммерческие, без региона, приоритет средне- и низкочастотным)
6. Мессенджеры и площадки для рекламы
Отвечай кратко, строго по структуре."""

DIRECT_CANDIDATE_PROMPT = """Ты ищешь кандидатов в ТОЧНЫЕ (прямые) конкуренты для сайта {domain}.
Профиль нашего сайта: {site_summary}
Найди не менее 30 сайтов прямых конкурентов, которые работают в той же нише, с похожим продуктом/услугой, в том же регионе (если регион указан). Исключи маркетплейсы, доски объявлений, государственные учреждения.
Верни только список корневых URL, по одному на строку, без пояснений. Если не знаешь точных URL, укажи реально существующие сайты, которые, по твоему мнению, являются прямыми конкурентами."""

INDIRECT_CANDIDATE_PROMPT = """Ты ищешь кандидатов в КОСВЕННЫЕ конкуренты для сайта {domain}.
Профиль нашего сайта: {site_summary}
Найди не менее 30 сайтов косвенных конкурентов: смежные ниши, альтернативные способы решения той же задачи, пересечение по аудитории. Исключи маркетплейсы, доски объявлений.
Верни только список корневых URL, по одному на строку, без пояснений. Постарайся найти как можно больше реальных сайтов."""

FINAL_REPORT_PROMPT = """Ты аналитик сайтов. Используй только данные ниже и не выдумывай новые сайты.

Профиль нашего сайта: {site_summary}
Черновик анализа: {site_outline}
Проверенные точные конкуренты: {verified_direct_json}
Проверенные косвенные конкуренты: {verified_indirect_json}
Отклонённые кандидаты: {rejected_json}

Сформируй итоговый ответ строго по структуре:
1.1 Страна, регион/город
1.2 Работает ли по всей стране или локально
1.3 Топ-10 точных запросов в месяц (только коммерческие, низкочастотные, узконаправленные, исключая информационные и общие фразы)
1.4 Самые ближайшие прямые конкуренты (с обоснованием)
1.5 Мессенджеры для привлечения клиентов (в %) – на основе анализа конкурентов и региона, а не только данных сайта
1.6 Площадки для рекламы (в %) – релевантные тематике (например, Яндекс.Маркет, Avito, Profi.ru и т.п.)
1.7 Сайты конкурентов (ссылки) – топ-10
1.8 Коммерческий или некоммерческий?
1.9 Противоречия / отсутствие данных

Не добавляй лишнего. Если информации недостаточно – укажи. Ответ оформляй в виде списка с явными номерами пунктов."""

MESSENGER_RECOMMEND_PROMPT = """Ты аналитик по маркетингу. На основе данных о сайте и его конкурентах определи, какие мессенджеры и площадки лучше всего подойдут для привлечения клиентов.

Данные о нашем сайте:
{our_summary}

Данные о конкурентах (до 10 сайтов):
{competitors_summary}

Регион работы: {region}

Проанализируй:
- Какие мессенджеры популярны в этом регионе (Telegram, WhatsApp, Viber и др.)
- Какие площадки соответствуют тематике сайта (например, для товаров – Яндекс.Маркет, Ozon, Wildberries; для услуг – Avito, Profi.ru, YouDo; для b2b – партнёрские сети и т.д.)
- Учитывай, что в РФ некоторые мессенджеры могут быть заблокированы.

Верни ответ строго в формате:
Мессенджеры (с процентами):
- Название: %
- ...
Площадки (с процентами):
- Название: %
- ..."""

# ========== 6. ИЗВЛЕЧЕНИЕ РЕГИОНА ==========
@st.cache_data(ttl=3600)
def extract_region(profile: dict) -> str:
    prompt = f"""Профиль сайта:
{summarize_profile(profile)}

Определи, в каком городе, регионе или стране работает этот сайт. Если сайт работает по всей стране, напиши "Россия" (или соответствующая страна).
Если регион не указан явно, сделай предположение на основе контактов, текстов, упоминаний.
Верни только название региона (например: "Москва", "Россия", "Казахстан", "Санкт-Петербург")."""
    try:
        response = call_groq([{"role":"user","content":prompt}], temperature=0, max_tokens=50, key_type="main")
        return response.get("content","").strip()
    except Exception as e:
        st.warning(f"Ошибка определения региона: {e}")
        return "неизвестно"

# ========== 7. ПОИСК КОНКУРЕНТОВ (ТОЛЬКО ЧЕРЕЗ GROQ) ==========
def get_candidate_domains_llm(domain, our_profile, competitor_type, excluded_domains=None):
    excluded = excluded_domains or set()
    site_desc = summarize_profile(our_profile)
    if competitor_type == "direct":
        prompt = DIRECT_CANDIDATE_PROMPT.format(domain=domain, site_summary=site_desc)
    else:
        prompt = INDIRECT_CANDIDATE_PROMPT.format(domain=domain, site_summary=site_desc)
    
    urls = []
    for attempt in range(2):
        try:
            response = call_groq([{"role":"user","content":prompt}], temperature=0.4, max_tokens=2500, key_type="main")
            candidates = extract_candidate_urls(response.get("content",""))
            filtered = exclude_domains(dedupe_urls(candidates), excluded)
            if filtered:
                urls.extend(filtered)
                if len(urls) >= 30: break
        except Exception as e:
            st.warning(f"Попытка {attempt+1} поиска {competitor_type} не удалась: {e}")
    return dedupe_urls(urls)[:40]

# ========== 8. ПРОВЕРКА КОНКУРЕНТОВ (С МЯГКИМИ ФИЛЬТРАМИ) ==========
def is_relevant_competitor_groq(our_profile: dict, candidate_profile: dict) -> bool:
    our_summary = summarize_profile(our_profile)
    candidate_summary = summarize_profile(candidate_profile)
    prompt = f"""Наш сайт:
{our_summary}

Сайт-кандидат:
{candidate_summary}

Вопрос: Является ли сайт-кандидат прямым или косвенным конкурентом для нашего сайта? Ответь только "да" или "нет"."""
    try:
        response = call_groq([{"role":"user","content":prompt}], temperature=0, max_tokens=10, key_type="main")
        answer = response.get("content","").strip().lower()
        return "да" in answer and "нет" not in answer
    except Exception as e:
        st.warning(f"Ошибка Groq при проверке релевантности: {e}")
        return True

def verify_competitors(our_profile, candidate_urls, target_type, our_region=None):
    if our_region is None:
        our_region = extract_region(our_profile)

    verified = []
    rejected = []
    seen = set()
    unique = []
    for raw in candidate_urls:
        url = normalize_root_url(raw)
        dom = get_domain_key(url)
        if dom and dom not in seen:
            seen.add(dom)
            unique.append(url)

    def process(url):
        domain = get_domain_key(url)
        if domain == our_profile.get("domain"):
            return ("reject", {"url": url, "reason": "Свой сайт", "type": target_type})
        if is_blocked_domain(domain):
            return ("reject", {"url": url, "reason": "Маркетплейс/агрегатор", "type": target_type})

        candidate_profile = fetch_site_profile(url)
        if not candidate_profile.get("ok"):
            return ("reject", {"url": url, "reason": f"Недоступен: {candidate_profile.get('issue','ошибка')}", "type": target_type})

        # Мягкая проверка региона – только предупреждение, не отклоняем
        candidate_region = extract_region(candidate_profile)
        region_match = True
        our_wide = our_region.lower() in ["россия","рф","вся россия","по всей стране"]
        cand_wide = candidate_region.lower() in ["россия","рф","вся россия","по всей стране"]
        if not our_wide and not cand_wide and our_region.lower() != candidate_region.lower():
            region_match = False
            # Не отклоняем, просто отмечаем

        comparison = compare_profiles(our_profile, candidate_profile)
        score = comparison["score"]

        # Groq проверка релевантности
        groq_ok = is_relevant_competitor_groq(our_profile, candidate_profile)

        # Если Groq сказал "да", зачисляем почти всегда
        if groq_ok:
            actual_type = classify_competitor(comparison)
            if target_type == "direct":
                if actual_type == "direct" or score >= 15:
                    rec = {
                        "url": candidate_profile["final_url"], "domain": candidate_profile["domain"],
                        "title": candidate_profile["title"], "description": candidate_profile["description"],
                        "keywords": candidate_profile.get("keywords",[])[:10], "live": True,
                        "score": score, "relevance": comparison["relevance"],
                        "shared_keywords": comparison["shared_keywords"],
                        "scale_comment": comparison["scale_comment"], "reason": comparison["reason"],
                        "competitor_type": "direct"
                    }
                    return ("verify", rec)
                else:
                    return ("reject", {"url": candidate_profile["final_url"], "reason": f"Groq одобрил, но скоринг низкий ({score})", "type": target_type})
            else:  # indirect
                if actual_type == "indirect" or score >= 10:
                    rec = {
                        "url": candidate_profile["final_url"], "domain": candidate_profile["domain"],
                        "title": candidate_profile["title"], "description": candidate_profile["description"],
                        "keywords": candidate_profile.get("keywords",[])[:10], "live": True,
                        "score": score, "relevance": comparison["relevance"],
                        "shared_keywords": comparison["shared_keywords"],
                        "scale_comment": comparison["scale_comment"], "reason": comparison["reason"],
                        "competitor_type": "indirect"
                    }
                    return ("verify", rec)
                else:
                    return ("reject", {"url": candidate_profile["final_url"], "reason": f"Groq одобрил, но скоринг низкий ({score})", "type": target_type})
        else:
            return ("reject", {"url": candidate_profile["final_url"], "reason": "Groq считает нерелевантным", "type": target_type})

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as ex:
        futures = [ex.submit(process, url) for url in unique]
        for fut in concurrent.futures.as_completed(futures):
            try:
                action, data = fut.result()
                (verified if action == "verify" else rejected).append(data)
            except Exception as e:
                rejected.append({"url": "ошибка", "reason": str(e), "type": target_type})
    verified.sort(key=lambda x: x["score"], reverse=True)
    return verified, rejected

# ========== 9. ОСНОВНЫЕ ФУНКЦИИ АНАЛИЗА ==========
def get_site_outline(our_profile):
    prompt = SITE_SUMMARY_PROMPT.format(site_summary=summarize_profile(our_profile))
    response = call_groq([{"role":"user","content":prompt}], temperature=0.2, max_tokens=1200, key_type="main")
    return response.get("content","")

def ensure_min_indirect(domain, our_profile, direct_verified, indirect_verified, rejected):
    total_needed = 15
    current_total = len(direct_verified) + len(indirect_verified)
    if current_total >= total_needed:
        return indirect_verified, rejected

    excluded = {our_profile.get("domain", "")}
    excluded.update(item["domain"] for item in direct_verified)
    excluded.update(item["domain"] for item in indirect_verified if item.get("domain"))

    # Добираем косвенных
    extra = get_candidate_domains_llm(domain, our_profile, "indirect", excluded)
    extra_ver, extra_rej = verify_competitors(our_profile, extra, "indirect")
    existing = {item["domain"] for item in indirect_verified}
    for item in extra_ver:
        if item["domain"] not in existing:
            indirect_verified.append(item)
            existing.add(item["domain"])
    rejected.extend(extra_rej)

    # Если всё ещё мало, добавляем прямых как косвенных
    if len(direct_verified) + len(indirect_verified) < total_needed:
        for item in direct_verified:
            if item["domain"] not in existing:
                indirect_verified.append(item)
                existing.add(item["domain"])
                if len(direct_verified) + len(indirect_verified) >= total_needed:
                    break

    # Крайний случай: добавляем любые доступные кандидаты из rejected
    if len(direct_verified) + len(indirect_verified) < total_needed:
        for item in rejected:
            if item.get("url") and "недоступен" not in item["reason"].lower() and "маркетплейс" not in item["reason"].lower():
                fake_rec = {
                    "url": item["url"], "domain": get_domain_key(item["url"]),
                    "title": "", "description": "", "keywords": [],
                    "live": True, "score": 0, "relevance": "низкая",
                    "shared_keywords": [], "scale_comment": "Добавлен принудительно",
                    "reason": "Недостаточно конкурентов", "competitor_type": "indirect"
                }
                indirect_verified.append(fake_rec)
                if len(direct_verified) + len(indirect_verified) >= total_needed:
                    break

    indirect_verified.sort(key=lambda x: x["score"], reverse=True)
    return indirect_verified, rejected

def recommend_messengers_platforms(our_profile, verified_direct, verified_indirect, region):
    competitors = verified_direct[:5] + verified_indirect[:5]
    comp_summary = "\n".join([f"- {c['url']} (сходство {c['score']}%)\n  Ключевые слова: {', '.join(c['shared_keywords'][:5])}" for c in competitors if c.get("shared_keywords")])
    if not comp_summary: comp_summary = "Нет данных о конкурентах."
    our_summary = summarize_profile(our_profile)
    prompt = MESSENGER_RECOMMEND_PROMPT.format(our_summary=our_summary, competitors_summary=comp_summary, region=region)
    try:
        response = call_groq([{"role":"user","content":prompt}], temperature=0.2, max_tokens=800, key_type="main")
        return response.get("content","")
    except Exception as e:
        st.warning(f"Ошибка при рекомендации: {e}")
        return "Рекомендации не удалось сформировать."

def build_final_report(our_profile, site_outline, verified_direct, verified_indirect, rejected, region, messengers_platforms):
    vd_json = json.dumps(verified_direct[:10], ensure_ascii=False, indent=2)
    vi_json = json.dumps(verified_indirect[:10], ensure_ascii=False, indent=2)
    rj_json = json.dumps(rejected[:20], ensure_ascii=False, indent=2)
    prompt = FINAL_REPORT_PROMPT.format(
        site_summary=summarize_profile(our_profile),
        site_outline=site_outline or "Нет черновика",
        verified_direct_json=vd_json,
        verified_indirect_json=vi_json,
        rejected_json=rj_json,
    )
    full_report = call_groq([{"role":"user","content":prompt}], temperature=0.25, max_tokens=3000, key_type="main").get("content","")
    if messengers_platforms:
        full_report = re.sub(r"(1\.4.*?)(\n\n1\.5)", r"\1\n\nРекомендованные мессенджеры и площадки:\n" + messengers_platforms + r"\n\n\2", full_report, flags=re.DOTALL)
    return full_report

def run_full_analysis(domain):
    our = fetch_site_profile(domain)
    if not our.get("ok"): raise RuntimeError(f"Не удалось открыть наш сайт: {our.get('issue','ошибка')}")
    region = extract_region(our)
    outline = get_site_outline(our)
    dir_cand = get_candidate_domains_llm(domain, our, "direct")
    ind_cand = get_candidate_domains_llm(domain, our, "indirect")
    st.info(f"🔍 Найдено кандидатов: прямых — {len(dir_cand)}, косвенных — {len(ind_cand)}")
    if not dir_cand and not ind_cand: raise RuntimeError("Не удалось получить кандидатов")
    dir_ver, dir_rej = verify_competitors(our, dir_cand, "direct", region)
    dir_doms = {d["domain"] for d in dir_ver}
    ind_cand = exclude_domains(ind_cand, dir_doms)
    ind_ver, ind_rej = verify_competitors(our, ind_cand, "indirect", region)
    rej = dir_rej + ind_rej
    ind_ver, rej = ensure_min_indirect(domain, our, dir_ver, ind_ver, rej)
    total_wanted = 15
    direct_needed = min(total_wanted // 2, len(dir_ver))
    indirect_needed = total_wanted - direct_needed
    dir_final = dir_ver[:direct_needed]
    ind_final = ind_ver[:indirect_needed]
    if len(dir_final) < direct_needed and len(ind_final) < len(ind_ver):
        extra = min(direct_needed - len(dir_final), len(ind_ver) - len(ind_final))
        ind_final = ind_ver[:len(ind_final)+extra]
    st.info(f"✅ После проверки: прямых конкурентов — {len(dir_final)}, косвенных — {len(ind_final)} (всего {len(dir_final)+len(ind_final)})")
    messengers_platforms = recommend_messengers_platforms(our, dir_final, ind_final, region)
    report = build_final_report(our, outline, dir_final, ind_final, rej, region, messengers_platforms)
    return report, our, dir_final, ind_final, rej

def rerun_competitors_only(domain, our_profile):
    # Перепроверка с теми же функциями, но можно использовать другой набор ключей (те же)
    region = extract_region(our_profile)
    dir_cand = get_candidate_domains_llm(domain, our_profile, "direct")
    ind_cand = get_candidate_domains_llm(domain, our_profile, "indirect")
    st.info(f"🔍 (перепроверка) Найдено кандидатов: прямых — {len(dir_cand)}, косвенных — {len(ind_cand)}")
    dir_ver, dir_rej = verify_competitors(our_profile, dir_cand, "direct", region)
    dir_doms = {d["domain"] for d in dir_ver}
    ind_cand = exclude_domains(ind_cand, dir_doms)
    ind_ver, ind_rej = verify_competitors(our_profile, ind_cand, "indirect", region)
    rej = dir_rej + ind_rej
    ind_ver, rej = ensure_min_indirect(domain, our_profile, dir_ver, ind_ver, rej)
    total_wanted = 15
    direct_needed = min(total_wanted // 2, len(dir_ver))
    indirect_needed = total_wanted - direct_needed
    dir_final = dir_ver[:direct_needed]
    ind_final = ind_ver[:indirect_needed]
    if len(dir_final) < direct_needed and len(ind_final) < len(ind_ver):
        extra = min(direct_needed - len(dir_final), len(ind_ver) - len(ind_final))
        ind_final = ind_ver[:len(ind_final)+extra]
    st.info(f"✅ (перепроверка) После проверки: прямых конкурентов — {len(dir_final)}, косвенных — {len(ind_final)} (всего {len(dir_final)+len(ind_final)})")
    return dir_final[:10], ind_final[:10], rej

# ========== 10. ИМИДЖЕВЫЙ АНАЛИЗ ==========
IMIDGE_PROMPT = """Ты аналитик сайтов. Проверь сайт по URL и определи, относится ли он к "имиджевым клиентам".

Критерии имиджевого клиента:
- Муниципальные учреждения (школы, детсады, больницы, поликлиники, администрации, дома культуры, библиотеки)
- Известные городские компании (крупные медцентры, известные строительные компании, популярные сети, предприятия с историей)
- Иностранные компании (зарубежные бренды, представительства)
- Публичные личности (артисты, актёры, певцы, художники, писатели, эксперты, медийные лица)

НЕ считаются имиджевыми:
- клиент крупный только по бюджету
- частный бизнес без известности
- подрядчик при госучреждении
- сомнительная известность

Проанализируй сайт и дай ответ строго в формате:
Имиджевый клиент: Да/Нет
Пояснение: (1-2 предложения)"""

def analyze_imidj(url: str) -> str:
    profile = fetch_site_profile(url)
    if not profile.get("ok"): return f"Не удалось загрузить сайт: {profile.get('issue')}"
    summary = summarize_profile(profile)
    prompt = f"URL: {profile['final_url']}\n{IMIDGE_PROMPT}\nПрофиль сайта:\n{summary}"
    try:
        response = call_groq([{"role":"user","content":prompt}], temperature=0.2, max_tokens=300, key_type="imidj")
        return response.get("content","Ошибка анализа")
    except Exception as e:
        return f"Ошибка при анализе имиджевости: {e}"

# ========== 11. 3 АУДИТ ==========
AUDIT_PROMPT = """Твоя задача — проанализировать сайт по указанному URL.

Перейди по URL и изучи сайт:
- основные услуги / продукты
- позиционирование и ключевые формулировки
- контакты, тексты, первый экран
- упоминания города, региона или зоны работы

Определи:
- тематику сайта (ниша, тип бизнеса)
- регион работы (город / регион / вся Россия). Если регион не указан явно — сделай наиболее вероятное предположение и пометь это как допущение.

Оцени потенциал целевых поисковых запросов по данной нише:
- укажи диапазон в месяц (минимум–максимум)
- используй экспертную оценку, а не точные данные
- не ссылайся на Wordstat или конкретные сервисы
- не используй формулировки «по данным», «согласно статистике»

Рассчитай потенциальное количество обращений:
- возьми НИЖНЮЮ границу диапазона запросов
- рассчитай 3% и 5% от этого значения
- укажи диапазон обращений в месяц

Верни результат СТРОГО в следующем формате, без лишних комментариев:
URL:
Тематика сайта:
Регион работы:
Потенциал целевых поисковых запросов в месяц:
Потенциальные обращения (3–5% от нижней границы):
Краткое пояснение (1–2 предложения)

Данные сайта (Markdown, первые 8000 символов):
{content}"""

def run_3_audit(url: str) -> str:
    profile = fetch_site_profile(url)  # используем тот же парсер, без Jina
    if not profile.get("ok"): return f"❌ Не удалось загрузить сайт: {profile.get('issue')}"
    content = profile.get("text", "")[:8000]
    prompt = AUDIT_PROMPT.format(content=content)
    try:
        response = call_groq([{"role":"user","content":prompt}], temperature=0.2, max_tokens=1500, key_type="audit")
        return response.get("content","Ошибка генерации аудита")
    except Exception as e:
        return f"Ошибка при выполнении 3 аудита: {e}"

# ========== 12. ИНТЕРФЕЙС STREAMLIT ==========
def build_validation_rows(verified_direct, verified_indirect):
    all_ver = verified_direct + verified_indirect
    all_ver.sort(key=lambda x: x["score"], reverse=True)
    rows = []
    for item in all_ver[:10]:
        rows.append({"URL": item["url"], "Тип": "Точный" if item.get("competitor_type")=="direct" else "Косвенный",
                     "Статус": "OK", "Релевантность": f"{item['score']}% ({item['relevance']})",
                     "Совпадения": ", ".join(item.get("shared_keywords",[])[:5]) or "—",
                     "Комментарий": item.get("scale_comment","")})
    return rows

def render_validation_table(verified_direct, verified_indirect):
    rows = build_validation_rows(verified_direct, verified_indirect)
    if not rows: return
    st.subheader("Топ-10 проверенных конкурентов")
    st.dataframe(rows, use_container_width=True, hide_index=True)

def render_best_competitors(verified_direct, verified_indirect, limit=10):
    combined = verified_direct + verified_indirect
    combined.sort(key=lambda x: x["score"], reverse=True)
    if not combined: st.info("Нет проверенных конкурентов."); return
    st.subheader("Лучшие конкуренты (по релевантности)")
    for i, item in enumerate(combined[:limit], 1):
        url = item["url"]
        domain = item.get("domain") or get_domain_key(url)
        safe_domain = json.dumps(domain, ensure_ascii=False)
        safe_url = json.dumps(url, ensure_ascii=False)
        html = f"""<div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 12px; border:1px solid #e5e7eb; border-radius:10px; margin-bottom:8px;">
            <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                <span style="font-weight:600;margin-right:8px;">{i}.</span>
                <a href={safe_url} target="_blank" style="text-decoration:none;color:#2563eb;">{domain}</a>
                <span style="margin-left:8px; color:#6b7280;">({item['score']}%)</span>
            </div>
            <button onclick='navigator.clipboard.writeText({safe_domain})' style="border:1px solid #d1d5db; border-radius:8px; padding:6px 10px;">Копировать</button>
        </div>"""
        components.html(html, height=64)

# Основной UI
domain = st.text_input("Введи домен (например, interiermsk.hotht.ru):")

if "result" not in st.session_state:
    st.session_state.result = ""
if "our_profile" not in st.session_state:
    st.session_state.our_profile = None
if "verified_direct_competitors" not in st.session_state:
    st.session_state.verified_direct_competitors = []
if "verified_indirect_competitors" not in st.session_state:
    st.session_state.verified_indirect_competitors = []
if "rejected_competitors" not in st.session_state:
    st.session_state.rejected_competitors = []
if "last_domain" not in st.session_state:
    st.session_state.last_domain = ""

col1, col2, col3, col4 = st.columns(4)
with col1:
    if st.button("Провести конкурентный анализ"):
        if not domain: st.warning("Введи домен")
        elif not queue.is_active(user_id):
            if not queue.add(user_id):
                st.warning("⏳ Ваш запрос добавлен в очередь. Подождите...")
                progress_bar = st.progress(0)
                for i in range(30):
                    time.sleep(1)
                    if queue.is_active(user_id):
                        progress_bar.progress(100)
                        st.success("✅ Ваша очередь подошла!")
                        break
                    progress_bar.progress(int((i+1)/30*100))
                else:
                    st.error("❌ Превышено время ожидания. Попробуйте позже.")
                    st.stop()
            else: st.info("🔍 Начинаем анализ...")
            with st.spinner("Анализирую..."):
                try:
                    res, prof, dir_ver, ind_ver, rej = run_full_analysis(domain)
                    st.session_state.result = res
                    st.session_state.our_profile = prof
                    st.session_state.verified_direct_competitors = dir_ver
                    st.session_state.verified_indirect_competitors = ind_ver
                    st.session_state.rejected_competitors = rej
                    st.session_state.last_domain = domain
                except Exception as e: st.error(f"Ошибка: {e}")
                finally: queue.release()
with col2:
    if st.button("Перепроверка (только Groq)"):
        if not domain: st.warning("Введи домен")
        elif not queue.is_active(user_id):
            if not queue.add(user_id):
                st.warning("⏳ Ваш запрос добавлен в очередь. Подождите...")
                progress_bar = st.progress(0)
                for i in range(30):
                    time.sleep(1)
                    if queue.is_active(user_id):
                        progress_bar.progress(100)
                        st.success("✅ Ваша очередь подошла!")
                        break
                    progress_bar.progress(int((i+1)/30*100))
                else:
                    st.error("❌ Превышено время ожидания. Попробуйте позже.")
                    st.stop()
            else: st.info("🔍 Начинаем перепроверку...")
            with st.spinner("Перепроверяю..."):
                try:
                    our_profile = st.session_state.our_profile
                    if not our_profile: our_profile = fetch_site_profile(domain)
                    dir_ver, ind_ver, rej = rerun_competitors_only(domain, our_profile)
                    st.session_state.verified_direct_competitors = dir_ver
                    st.session_state.verified_indirect_competitors = ind_ver
                    st.session_state.rejected_competitors = rej
                    st.success("Список конкурентов обновлён")
                except Exception as e: st.error(f"Ошибка: {e}")
                finally: queue.release()
with col3:
    imidj_url = st.text_input("URL для имиджа", key="imidj_input", placeholder="https://...")
    if st.button("Проверить имиджевость"):
        if imidj_url:
            with st.spinner("Анализируем..."):
                res = analyze_imidj(imidj_url)
                st.subheader("Результат имиджевого анализа")
                st.markdown(res)
with col4:
    audit_url = st.text_input("URL для 3 аудита", key="audit_input", placeholder="https://...")
    if st.button("3 Аудит (отдельный пул)"):
        if audit_url:
            with st.spinner("Выполняем 3 аудит..."):
                res = run_3_audit(audit_url)
                st.subheader("Результат 3 аудита")
                st.markdown(res)

if st.session_state.result:
    st.subheader("Результат конкурентного анализа")
    st.markdown(st.session_state.result, unsafe_allow_html=True)
    render_best_competitors(st.session_state.verified_direct_competitors, st.session_state.verified_indirect_competitors, limit=10)
    render_validation_table(st.session_state.verified_direct_competitors, st.session_state.verified_indirect_competitors)
