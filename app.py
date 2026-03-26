import json
import math
import re
import threading
import time
import random
import concurrent.futures
from collections import Counter, deque
from urllib.parse import urlparse
from datetime import datetime

import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup

st.set_page_config(page_title="Конкурентный Анализатор | 3 Аудит", layout="wide")
st.title("Конкурентный Анализатор")

# ============================================================
# 1. НАСТРОЙКА API-КЛЮЧЕЙ (НОВЫЕ)
# ============================================================

# --- Mistral (для линий 1 и 2) ---
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

# --- Exa (для линий 1 и 2) ---
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

# --- Groq (все 6 ключей) ---
GROQ_KEYS_ALL = [
    "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",
    "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",
    "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",
    "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",
    "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",
    "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",
]

# --- Gemini (5 ключей) ---
GEMINI_KEYS_ALL = [
    "AIzaSyCIUNviKfWReJZXSx0lmGhZwLR_3oq0mv0",
    "AIzaSyBELdB8pwTRGAHpThWyPhIo8Y55bR34u74",
    "AIzaSyCVris8gA-EoRXojE1eWvP1GJGK6uebgCk",
    "AIzaSyAJP67w_9Z5xmSDVwcE_2L5Rz-v4ktRJSo",
    "AIzaSyDdjbQ47TUjsbUigDgctHUnSJ-BrXvvvkQ",
]

# --- Распределение по линиям (согласно ТЗ) ---
# Линия 1: 4/4 Exa/Mistral, 1/1 Groq/Gemini
GROQ_KEYS_LINE1 = [GROQ_KEYS_ALL[0]]
GEMINI_KEYS_LINE1 = [GEMINI_KEYS_ALL[0]]
# Линия 2: 3/3 Exa/Mistral, 2/2 Groq/Gemini
GROQ_KEYS_LINE2 = [GROQ_KEYS_ALL[1], GROQ_KEYS_ALL[2]]
GEMINI_KEYS_LINE2 = [GEMINI_KEYS_ALL[1], GEMINI_KEYS_ALL[2]]
# Линия 3: без Exa и Mistral, только 3/3 Groq/Gemini
GROQ_KEYS_LINE3 = [GROQ_KEYS_ALL[3], GROQ_KEYS_ALL[4], GROQ_KEYS_ALL[5]]
GEMINI_KEYS_LINE3 = [GEMINI_KEYS_ALL[3], GEMINI_KEYS_ALL[4], GEMINI_KEYS_ALL[5]]

# --- Jina для 3 Аудита (один ключ) ---
JINA_3AUDIT_KEY = "jina_d3ebb125d2f24e938e21abf8d562e5498EdB-_JFA3jU8lgOtlvxURphhdBe"
JINA_READER_URL = "https://r.jina.ai/"

# Конфигурация линий
LINE_CONFIG = {
    1: {
        "mistral": MISTRAL_KEYS_LINE1,
        "exa": EXA_KEYS_LINE1,
        "groq": GROQ_KEYS_LINE1,
        "gemini": GEMINI_KEYS_LINE1,
    },
    2: {
        "mistral": MISTRAL_KEYS_LINE2,
        "exa": EXA_KEYS_LINE2,
        "groq": GROQ_KEYS_LINE2,
        "gemini": GEMINI_KEYS_LINE2,
    },
    3: {
        "mistral": [],
        "exa": [],
        "groq": GROQ_KEYS_LINE3,
        "gemini": GEMINI_KEYS_LINE3,
    }
}

# Round-robin для Groq/Gemini внутри линии
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

