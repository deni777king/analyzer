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

st.set_page_config(page_title="Конкурентный Анализатор | 5 сайтов + 3 аудит", layout="wide")
st.title("Конкурентный Анализатор (5 сайтов + 3 аудит)")

# ========== 1. НАСТРОЙКА КЛЮЧЕЙ ==========
MISTRAL_KEYS_LINE1 = [
    "uiJLmg6FTBoccElFrCbhV06PDmLPPVuH",
    "NHXvVYh8il4ydpG40zdAr2FypP0PdrOH",
    "AJtcbBOBYlJrpKiAZJDwb71Al5mLExbN",
    "F4BTL3sgx49XPfmBGJxW4vnTp4cw1il9",
]
MISTRAL_KEYS_LINE2 = [
    "Wb0bIlL8TDWdT3iAxEDHE2Dx6fgZRoNG",
    "es65iDRkC1U4a85AxNFceecJBQYZGHqn",
    "xDTZtoJp68uT9Qqsr5PveZMNmqczalwa",
]

EXA_KEYS_LINE1 = [
    "6641c418-b339-4a60-9015-cfe635a8dee0",
    "9963984d-6b17-4bbc-8c8b-8c9c1eaeb5a2",
    "52864684-c02c-4263-a00c-f7200a199841",
    "473e4118-05cf-43a4-b21c-29d833390442",
]
EXA_KEYS_LINE2 = [
    "a69ce51c-b823-4c5f-95d9-3d9bc80ec0c7",
    "c07e3f67-95ec-4248-ba88-71023190b971",
    "1f664dc7-e278-40ed-a4e6-58397d0dfbee",
]

GROQ_KEYS_ALL = [
    "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",
    "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",
    "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",
    "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",
    "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",
    "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",
]
GROQ_KEYS_LINE1 = [GROQ_KEYS_ALL[0]]
GROQ_KEYS_LINE2 = [GROQ_KEYS_ALL[1], GROQ_KEYS_ALL[2]]
GROQ_KEYS_LINE3 = [GROQ_KEYS_ALL[3], GROQ_KEYS_ALL[4], GROQ_KEYS_ALL[5]]

GEMINI_KEYS_ALL = [
    "AIzaSyCIUNviKfWReJZXSx0lmGhZwLR_3oq0mv0",
    "AIzaSyBELdB8pwTRGAHpThWyPhIo8Y55bR34u74",
    "AIzaSyCVris8gA-EoRXojE1eWvP1GJGK6uebgCk",
    "AIzaSyAJP67w_9Z5xmSDVwcE_2L5Rz-v4ktRJSo",
    "AIzaSyDdjbQ47TUjsbUigDgctHUnSJ-BrXvvvkQ",
]
GEMINI_KEYS_LINE1 = [GEMINI_KEYS_ALL[0]]
GEMINI_KEYS_LINE2 = [GEMINI_KEYS_ALL[1], GEMINI_KEYS_ALL[2]]
GEMINI_KEYS_LINE3 = [GEMINI_KEYS_ALL[3], GEMINI_KEYS_ALL[4]]

JINA_3AUDIT_KEY = "jina_d3ebb125d2f24e938e21abf8d562e5498EdB-_JFA3jU8lgOtlvxURphhdBe"
JINA_READER_URL = "https://r.jina.ai/"

LINE_CONFIG = {
    1: {"mistral": MISTRAL_KEYS_LINE1, "exa": EXA_KEYS_LINE1, "groq": GROQ_KEYS_LINE1, "gemini": GEMINI_KEYS_LINE1},
    2: {"mistral": MISTRAL_KEYS_LINE2, "exa": EXA_KEYS_LINE2, "groq": GROQ_KEYS_LINE2, "gemini": GEMINI_KEYS_LINE2},
    3: {"mistral": [], "exa": [], "groq": GROQ_KEYS_LINE3, "gemini": GEMINI_KEYS_LINE3}
}

class RoundRobin:
    def __init__(self, keys):
        self.keys = keys
        self.lock = threading.Lock()
        self.idx = 0
    def get(self):
        if not self.keys: return None
        with self.lock:
            k = self.keys[self.idx % len(self.keys)]
            self.idx += 1
            return k

current_line = 1
line_rr = {
    1: {"groq": RoundRobin(LINE_CONFIG[1]["groq"]), "gemini": RoundRobin(LINE_CONFIG[1]["gemini"])},
    2: {"groq": RoundRobin(LINE_CONFIG[2]["groq"]), "gemini": RoundRobin(LINE_CONFIG[2]["gemini"])},
    3: {"groq": RoundRobin(LINE_CONFIG[3]["groq"]), "gemini": RoundRobin(LINE_CONFIG[3]["gemini"])},
}

def get_exa_keys():
    return LINE_CONFIG[current_line]["exa"]
def get_mistral_keys():
    return LINE_CONFIG[current_line]["mistral"]

def switch_line():
    global current_line
    if current_line < 3:
        current_line += 1
        st.warning(f"⚠️ Переключение на линию {current_line} из-за ошибок/лимитов")
        return True
    else:
        st.error("❌ Все линии исчерпаны. Проверьте API-ключи.")
        return False

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

@st.cache_data(show_spinner=False, ttl=3600)
def browse_page(url: str) -> str:
    profile = fetch_site_profile(url)
    payload = {
        "live": profile["live"], "url": profile["final_url"], "domain": profile["domain"],
        "title": profile["title"], "description": profile["description"], "headings": profile["headings"],
        "keywords": profile["keywords"][:12], "snippet": profile["snippet"], "issue": profile["issue"]
    }
    return json.dumps(payload, ensure_ascii=False)

# ========== 5. ФУНКЦИИ ДЛЯ РАБОТЫ С LLM ==========
tools = [{"type":"function","function":{"name":"browse_page","description":"Проверить сайт по URL и вернуть краткий профиль страницы: живая ли она, тема, заголовок, описание, ключевые слова и краткий фрагмент текста.","parameters":{"type":"object","properties":{"url":{"type":"string"}},"required":["url"]}}}]

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
Правила: используй browse_page для каждого кандидата, исключай маркетплейсы, стремись к минимум 5. Верни только список корневых URL."""

INDIRECT_CANDIDATE_PROMPT = """Ты ищешь кандидатов в КОСВЕННЫЕ конкуренты для сайта {domain}.
Профиль нашего сайта: {site_summary}
Правила: используй browse_page, исключай прямых конкурентов и маркетплейсы, стремись к минимум 5. Верни только список корневых URL."""

FINAL_REPORT_PROMPT = """Ты аналитик сайтов. Используй только данные ниже и не выдумывай новые сайты.

Профиль нашего сайта: {site_summary}
Черновик анализа: {site_outline}
Проверенные точные конкуренты: {verified_direct_json}
Проверенные косвенные конкуренты: {verified_indirect_json}
Отклонённые кандидаты: {rejected_json}

Сформируй итоговый ответ строго по структуре:
1.1 Страна, регион/город
1.2 Работает ли по всей стране или локально
1.3 Топ-10 точных запросов в месяц (коммерческие, без региона, средне- и низкочастотные)
1.4 Самые ближайшие прямые конкуренты (с обоснованием)
1.5 Мессенджеры для привлечения клиентов (в %)
1.6 Площадки для рекламы (в %)
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

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"

def call_mistral(messages, use_tools=False, temperature=0.3, max_tokens=4096):
    keys = get_mistral_keys()
    if not keys: raise Exception("Нет доступных ключей Mistral")
    for api_key in keys:
        try:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"model": "mistral-small-latest", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
            if use_tools: payload["tools"] = tools
            response = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=90)
            if response.status_code == 200: return response.json()["choices"][0]["message"]
            elif response.status_code == 429: raise Exception("Rate limit")
            elif response.status_code == 401: continue
        except: continue
    raise Exception("Все ключи Mistral не сработали")