# Текущая активная линия (изменяется при ошибках)
current_line = 1
line_rr = {
    1: {"groq": RoundRobin(LINE_CONFIG[1]["groq"]),
        "gemini": RoundRobin(LINE_CONFIG[1]["gemini"])},
    2: {"groq": RoundRobin(LINE_CONFIG[2]["groq"]),
        "gemini": RoundRobin(LINE_CONFIG[2]["gemini"])},
    3: {"groq": RoundRobin(LINE_CONFIG[3]["groq"]),
        "gemini": RoundRobin(LINE_CONFIG[3]["gemini"])},
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

# ============================================================
# 2. УПРАВЛЕНИЕ ОЧЕРЕДЬЮ ПОЛЬЗОВАТЕЛЕЙ
# ============================================================
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

# ============================================================
# 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (парсинг, токенизация, сравнение)
# ============================================================
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
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
    if not raw:
        return []
    raw = re.sub(r"^[\-\s]+", "", raw)
    raw = re.sub(r"[\s/]+$", "", raw)
    raw = raw.replace("http://", "").replace("https://", "")
    raw = raw.replace("www.", "")
    domain = raw.split("/", 1)[0]
    variants = [
        f"https://{domain}",
        f"https://www.{domain}",
        f"http://{domain}",
        f"http://www.{domain}",
    ]
    return list(dict.fromkeys(variants))

def normalize_root_url(value: str) -> str:
    parsed = urlparse(value if value.startswith(("http://", "https://")) else f"https://{value}")
    netloc = parsed.netloc or parsed.path
    netloc = netloc.lower().strip()
    netloc = netloc.replace("http://", "").replace("https://", "")
    netloc = netloc.rstrip("/")
    return f"https://{netloc}"

def get_domain_key(value: str) -> str:
    parsed = urlparse(value if value.startswith(("http://", "https://")) else f"https://{value}")
    netloc = (parsed.netloc or parsed.path).lower().strip()
    netloc = netloc.replace("http://", "").replace("https://", "")
    netloc = netloc.rstrip("/")
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc

def clean_text(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "")
    return text.strip()

def count_internal_links(soup: BeautifulSoup, domain: str) -> int:
    count = 0
    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
            continue
        href_domain = get_domain_key(href) if href.startswith(("http://", "https://")) else domain
        if href_domain == domain:
            count += 1
    return count

def tokenize(text: str) -> list[str]:
    prepared = clean_text(text.lower().replace("ё", "е"))
    tokens = re.findall(r"[a-zа-я][a-zа-я0-9\-]{1,}", prepared)
    result = []
    for token in tokens:
        if token in STOPWORDS:
            continue
        if token.isdigit():
            continue
        if len(token) <= 2:
            continue
        result.append(token)
    return result

def jaccard_similarity(first: set[str], second: set[str]) -> float:
    if not first or not second:
        return 0.0
    union = first | second
    if not union:
        return 0.0
    return len(first & second) / len(union)

def cosine_similarity(counter_a: Counter, counter_b: Counter) -> float:
    if not counter_a or not counter_b:
        return 0.0
    shared = set(counter_a) & set(counter_b)
    numerator = sum(counter_a[token] * counter_b[token] for token in shared)
    norm_a = math.sqrt(sum(v * v for v in counter_a.values()))
    norm_b = math.sqrt(sum(v * v for v in counter_b.values()))
    if not norm_a or not norm_b:
        return 0.0
    return numerator / (norm_a * norm_b)

def compare_profiles(our_profile: dict, candidate_profile: dict) -> dict:
    our_counter = Counter(our_profile.get("token_counter", {}))
    candidate_counter = Counter(candidate_profile.get("token_counter", {}))

    our_keywords = our_profile.get("keywords", [])
    candidate_keywords = candidate_profile.get("keywords", [])
    shared_keywords = [kw for kw in our_keywords if kw in candidate_keywords][:10]

    our_head = set(tokenize(" ".join([
        our_profile.get("title", ""),
        our_profile.get("description", ""),
        " ".join(our_profile.get("headings", [])),
    ])))
    candidate_head = set(tokenize(" ".join([
        candidate_profile.get("title", ""),
        candidate_profile.get("description", ""),
        " ".join(candidate_profile.get("headings", [])),
    ])))

    body_cosine = cosine_similarity(our_counter, candidate_counter)
    keyword_overlap = 0.0
    if our_keywords and candidate_keywords:
        keyword_overlap = len(set(shared_keywords)) / max(1, min(len(our_keywords), len(candidate_keywords)))
    header_overlap = jaccard_similarity(our_head, candidate_head)

    our_text_len = max(our_profile.get("text_length", 0), 1)
    cand_text_len = max(candidate_profile.get("text_length", 0), 1)
    text_ratio = min(our_text_len, cand_text_len) / max(our_text_len, cand_text_len)

    our_links = max(our_profile.get("internal_links", 0), 1)
    cand_links = max(candidate_profile.get("internal_links", 0), 1)
    link_ratio = min(our_links, cand_links) / max(our_links, cand_links)
    scale_score = 0.6 * text_ratio + 0.4 * link_ratio

    thematic_score = 0.55 * body_cosine + 0.30 * keyword_overlap + 0.15 * header_overlap
    final_score = round(((0.8 * thematic_score) + (0.2 * scale_score)) * 100, 1)

    relevance = "низкая"
    if final_score >= 40:
        relevance = "высокая"
    elif final_score >= 25:
        relevance = "средняя"

    scale_comment = "похожий масштаб"
    if scale_score < 0.25:
        scale_comment = "масштаб заметно отличается"
    elif scale_score < 0.45:
        scale_comment = "масштаб отличается"

    reason = (
        f"Совпавшие ключи: {', '.join(shared_keywords[:6])}."
        if shared_keywords
        else "Мало совпадающих тематических терминов."
    )

    return {
        "score": final_score,
        "relevance": relevance,
        "body_cosine": round(body_cosine, 3),
        "keyword_overlap": round(keyword_overlap, 3),
        "header_overlap": round(header_overlap, 3),
        "scale_score": round(scale_score, 3),
        "scale_comment": scale_comment,
        "shared_keywords": shared_keywords,
        "reason": reason,
    }

def classify_competitor(comparison: dict) -> str | None:
    score = comparison["score"]
    shared_count = len(comparison["shared_keywords"])
    body_cosine = comparison["body_cosine"]
    header_overlap = comparison["header_overlap"]

    if score >= 30 and shared_count >= 2 and (body_cosine >= 0.15 or header_overlap >= 0.12):
        return "direct"
    if score >= 18 and shared_count >= 1 and (body_cosine >= 0.08 or header_overlap >= 0.07):
        return "indirect"
    return None

def is_blocked_domain(domain: str) -> bool:
    domain = get_domain_key(domain)
    if domain in MARKETPLACE_BLOCKLIST:
        return True
    return any(domain.endswith(f".{item}") for item in MARKETPLACE_BLOCKLIST)

def summarize_profile(profile: dict) -> str:
    headings = "; ".join(profile.get("headings", [])[:4]) or "нет данных"
    keywords = ", ".join(profile.get("keywords", [])[:12]) or "нет данных"
    snippet = profile.get("snippet", "")[:1200] or "нет данных"
    return (
        f"Домен: {profile.get('domain', '')}\n"
        f"URL: {profile.get('final_url', '')}\n"
        f"Title: {profile.get('title', '') or 'нет данных'}\n"
        f"Description: {profile.get('description', '') or 'нет данных'}\n"
        f"Headings: {headings}\n"
        f"Keywords: {keywords}\n"
        f"Фрагмент текста: {snippet}"
    )

def extract_candidate_urls(text: str) -> list[str]:
    if not text:
        return []
    pattern = re.compile(
        r"(?:https?://)?(?:www\.)?[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)+(?:/[a-zA-Z0-9_./?=&%-]*)?"
    )
    candidates = []
    seen = set()
    for raw in pattern.findall(text):
        url = normalize_root_url(raw)
        domain = get_domain_key(url)
        if "." not in domain:
            continue
        if domain in seen:
            continue
        seen.add(domain)
        candidates.append(url)
    return candidates

def dedupe_urls(urls: list[str]) -> list[str]:
    result = []
    seen = set()
    for raw in urls:
        url = normalize_root_url(raw)
        domain = get_domain_key(url)
        if not domain or domain in seen:
            continue
        seen.add(domain)
        result.append(url)
    return result

def exclude_domains(urls: list[str], excluded_domains: set[str]) -> list[str]:
    result = []
    seen = set()
    for raw in urls:
        url = normalize_root_url(raw)
        domain = get_domain_key(url)
        if not domain or domain in excluded_domains or domain in seen:
            continue
        seen.add(domain)
        result.append(url)
    return result

# ============================================================
# 4. ФУНКЦИИ ДЛЯ ПОЛУЧЕНИЯ ПРОФИЛЯ САЙТА (с Jina)
# ============================================================
# Стандартный парсинг (используется везде, кроме 3 аудита)
@st.cache_data(show_spinner=False, ttl=3600)
def fetch_site_profile(url_or_domain: str) -> dict:
    variants = build_url_variants(url_or_domain)
    last_error = "Не удалось открыть сайт"
    for candidate in variants:
        # Сначала попробуем Jina с обычной ротацией? В ТЗ Jina только для 3 аудита, но можно оставить как есть.
        # Оставим старый парсинг как основной, так как ключи Jina у нас только для аудита.
        try:
            response = requests.get(candidate, headers=REQUEST_HEADERS, timeout=15, allow_redirects=True)
            status_code = response.status_code
            content_type = response.headers.get("Content-Type", "")

            if status_code >= 400:
                last_error = f"HTTP {status_code}"
                continue

            if "html" not in content_type and "text" not in content_type:
                last_error = f"Неподдерживаемый Content-Type: {content_type}"
                continue

            html = response.text
            soup = BeautifulSoup(html, "html.parser")
            for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
                tag.decompose()

            title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
            description = clean_text(
                (
                    soup.find("meta", attrs={"name": "description"})
                    or soup.find("meta", attrs={"property": "og:description"})
                    or {}
                ).get("content", "")
            )
            headings = [
                clean_text(tag.get_text(" ", strip=True))
                for tag in soup.find_all(["h1", "h2"], limit=8)
                if clean_text(tag.get_text(" ", strip=True))
            ]
            text = clean_text(soup.get_text(" ", strip=True))
            text = text[:15000]
            final_url = response.url
            final_domain = get_domain_key(final_url)
            internal_links = count_internal_links(soup, final_domain)

            if len(text) < 180:
                last_error = "Сайт почти пустой"
                continue

            weighted_text = " ".join(
                [title] * 6 + [description] * 5 + headings * 3 + [text]
            )
            token_counter = Counter(tokenize(weighted_text))
            keywords = [token for token, _ in token_counter.most_common(25)]

            return {
                "ok": True,
                "live": True,
                "requested_url": candidate,
                "final_url": normalize_root_url(final_url),
                "domain": final_domain,
                "title": title,
                "description": description,
                "headings": headings[:5],
                "text": text,
                "snippet": text[:1500],
                "status_code": status_code,
                "internal_links": internal_links,
                "text_length": len(text),
                "keywords": keywords,
                "token_counter": dict(token_counter),
                "issue": "",
            }
        except Exception as exc:
            last_error = str(exc)

    return {
        "ok": False,
        "live": False,
        "requested_url": normalize_root_url(url_or_domain),
        "final_url": normalize_root_url(url_or_domain),
        "domain": get_domain_key(url_or_domain),
        "title": "",
        "description": "",
        "headings": [],
        "text": "",
        "snippet": "",
        "status_code": None,
        "internal_links": 0,
        "text_length": 0,
        "keywords": [],
        "token_counter": {},
        "issue": last_error,
    }

@st.cache_data(show_spinner=False, ttl=3600)
def browse_page(url: str) -> str:
    profile = fetch_site_profile(url)
    payload = {
        "live": profile["live"],
        "url": profile["final_url"],
        "domain": profile["domain"],
        "title": profile["title"],
        "description": profile["description"],
        "headings": profile["headings"],
        "keywords": profile["keywords"][:12],
        "snippet": profile["snippet"],
        "issue": profile["issue"],
    }
    return json.dumps(payload, ensure_ascii=False)

# ============================================================
# 5. ФУНКЦИИ ДЛЯ РАБОТЫ С LLM (с переключением линий)
# ============================================================
tools = [
    {
        "type": "function",
        "function": {
            "name": "browse_page",
            "description": (
                "Проверить сайт по URL и вернуть краткий профиль страницы: живая ли она, тема, заголовок, "
                "описание, ключевые слова и краткий фрагмент текста."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    }
]

GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"

def call_mistral(messages, use_tools=False, temperature=0.3, max_tokens=4096):
    keys = get_mistral_keys()
    if not keys:
        raise Exception("Нет доступных ключей Mistral в текущей линии")
    for api_key in keys:
        try:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": "mistral-small-latest",
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if use_tools:
                payload["tools"] = tools
            response = requests.post("https://api.mistral.ai/v1/chat/completions", json=payload, headers=headers, timeout=90)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]
            elif response.status_code == 429:
                raise Exception("Rate limit")
            else:
                continue
        except Exception:
            continue
    raise Exception("Все ключи Mistral в текущей линии не сработали")

def call_groq(messages, temperature=0.3, max_tokens=4096):
    rr = line_rr[current_line]["groq"]
    api_key = rr.get()
    if not api_key:
        raise Exception("Нет доступных ключей Groq в текущей линии")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=90)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]
    elif response.status_code == 429:
        raise Exception("Rate limit")
    else:
        raise Exception(f"Groq ошибка {response.status_code}")

def call_gemini(messages, temperature=0.3, max_tokens=4096):
    rr = line_rr[current_line]["gemini"]
    api_key = rr.get()
    if not api_key:
        raise Exception("Нет доступных ключей Gemini в текущей линии")
    contents = []
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else msg["role"]
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    url = f"{GEMINI_API_URL}?key={api_key}"
    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    response = requests.post(url, json=payload, timeout=90)
    if response.status_code == 200:
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return {"role": "assistant", "content": text}
    elif response.status_code == 429:
        raise Exception("Rate limit")
    else:
        raise Exception(f"Gemini ошибка {response.status_code}")

def call_llm_with_fallback(messages, use_tools=False, temperature=0.3, max_tokens=4096):
    if use_tools:
        # Только Mistral поддерживает tools
        try:
            return call_mistral(messages, use_tools=True, temperature=temperature, max_tokens=max_tokens)
        except Exception as e:
            if "Rate limit" in str(e) and switch_line():
                return call_llm_with_fallback(messages, use_tools, temperature, max_tokens)
            raise
    else:
        # Пробуем всех по очереди с переключением линии при лимитах
        providers = [
            ("Mistral", call_mistral),
            ("Gemini", call_gemini),
            ("Groq", call_groq),
        ]
        for name, func in providers:
            try:
                return func(messages, temperature=temperature, max_tokens=max_tokens)
            except Exception as e:
                if "Rate limit" in str(e):
                    # Пробуем переключить линию и повторить с новыми ключами
                    if switch_line():
                        return call_llm_with_fallback(messages, use_tools, temperature, max_tokens)
                    else:
                        raise
                continue
        raise Exception("Все провайдеры не смогли обработать запрос")