def call_groq(messages, temperature=0.3, max_tokens=4096):
    # Пробуем все ключи текущей линии
    rr = line_rr[current_line]["groq"]
    for attempt in range(3):
        api_key = rr.get()
        if not api_key: break
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.3-70b-versatile", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        try:
            response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=90)
            if response.status_code == 200: return response.json()["choices"][0]["message"]
            elif response.status_code == 429: raise Exception("Rate limit")
            elif response.status_code == 401: continue
        except Exception as e:
            continue
    # Если не помогло, переключаем линию
    if switch_line():
        return call_groq(messages, temperature, max_tokens)
    else:
        raise Exception("Все ключи Groq не сработали")

def call_gemini(messages, temperature=0.3, max_tokens=4096):
    rr = line_rr[current_line]["gemini"]
    for attempt in range(3):
        api_key = rr.get()
        if not api_key: break
        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else msg["role"]
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        payload = {"contents": contents, "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
        url = f"{GEMINI_API_URL}?key={api_key}"
        try:
            response = requests.post(url, json=payload, timeout=90)
            if response.status_code == 200:
                data = response.json()
                return {"role": "assistant", "content": data["candidates"][0]["content"]["parts"][0]["text"]}
            elif response.status_code == 429: raise Exception("Rate limit")
            elif response.status_code == 401: continue
        except: continue
    if switch_line():
        return call_gemini(messages, temperature, max_tokens)
    else:
        raise Exception("Все ключи Gemini не сработали")

def call_llm_with_fallback(messages, use_tools=False, temperature=0.3, max_tokens=4096):
    if use_tools:
        try:
            return call_mistral(messages, use_tools=True, temperature=temperature, max_tokens=max_tokens)
        except Exception as e:
            if "Rate limit" in str(e):
                if switch_line(): return call_llm_with_fallback(messages, use_tools, temperature, max_tokens)
                else: raise
            raise
    else:
        providers = [("Mistral", call_mistral), ("Gemini", call_gemini), ("Groq", call_groq)]
        for name, func in providers:
            try:
                return func(messages, temperature=temperature, max_tokens=max_tokens)
            except Exception as e:
                if "Rate limit" in str(e) or "429" in str(e):
                    if switch_line(): return call_llm_with_fallback(messages, use_tools, temperature, max_tokens)
                continue
        raise Exception("Все провайдеры не смогли обработать запрос")

def complete_with_tools(messages, temperature=0.3, max_tokens=4096):
    conversation = list(messages)
    for _ in range(12):
        try:
            msg = call_llm_with_fallback(conversation, use_tools=True, temperature=temperature, max_tokens=max_tokens)
        except Exception as e:
            st.error(f"Ошибка вызова LLM с tools: {e}")
            raise
        conversation.append(msg)
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls: return msg.get("content","")
        def process(tc):
            func = tc.get("function",{})
            if func.get("name") != "browse_page": return None
            try:
                args = json.loads(func.get("arguments","{}"))
                url = args.get("url","")
                content = browse_page(url) if url else json.dumps({"error":"Пустой URL"}, ensure_ascii=False)
            except Exception as e:
                content = json.dumps({"error":str(e)}, ensure_ascii=False)
            return {"role":"tool","tool_call_id":tc["id"],"name":"browse_page","content":content}
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            results = list(ex.map(process, tool_calls))
        for r in results:
            if r: conversation.append(r)
    return "Не удалось завершить обработку tool calls."

# ========== 6. ПОИСК КОНКУРЕНТОВ (EXA) ==========
def search_exa(query: str, num_results: int = 15) -> list[str]:
    keys = get_exa_keys()
    if not keys: return []
    for api_key in keys:
        try:
            url = "https://api.exa.ai/search"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {"query": query, "type": "neural", "numResults": num_results, "contents": {"text": False}}
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                return dedupe_urls([normalize_root_url(r["url"]) for r in data.get("results", [])])
            elif response.status_code == 429: continue
        except: continue
    raise Exception("Все ключи Exa не сработали")

def get_candidate_domains(domain, our_profile, competitor_type, excluded_domains=None):
    excluded = excluded_domains or set()
    if competitor_type == "direct":
        query = f"similar to {domain}"
    else:
        query = f"companies in related niches to {domain}"
    try:
        exa_urls = search_exa(query, num_results=20)
    except Exception as e:
        if switch_line():
            return get_candidate_domains(domain, our_profile, competitor_type, excluded_domains)
        else:
            return []
    return exclude_domains(dedupe_urls(exa_urls), excluded)

# ========== 7. ПРОВЕРКА КОНКУРЕНТОВ ==========
def is_relevant_competitor(our_profile: dict, candidate_profile: dict) -> bool:
    our_summary = summarize_profile(our_profile)
    candidate_summary = summarize_profile(candidate_profile)
    prompt = f"""
Наш сайт:
{our_summary}

Сайт-кандидат:
{candidate_summary}

Вопрос: Является ли сайт-кандидат прямым или косвенным конкурентом для нашего сайта? Ответь только "да" или "нет".
"""
    try:
        response = call_llm_with_fallback([{"role": "user", "content": prompt}], use_tools=False, temperature=0, max_tokens=10)
        answer = response.get("content", "").strip().lower()
        return "да" in answer and "нет" not in answer
    except Exception as e:
        st.warning(f"Ошибка LLM при проверке релевантности: {e}")
        return True

def verify_competitors(our_profile, candidate_urls, target_type):
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
            return ("reject", {"url": url, "reason": f"Недоступен: {candidate_profile.get('issue', 'ошибка')}", "type": target_type})

        our_keywords_set = set(our_profile.get("keywords", []))
        candidate_keywords_set = set(candidate_profile.get("keywords", []))
        if not (our_keywords_set & candidate_keywords_set):
            return ("reject", {"url": candidate_profile["final_url"], "reason": "Нет общих ключевых слов", "type": target_type})

        comparison = compare_profiles(our_profile, candidate_profile)
        if comparison["score"] < 10:
            return ("reject", {"url": candidate_profile["final_url"], "reason": f"Низкая оценка сходства ({comparison['score']}%)", "type": target_type})

        if not is_relevant_competitor(our_profile, candidate_profile):
            return ("reject", {"url": candidate_profile["final_url"], "reason": "Не является релевантным конкурентом по оценке LLM", "type": target_type})

        actual_type = classify_competitor(comparison)
        rec = {
            "url": candidate_profile["final_url"], "domain": candidate_profile["domain"], "title": candidate_profile["title"],
            "description": candidate_profile["description"], "keywords": candidate_profile.get("keywords", [])[:10],
            "live": True, "score": comparison["score"], "relevance": comparison["relevance"],
            "shared_keywords": comparison["shared_keywords"], "scale_comment": comparison["scale_comment"],
            "reason": comparison["reason"], "competitor_type": actual_type or "rejected",
        }
        if target_type == "direct":
            if actual_type == "direct":
                return ("verify", rec)
            else:
                return ("reject", {"url": candidate_profile["final_url"], "reason": f"Не прошёл как точный ({comparison['score']}%). {comparison['reason']}", "type": "direct"})
        else:
            if actual_type == "indirect":
                return ("verify", rec)
            elif actual_type == "direct":
                return ("reject", {"url": candidate_profile["final_url"], "reason": "Слишком близок к прямому", "type": "indirect"})
            else:
                return ("reject", {"url": candidate_profile["final_url"], "reason": f"Недостаточная близость ({comparison['score']}%). {comparison['reason']}", "type": "indirect"})

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

# ========== 8. ФУНКЦИИ ДЛЯ РЕКОМЕНДАЦИЙ ==========
def recommend_messengers_platforms(our_profile, verified_direct, verified_indirect, region):
    competitors = verified_direct[:5] + verified_indirect[:5]
    comp_summary = "\n".join([f"- {c['url']} (сходство {c['score']}%)\n  Ключевые слова: {', '.join(c['shared_keywords'][:5])}" for c in competitors if c.get("shared_keywords")])
    if not comp_summary: comp_summary = "Нет данных о конкурентах."
    our_summary = summarize_profile(our_profile)
    prompt = MESSENGER_RECOMMEND_PROMPT.format(our_summary=our_summary, competitors_summary=comp_summary, region=region)
    try:
        response = call_llm_with_fallback([{"role": "user", "content": prompt}], use_tools=False, temperature=0.2, max_tokens=800)
        return response.get("content", "")
    except Exception as e:
        st.warning(f"Ошибка при рекомендации: {e}")
        return "Рекомендации не удалось сформировать."

# ========== 9. ИМИДЖЕВЫЙ АНАЛИЗ ==========
IMIDGE_PROMPT = """
Ты аналитик сайтов. Проверь сайт по URL и определи, относится ли он к "имиджевым клиентам".

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
Пояснение: (1-2 предложения)
"""

def analyze_imidj(url: str) -> str:
    profile = fetch_site_profile(url)
    if not profile.get("ok"): return f"Не удалось загрузить сайт: {profile.get('issue')}"
    summary = summarize_profile(profile)
    prompt = f"URL: {profile['final_url']}\n{IMIDGE_PROMPT}\nПрофиль сайта:\n{summary}"
    response = call_llm_with_fallback([{"role": "user", "content": prompt}], use_tools=False, temperature=0.2, max_tokens=300)
    return response.get("content", "Ошибка анализа")

# ========== 10. ФУНКЦИЯ 3 АУДИТА ==========
AUDIT_GROQ_KEYS = [GROQ_KEYS_ALL[0], GROQ_KEYS_ALL[1]]
AUDIT_GEMINI_KEYS = [GEMINI_KEYS_ALL[0], GEMINI_KEYS_ALL[1]]
audit_groq_rr = RoundRobin(AUDIT_GROQ_KEYS)
audit_gemini_rr = RoundRobin(AUDIT_GEMINI_KEYS)

def audit_call_groq(messages, temperature=0.3, max_tokens=4096):
    for attempt in range(3):
        api_key = audit_groq_rr.get()
        if not api_key: break
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.3-70b-versatile", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        try:
            response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=90)
            if response.status_code == 200: return response.json()["choices"][0]["message"]
            elif response.status_code == 429: raise Exception("Rate limit")
            elif response.status_code == 401: continue
        except: continue
    # Если не помогло, пробуем Gemini
    return audit_call_gemini(messages, temperature, max_tokens)