# ============================================================
# 6. ПОИСК КОНКУРЕНТОВ (Exa)
# ============================================================
def search_exa(query: str, num_results: int = 15) -> list[str]:
    keys = get_exa_keys()
    if not keys:
        raise Exception("Нет ключей Exa в текущей линии")
    for api_key in keys:
        try:
            url = "https://api.exa.ai/search"
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "query": query,
                "type": "neural",
                "numResults": num_results,
                "contents": {"text": False}
            }
            response = requests.post(url, json=payload, headers=headers, timeout=30)
            if response.status_code == 200:
                data = response.json()
                urls = [normalize_root_url(r["url"]) for r in data.get("results", [])]
                return dedupe_urls(urls)
            elif response.status_code == 429:
                continue
        except Exception:
            continue
    raise Exception("Все ключи Exa в текущей линии не сработали")

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

# ============================================================
# 7. ПРОВЕРКА КОНКУРЕНТОВ (с LLM-фильтром)
# ============================================================
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

def ensure_min_indirect(domain, our_profile, direct_verified, indirect_verified, rejected):
    if len(indirect_verified) >= 5:
        return indirect_verified, rejected
    excluded = {our_profile.get("domain", "")}
    excluded.update(item["domain"] for item in direct_verified)
    excluded.update(item["domain"] for item in indirect_verified if item.get("domain"))
    extra = get_candidate_domains(domain, our_profile, "indirect", excluded)
    extra_ver, extra_rej = verify_competitors(our_profile, extra, "indirect")
    existing = {item["domain"] for item in indirect_verified}
    for item in extra_ver:
        if item["domain"] not in existing:
            indirect_verified.append(item)
            existing.add(item["domain"])
    rejected.extend(extra_rej)
    indirect_verified.sort(key=lambda x: x["score"], reverse=True)
    return indirect_verified, rejected

# ============================================================
# 8. ФУНКЦИИ ДЛЯ ЧЕРНОВИКА И ФИНАЛЬНОГО ОТЧЁТА
# ============================================================
SITE_SUMMARY_PROMPT = """
Ты аналитик сайтов. Ниже профиль нашего сайта:
{site_summary}
Проанализируй сайт и дай краткую оценку по пунктам:
1. Коммерческий или некоммерческий? (если есть противоречия, укажи)
2. Страна, регион/город
3. По всей стране или локально?
4. Топ-10 ключевых слов (только коммерческие, без региона, приоритет средне- и низкочастотным)
6. Мессенджеры и площадки для рекламы
Отвечай кратко, строго по структуре.
"""

DIRECT_CANDIDATE_PROMPT = """
Ты ищешь кандидатов в ТОЧНЫЕ (прямые) конкуренты для сайта {domain}.
Профиль нашего сайта: {site_summary}
Правила: используй browse_page для каждого кандидата, исключай маркетплейсы, стремись к минимум 5. Верни только список корневых URL.
"""

INDIRECT_CANDIDATE_PROMPT = """
Ты ищешь кандидатов в КОСВЕННЫЕ конкуренты для сайта {domain}.
Профиль нашего сайта: {site_summary}
Правила: используй browse_page, исключай прямых конкурентов и маркетплейсы, стремись к минимум 5. Верни только список корневых URL.
"""