def audit_call_gemini(messages, temperature=0.3, max_tokens=4096):
    for attempt in range(3):
        api_key = audit_gemini_rr.get()
        if not api_key: break
        contents = []
        for msg in messages:
            role = "model" if msg["role"] == "assistant" else msg["role"]
            contents.append({"role": role, "parts": [{"text": msg["content"]}]})
        payload = {"contents": contents, "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
        url = f"{GEMINI_API_URL}?key={api_key}"
        try:
            response = requests.post(url, json=payload, timeout=90)
            if response.status_code == 200:
                data = response.json()
                return {"role": "assistant", "content": data["candidates"][0]["content"]["parts"][0]["text"]}
            elif response.status_code == 429: raise Exception("Rate limit")
            elif response.status_code == 401: continue
        except: continue
    raise Exception("Все ключи аудита не сработали")

def fetch_site_for_audit(url: str) -> dict:
    try:
        jina_url = JINA_READER_URL + url
        headers = {"Authorization": f"Bearer {JINA_3AUDIT_KEY}"}
        response = requests.get(jina_url, headers=headers, timeout=15)
        if response.status_code == 200:
            markdown = response.text
            title_match = re.search(r'# (.*?)\n', markdown)
            title = title_match.group(1) if title_match else ""
            desc_match = re.search(r'description: (.*?)\n', markdown)
            description = desc_match.group(1) if desc_match else ""
            text = re.sub(r'[#*`_\[\]\(\)]', ' ', markdown)
            text = clean_text(text)
            return {"ok": True, "url": url, "title": title, "description": description, "content": text[:8000], "error": None}
    except Exception as e:
        return {"ok": False, "url": url, "error": str(e)}
    return {"ok": False, "url": url, "error": "Не удалось загрузить"}

def run_3_audit(url: str) -> str:
    profile = fetch_site_for_audit(url)
    if not profile.get("ok"):
        return f"❌ Не удалось загрузить сайт: {profile.get('error')}"
    prompt = f"""
Твоя задача — проанализировать сайт по указанному URL.

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
URL: {url}
Тематика сайта:
Регион работы:
Потенциал целевых поисковых запросов в месяц:
Потенциальные обращения (3–5% от нижней границы):
Краткое пояснение (1–2 предложения)

Данные сайта (Markdown, первые 8000 символов):
{profile['content'][:8000]}
"""
    response = audit_call_groq([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=1500)
    return response.get("content", "Ошибка генерации аудита")

# ========== 11. НОВАЯ ФУНКЦИЯ: анализ одного сайта по 4 пунктам (включая имиджевый) ==========
def analyze_single_site(domain: str) -> dict:
    results = {"domain": domain, "status": "ok", "error": None, "data": {}}
    try:
        profile = fetch_site_profile(domain)
        if not profile.get("ok"):
            raise RuntimeError(f"Не удалось открыть сайт: {profile.get('issue', 'ошибка')}")

        # Пункт 1: коммерческий/некоммерческий, регион, масштаб
        prompt1 = f"""
Проанализируй сайт: {profile['final_url']}
На основе профиля сайта и его содержимого определи:
1. Коммерческий или некоммерческий? (если есть противоречия, укажи)
2. Страна, регион/город. Используй: блок «О компании», тексты на первом экране, раздел услуги/география, упоминания «работаем по России», кейсы, доставку, контакты как подтверждение, но не основной фактор.
3. Работает локально или по всей стране/регионально? (локально — один город/регион, регионально — несколько регионов, по всей стране — вся страна)

Верни ответ в три строки:
Статус:
Регион:
Масштаб:
"""
        response1 = call_llm_with_fallback([{"role": "user", "content": prompt1}], use_tools=False, temperature=0.2, max_tokens=300)
        lines = response1.get("content", "").strip().split("\n")
        status_line = lines[0].replace("Статус:", "").strip() if len(lines) > 0 else ""
        region_line = lines[1].replace("Регион:", "").strip() if len(lines) > 1 else ""
        scale_line = lines[2].replace("Масштаб:", "").strip() if len(lines) > 2 else ""
        results["data"]["point1"] = {"status": status_line, "region": region_line, "scale": scale_line}

        # Пункт 2: топ-10 коммерческих запросов
        prompt2 = f"""
Проанализируй сайт: {profile['final_url']}
Профиль: {summarize_profile(profile)}

Подбери 10 коммерческих поисковых запросов, которые приводят реальных клиентов, а не информационный трафик.
Требования: не использовать название региона в ключевых фразах, исключить информационные, слишком общие и высокочастотные запросы.
Упор на средне- и низкочастотные, с коммерческим интентом (купить, заказать, получить расчет, консультацию).
Запросы должны быть строго релевантны услугам/товарам сайта.
Если сайт работает локально, дай запросы для региона; если по всей стране/онлайн — запросы по стране.
Верни список из 10 фраз, каждая с примерным количеством просмотров в месяц (если нет данных — укажи оценку). Формат: "запрос — количество".
Если точных данных нет, укажи диапазон (например, "50–200") или "нет данных".
"""
        response2 = call_llm_with_fallback([{"role": "user", "content": prompt2}], use_tools=False, temperature=0.3, max_tokens=1500)
        results["data"]["point2"] = response2.get("content", "Ошибка генерации запросов")

        # Пункт 3: прямые конкуренты
        dir_cand = get_candidate_domains(domain, profile, "direct")
        dir_ver, _ = verify_competitors(profile, dir_cand, "direct")
        competitors = [c["url"] for c in dir_ver[:10]]
        if not competitors:
            prompt3 = f"""
Найди 10 предполагаемых прямых конкурентов для сайта {domain} (даже если они не идеально подходят, но хоть как-то пересекаются по тематике).
Верни только список корневых URL, по одному на строку.
"""
            try:
                resp = call_llm_with_fallback([{"role": "user", "content": prompt3}], use_tools=False, temperature=0.3, max_tokens=800)
                competitors = extract_candidate_urls(resp.get("content", ""))
            except:
                competitors = []
        results["data"]["point3"] = competitors[:10]

        # Пункт 4: мессенджеры, площадки и имиджевый анализ
        region = results["data"]["point1"].get("region", "")
        comp_list = [{"url": u, "score": 0, "shared_keywords": []} for u in competitors[:5]]
        rec_text = recommend_messengers_platforms(profile, comp_list, [], region)
        messengers = []
        platforms = []
        if rec_text:
            lines = rec_text.split("\n")
            current = None
            for line in lines:
                if "Мессенджеры" in line:
                    current = "mess"
                elif "Площадки" in line:
                    current = "plat"
                elif line.strip().startswith("-"):
                    parts = line.strip("- ").split(":")
                    if len(parts) >= 2:
                        name = parts[0].strip()
                        perc = parts[1].strip()
                        if current == "mess":
                            messengers.append((name, perc))
                        elif current == "plat":
                            platforms.append((name, perc))

        imidj_result = analyze_imidj(domain)
        results["data"]["point4"] = {
            "messengers": messengers[:5],
            "platforms": platforms[:5],
            "imidj": imidj_result
        }

    except Exception as e:
        results["status"] = "error"
        results["error"] = str(e)
    return results

# ========== 12. ИНТЕРФЕЙС STREAMLIT ==========
# Поля ввода для 5 сайтов
st.subheader("Анализ 5 сайтов")
domains = []
cols = st.columns(5)
for i in range(5):
    with cols[i]:
        domains.append(st.text_input(f"Сайт {i+1}", key=f"domain_{i}", placeholder="example.com"))

if st.button("Анализировать 5 сайтов"):
    valid_domains = [d.strip() for d in domains if d.strip()]
    if not valid_domains:
        st.warning("Введите хотя бы один домен")
    else:
        with st.spinner("Анализируем сайты..."):
            with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
                futures = {executor.submit(analyze_single_site, d): d for d in valid_domains}
                results_dict = {}
                for future in concurrent.futures.as_completed(futures):
                    domain = futures[future]
                    try:
                        res = future.result()
                        results_dict[domain] = res
                    except Exception as e:
                        results_dict[domain] = {"domain": domain, "status": "error", "error": str(e), "data": {}}

            for domain in valid_domains:
                res = results_dict.get(domain, {"status": "error", "error": "Неизвестная ошибка"})
                with st.expander(f"📊 {domain}", expanded=True):
                    if res["status"] == "error":
                        st.error(f"Ошибка: {res['error']}")
                        continue
                    data = res["data"]
                    st.markdown("**1. Коммерческий статус, регион, масштаб**")
                    st.write(f"**Статус:** {data.get('point1', {}).get('status', '—')}")
                    st.write(f"**Регион:** {data.get('point1', {}).get('region', '—')}")
                    st.write(f"**Масштаб:** {data.get('point1', {}).get('scale', '—')}")

                    st.markdown("**2. Топ-10 коммерческих запросов**")
                    st.markdown(data.get("point2", "Нет данных"))

                    st.markdown("**3. Прямые конкуренты**")
                    comps = data.get("point3", [])
                    if comps:
                        for url in comps:
                            st.markdown(f"- [{url}]({url})")
                    else:
                        st.write("Не найдено")

                    st.markdown("**4. Мессенджеры, площадки и имиджевый анализ**")
                    point4 = data.get("point4", {})
                    if point4.get("messengers"):
                        st.write("**Мессенджеры:**")
                        for name, perc in point4["messengers"]:
                            st.write(f"- {name}: {perc}")
                    else:
                        st.write("Нет данных по мессенджерам")
                    if point4.get("platforms"):
                        st.write("**Площадки:**")
                        for name, perc in point4["platforms"]:
                            st.write(f"- {name}: {perc}")
                    else:
                        st.write("Нет данных по площадкам")
                    if point4.get("imidj"):
                        st.write("**Имиджевый анализ:**")
                        st.write(point4["imidj"])

        st.success("Анализ завершён!")

# ========== 13. 3 АУДИТ (отдельный блок) ==========
st.markdown("---")
st.subheader("3 Аудит (отдельный инструмент)")
audit_url = st.text_input("Введите URL для 3 аудита", placeholder="https://example.com")
if st.button("Выполнить 3 аудит"):
    if audit_url:
        with st.spinner("Выполняем 3 аудит..."):
            res = run_3_audit(audit_url)
            st.subheader("Результат 3 аудита")
            st.markdown(res)
    else:
        st.warning("Введите URL")