FINAL_REPORT_PROMPT = """
Ты аналитик сайтов. Используй только данные ниже и не выдумывай новые сайты.

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

Не добавляй лишнего. Если информации недостаточно – укажи. Ответ оформляй в виде списка с явными номерами пунктов.
"""

def get_site_outline(our_profile):
    prompt = SITE_SUMMARY_PROMPT.format(site_summary=summarize_profile(our_profile))
    response = call_llm_with_fallback([{"role": "user", "content": prompt}], use_tools=False, temperature=0.2, max_tokens=1200)
    return response.get("content", "")

def build_final_report(our_profile, site_outline, verified_direct, verified_indirect, rejected):
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
    response = call_llm_with_fallback([{"role": "user", "content": prompt}], use_tools=False, temperature=0.25, max_tokens=3000)
    return response.get("content", "")

def run_full_analysis(domain):
    our = fetch_site_profile(domain)
    if not our.get("ok"):
        raise RuntimeError(f"Не удалось открыть наш сайт: {our.get('issue', 'ошибка')}")
    outline = get_site_outline(our)
    dir_cand = get_candidate_domains(domain, our, "direct")
    ind_cand = get_candidate_domains(domain, our, "indirect")
    if not dir_cand and not ind_cand:
        raise RuntimeError("Не удалось получить кандидатов")
    dir_ver, dir_rej = verify_competitors(our, dir_cand, "direct")
    dir_doms = {d["domain"] for d in dir_ver}
    ind_cand = exclude_domains(ind_cand, dir_doms)
    ind_ver, ind_rej = verify_competitors(our, ind_cand, "indirect")
    rej = dir_rej + ind_rej
    ind_ver, rej = ensure_min_indirect(domain, our, dir_ver, ind_ver, rej)
    dir_ver = dir_ver[:10]
    ind_ver = ind_ver[:10]
    report = build_final_report(our, outline, dir_ver, ind_ver, rej)
    return report, our, dir_ver, ind_ver, rej

def rerun_competitors_only(domain, our_profile):
    # Принудительно используем линию 3 (только Groq/Gemini)
    global current_line
    saved_line = current_line
    current_line = 3
    try:
        dir_cand = get_candidate_domains(domain, our_profile, "direct")
        ind_cand = get_candidate_domains(domain, our_profile, "indirect")
        dir_ver, dir_rej = verify_competitors(our_profile, dir_cand, "direct")
        dir_doms = {d["domain"] for d in dir_ver}
        ind_cand = exclude_domains(ind_cand, dir_doms)
        ind_ver, ind_rej = verify_competitors(our_profile, ind_cand, "indirect")
        rej = dir_rej + ind_rej
        ind_ver, rej = ensure_min_indirect(domain, our_profile, dir_ver, ind_ver, rej)
        return dir_ver[:10], ind_ver[:10], rej
    finally:
        current_line = saved_line

# ============================================================
# 9. ИМИДЖЕВЫЙ АНАЛИЗ (отдельная кнопка)
# ============================================================
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
    if not profile.get("ok"):
        return f"Не удалось загрузить сайт: {profile.get('issue')}"
    summary = summarize_profile(profile)
    prompt = f"URL: {profile['final_url']}\n{IMIDGE_PROMPT}\nПрофиль сайта:\n{summary}"
    response = call_llm_with_fallback([{"role": "user", "content": prompt}], use_tools=False, temperature=0.2, max_tokens=300)
    return response.get("content", "Ошибка анализа")

# ============================================================
# 10. 3 АУДИТ (отдельная кнопка, отдельный пул ключей)
# ============================================================
AUDIT_GROQ_KEYS = [GROQ_KEYS_ALL[0], GROQ_KEYS_ALL[1]]
AUDIT_GEMINI_KEYS = [GEMINI_KEYS_ALL[0], GEMINI_KEYS_ALL[1]]
audit_groq_rr = RoundRobin(AUDIT_GROQ_KEYS)
audit_gemini_rr = RoundRobin(AUDIT_GEMINI_KEYS)

def audit_call_groq(messages, temperature=0.3, max_tokens=4096):
    api_key = audit_groq_rr.get()
    if not api_key:
        raise Exception("Нет ключей Groq для аудита")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "llama-3.3-70b-versatile",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=90)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]
    else:
        raise Exception(f"Ошибка Groq аудит: {response.status_code}")

def audit_call_gemini(messages, temperature=0.3, max_tokens=4096):
    api_key = audit_gemini_rr.get()
    if not api_key:
        raise Exception("Нет ключей Gemini для аудита")
    contents = []
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else msg["role"]
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    url = f"{GEMINI_API_URL}?key={api_key}"
    payload = {
        "contents": contents,
        "generationConfig": {
            "temperature": temperature,
            "maxOutputTokens": max_tokens,
        },
    }
    response = requests.post(url, json=payload, timeout=90)
    if response.status_code == 200:
        data = response.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        return {"role": "assistant", "content": text}
    else:
        raise Exception(f"Ошибка Gemini аудит: {response.status_code}")

def audit_call_with_fallback(messages, temperature=0.3, max_tokens=4096):
    try:
        return audit_call_groq(messages, temperature, max_tokens)
    except:
        try:
            return audit_call_gemini(messages, temperature, max_tokens)
        except Exception as e:
            raise Exception(f"Аудит не удался: {e}")

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
            return {
                "ok": True,
                "url": url,
                "title": title,
                "description": description,
                "content": text[:8000],
                "error": None
            }
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
    response = audit_call_with_fallback([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=1500)
    return response.get("content", "Ошибка генерации аудита")

# ============================================================
# 11. ОТОБРАЖЕНИЕ РЕЗУЛЬТАТОВ
# ============================================================
def render_best_competitors(verified_direct, verified_indirect, limit=10):
    combined = verified_direct + verified_indirect
    combined.sort(key=lambda x: x["score"], reverse=True)
    if not combined:
        st.info("Нет проверенных конкурентов.")
        return
    st.subheader("Лучшие конкуренты (по релевантности)")
    for i, item in enumerate(combined[:limit], 1):
        url = item["url"]
        domain = item.get("domain") or get_domain_key(url)
        safe_domain = json.dumps(domain, ensure_ascii=False)
        safe_url = json.dumps(url, ensure_ascii=False)
        html = f"""
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 12px; border:1px solid #e5e7eb; border-radius:10px; margin-bottom:8px;">
            <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                <span style="font-weight:600;margin-right:8px;">{i}.</span>
                <a href={safe_url} target="_blank" style="text-decoration:none;color:#2563eb;">{domain}</a>
                <span style="margin-left:8px; color:#6b7280;">({item['score']}%)</span>
            </div>
            <button onclick='navigator.clipboard.writeText({safe_domain})' style="border:1px solid #d1d5db; border-radius:8px; padding:6px 10px;">Копировать</button>
        </div>
        """
        components.html(html, height=64)

def build_validation_rows(verified_direct, verified_indirect):
    all_ver = verified_direct + verified_indirect
    all_ver.sort(key=lambda x: x["score"], reverse=True)
    rows = []
    for item in all_ver[:10]:
        rows.append({
            "URL": item["url"],
            "Тип": "Точный" if item.get("competitor_type") == "direct" else "Косвенный",
            "Статус": "OK",
            "Релевантность": f"{item['score']}% ({item['relevance']})",
            "Совпадения": ", ".join(item.get("shared_keywords", [])[:5]) or "—",
            "Комментарий": item.get("scale_comment", ""),
        })
    return rows

def render_validation_table(verified_direct, verified_indirect):
    rows = build_validation_rows(verified_direct, verified_indirect)
    if not rows:
        return
    st.subheader("Топ-10 проверенных конкурентов")
    st.dataframe(rows, use_container_width=True, hide_index=True)

# ============================================================
# 12. ИНТЕРФЕЙС STREAMLIT
# ============================================================
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

# Основной анализ
if st.button("Провести конкурентный анализ"):
    if not domain:
        st.warning("Введи домен")
    else:
        if not queue.is_active(user_id):
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
            else:
                st.info("🔍 Начинаем анализ...")
        with st.spinner("Анализирую..."):
            try:
                res, prof, dir_ver, ind_ver, rej = run_full_analysis(domain)
                st.session_state.result = res
                st.session_state.our_profile = prof
                st.session_state.verified_direct_competitors = dir_ver
                st.session_state.verified_indirect_competitors = ind_ver
                st.session_state.rejected_competitors = rej
                st.session_state.last_domain = domain
            except Exception as e:
                st.error(f"Ошибка: {e}")
        queue.release()

# Перепроверка (только Groq/Gemini)
if st.button("Перепроверка (только Groq/Gemini)"):
    if not domain:
        st.warning("Введи домен")
    else:
        if not queue.is_active(user_id):
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
            else:
                st.info("🔍 Начинаем перепроверку...")
        with st.spinner("Перепроверяю (линия 3)..."):
            try:
                prof = st.session_state.our_profile
                if prof is None:
                    st.error("Сначала проведите основной анализ")
                else:
                    dir_ver, ind_ver, rej = rerun_competitors_only(domain, prof)
                    st.session_state.verified_direct_competitors = dir_ver
                    st.session_state.verified_indirect_competitors = ind_ver
                    st.session_state.rejected_competitors = rej
                    st.success("Перепроверка завершена")
            except Exception as e:
                st.error(f"Ошибка: {e}")
        queue.release()

# Имиджевый анализ
st.sidebar.header("Дополнительные проверки")
imidj_url = st.sidebar.text_input("URL для имиджевого анализа", key="imidj_url")
if st.sidebar.button("Проверить имиджевость"):
    if imidj_url:
        with st.spinner("Анализируем..."):
            result = analyze_imidj(imidj_url)
            st.sidebar.subheader("Результат имиджевого анализа")
            st.sidebar.markdown(result)
    else:
        st.sidebar.warning("Введите URL")

# 3 Аудит
audit_url = st.sidebar.text_input("URL для 3 аудита", key="audit_url")
if st.sidebar.button("3 Аудит (отдельный пул ключей)"):
    if audit_url:
        with st.spinner("Выполняем 3 аудит..."):
            result = run_3_audit(audit_url)
            st.sidebar.subheader("Результат 3 аудита")
            st.sidebar.markdown(result)
    else:
        st.sidebar.warning("Введите URL")

# Отображение результатов
if st.session_state.result:
    st.subheader("Результат анализа")
    st.markdown(st.session_state.result, unsafe_allow_html=True)
    render_best_competitors(
        st.session_state.verified_direct_competitors,
        st.session_state.verified_indirect_competitors,
        limit=10
    )
    render_validation_table(
        st.session_state.verified_direct_competitors,
        st.session_state.verified_indirect_competitors,
    )
