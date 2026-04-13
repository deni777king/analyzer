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

st.set_page_config(page_title="Конкурентный Анализатор | 5 сайтов", layout="wide")
st.title("Конкурентный Анализатор (5 сайтов)")

# ========== 1. КЛЮЧИ ==========
GROQ_MAIN_KEYS = [
    "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",
    "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",
    "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",
    "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",
    "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",
]
GROQ_AUDIT_KEY = "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"

EXA_API_KEYS = [
    "12fde322-d205-43a3-a2a3-56671f195f6a",
    "13c5e3ce-1017-4479-86d2-c496e5e5c092",
    "4052242f-4946-4460-9562-cc97bc6804b9",
    "d9908cda-4ddb-45b5-82f6-733ac41daa5d",
    "526c28fe-0095-492f-9c3f-7b83101bfe3d",
    "dea590ab-be52-4293-84b2-eac5ca57de5d",
    "6c88374d-ee51-498f-b669-4050832aca02",
]

JINA_3AUDIT_KEY = "jina_d3ebb125d2f24e938e21abf8d562e5498EdB-_JFA3jU8lgOtlvxURphhdBe"
JINA_READER_URL = "https://r.jina.ai/"

OPENAI_API_KEY = "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"
OPENAI_API_URL = "https://api.openai.com/v1/chat/completions"

# ========== 2. РОТАТОРЫ ==========
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

groq_main_rr = RoundRobin(GROQ_MAIN_KEYS)
exa_rr = RoundRobin(EXA_API_KEYS)
def get_groq_audit_key():
    return GROQ_AUDIT_KEY

# ========== 3. УПРАВЛЕНИЕ ОЧЕРЕДЬЮ ПОЛЬЗОВАТЕЛЕЙ (не используется в UI, оставлено для совместимости) ==========
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

# ========== 4. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========
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

# ========== 5. ЗАГРУЗКА ПРОФИЛЕЙ ==========
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

# ========== 6. ФУНКЦИИ ДЛЯ РАБОТЫ С LLM ==========
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"

def call_groq_main(messages, temperature=0.3, max_tokens=4096, retries=3):
    for attempt in range(retries):
        api_key = groq_main_rr.get()
        if not api_key:
            raise Exception("Нет доступных ключей Groq")
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {"model": "llama-3.3-70b-versatile", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
        try:
            response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=90)
            if response.status_code == 200:
                return response.json()["choices"][0]["message"]
            elif response.status_code == 429:
                wait = 2 ** attempt
                st.warning(f"Превышен лимит Groq (429), попытка {attempt+1}/{retries}, пауза {wait} сек")
                time.sleep(wait)
                continue
            else:
                raise Exception(f"Groq ошибка {response.status_code}: {response.text}")
        except requests.exceptions.RequestException as e:
            if attempt == retries - 1:
                raise Exception(f"Ошибка сети: {e}")
            time.sleep(1)
    raise Exception("Превышено количество попыток вызова Groq")

def call_groq_audit(messages, temperature=0.3, max_tokens=4096):
    api_key = get_groq_audit_key()
    if not api_key:
        raise Exception("Нет ключа Groq для аудита")
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": "llama-3.3-70b-versatile", "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=90)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]
    else:
        raise Exception(f"Groq аудит ошибка {response.status_code}")

def call_openai_with_stats(messages, temperature=0.3, max_tokens=4096):
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "gpt-4o",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens
    }
    response = requests.post(OPENAI_API_URL, json=payload, headers=headers, timeout=90)
    if response.status_code == 200:
        data = response.json()
        message = data["choices"][0]["message"]
        usage = data.get("usage", {})
        return message, usage
    else:
        raise Exception(f"OpenAI ошибка {response.status_code}: {response.text}")

# ========== 7. ПОИСК КОНКУРЕНТОВ ЧЕРЕЗ OPENAI ==========
def find_competitors_with_openai(domain: str, profile: dict):
    summary = summarize_profile(profile)
    prompt = f"""
Ты — SEO-аналитик. На основе информации о сайте найди 10 прямых конкурентов (корневые URL).

Сайт:
{summary}

Верни только список URL, по одному на строку, без лишнего текста. Убедись, что это корневые домены (https://example.com), без подпапок.
"""
    try:
        message, usage = call_openai_with_stats([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=800)
        content = message.get("content", "")
        urls = extract_candidate_urls(content)
        normalized = []
        seen = set()
        for url in urls:
            norm = normalize_root_url(url)
            dom = get_domain_key(norm)
            if dom and dom not in seen:
                seen.add(dom)
                normalized.append(norm)
        return normalized[:10], usage
    except Exception as e:
        st.warning(f"Ошибка OpenAI при поиске конкурентов: {e}")
        return [], {}

# ========== 8. ФУНКЦИИ ДЛЯ РЕКОМЕНДАЦИЙ И ИМИДЖЕВОГО АНАЛИЗА (через Groq) ==========
def recommend_messengers_platforms(our_profile, competitors, region):
    comp_summary = "\n".join([f"- {c['url']}" for c in competitors[:5]]) if competitors else "Нет данных о конкурентах."
    our_summary = summarize_profile(our_profile)
    prompt = f"""
Ты аналитик по маркетингу. На основе данных о сайте и его конкурентах определи, какие мессенджеры и площадки лучше всего подойдут для привлечения клиентов.

Данные о нашем сайте:
{our_summary}

Данные о конкурентах (до 10 сайтов):
{comp_summary}

Регион работы: {region}

Проанализируй:
- Какие мессенджеры популярны в этом регионе (Telegram, WhatsApp, Viber и др.). Исключи заблокированные в стране работы сайта.
- Какие площадки соответствуют тематике сайта (приоритет нишевым порталам, специализированным каталогам; доски объявлений типа Авито — по остаточному принципу).

Верни ответ строго в формате:
Мессенджеры (с процентами):
- Название: %
- ...
Площадки (с процентами):
- Название: %
- ...
"""
    try:
        response = call_groq_main([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=800)
        return response.get("content", "")
    except Exception as e:
        st.warning(f"Ошибка при рекомендации: {e}")
        return "Рекомендации не удалось сформировать."

def analyze_imidj(url: str, profile: dict) -> str:
    summary = summarize_profile(profile)
    prompt = f"""
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

Проанализируй сайт: {profile['final_url']}
Профиль: {summary}

Верни ответ строго в формате:
Имиджевый клиент: Да/Нет
Пояснение: (1-2 предложения)
"""
    response = call_groq_main([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=300)
    return response.get("content", "Ошибка анализа")

def get_site_type_and_geography(profile: dict) -> dict:
    prompt = f"""
Проанализируй сайт: {profile['final_url']}

1. Тип сайта: коммерческий или некоммерческий? Если есть противоречия, укажи их.
2. География бизнеса (страна, регион/город). Регион работы определяй по офферу услуг, а не по фактическому адресу офиса.
Обязательно проанализируй: блок «О компании», первый экран, раздел «Услуги / География работ», страницу доставки, упоминания («работаем по России», «по всей территории РФ», «выезд по регионам», «федеральный уровень»), кейсы и портфолио. Контакты используй только как подтверждение базового офиса.

Верни ответ в две строки:
Тип сайта:
География:
"""
    response = call_groq_main([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=300)
    lines = response.get("content", "").strip().split("\n")
    type_line = lines[0].replace("Тип сайта:", "").strip() if len(lines) > 0 else ""
    geo_line = lines[1].replace("География:", "").strip() if len(lines) > 1 else ""
    return {"type": type_line, "geography": geo_line}

def get_commercial_queries(profile: dict) -> str:
    prompt = f"""
Проанализируй сайт: {profile['final_url']}
Профиль: {summarize_profile(profile)}

Подбери 10 коммерческих поисковых запросов, которые приведут реальных клиентов (купить, заказать, получить расчет/консультацию).
Требования:
- Только коммерческий интент.
- Упор на средне- и низкочастотные запросы.
- Строгая релевантность услугам сайта.
- НЕ использовать названия регионов/городов.
- ИСКЛЮЧИТЬ информационные, обучающие, слишком общие и высокочастотные фразы.

Формат: каждая фраза с примерным количеством просмотров в месяц (ориентир на Яндекс.Вордстат для РФ/РБ или Google Ads для УЗ/КЗ). Если точных данных нет, просто укажи фразу.

Верни список из 10 строк в формате: "запрос — количество"
"""
    response = call_groq_main([{"role": "user", "content": prompt}], temperature=0.3, max_tokens=1500)
    return response.get("content", "Ошибка генерации запросов")

# ========== 9. ФУНКЦИЯ 3 АУДИТА ==========
def run_3_audit(url: str) -> str:
    try:
        jina_url = JINA_READER_URL + url
        headers = {"Authorization": f"Bearer {JINA_3AUDIT_KEY}"}
        response = requests.get(jina_url, headers=headers, timeout=15)
        if response.status_code != 200:
            return f"❌ Не удалось загрузить сайт: статус {response.status_code}"
        markdown = response.text
        text = re.sub(r'[#*`_\[\]\(\)]', ' ', markdown)
        text = clean_text(text)
        content = text[:8000]

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
{content}
"""
        response = call_groq_audit([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=1500)
        return response.get("content", "Ошибка генерации аудита")
    except Exception as e:
        return f"❌ Ошибка при выполнении 3 аудита: {e}"

# ========== 10. АНАЛИЗ ОДНОГО САЙТА ==========
def analyze_single_site(domain: str, use_openai: bool = False) -> dict:
    results = {"domain": domain, "status": "ok", "error": None, "data": {}}
    try:
        profile = fetch_site_profile(domain)
        if not profile.get("ok"):
            raise RuntimeError(f"Не удалось открыть сайт: {profile.get('issue', 'ошибка')}")

        # Пункт 1
        point1 = get_site_type_and_geography(profile)
        results["data"]["point1"] = point1
        time.sleep(0.5)

        # Пункт 2
        point2 = get_commercial_queries(profile)
        results["data"]["point2"] = point2
        time.sleep(0.5)

        # Пункт 3: конкуренты (только если use_openai)
        if use_openai:
            comp_list, usage = find_competitors_with_openai(domain, profile)
            results["data"]["point3"] = comp_list[:10]
            results["data"]["openai_usage"] = usage
        else:
            results["data"]["point3"] = []
            results["data"]["openai_usage"] = {}
        time.sleep(0.5)

        # Пункт 4: мессенджеры и площадки
        region = point1.get("geography", "")
        comp_for_rec = [{"url": u} for u in comp_list[:5]] if use_openai else []
        rec_text = recommend_messengers_platforms(profile, comp_for_rec, region)
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
        results["data"]["point4"] = {"messengers": messengers[:5], "platforms": platforms[:5]}
        time.sleep(0.5)

        # Пункт 5: имиджевый анализ
        point5 = analyze_imidj(domain, profile)
        results["data"]["point5"] = point5

    except Exception as e:
        results["status"] = "error"
        results["error"] = str(e)
    return results

# ========== 11. ИНТЕРФЕЙС STREAMLIT ==========
domains = []
cols = st.columns(5)
for i in range(5):
    with cols[i]:
        domains.append(st.text_input(f"Сайт {i+1}", key=f"domain_{i}", placeholder="example.com"))

if st.button("Анализировать 5 сайтов"):
    # Собираем валидные домены с сохранением позиции
    valid = []
    for i, d in enumerate(domains):
        if d.strip():
            valid.append((i, d.strip()))

    if not valid:
        st.warning("Введите хотя бы один домен")
    else:
        # Создаём контейнер для прогресса и результатов
        progress_container = st.empty()
        results_container = st.container()

        # Словарь для результатов
        all_results = {}

        for pos, domain in valid:
            progress_container.info(f"🔄 Анализируем {domain}...")
            use_openai = (pos == 0)  # только для поля "Сайт 1"
            try:
                res = analyze_single_site(domain, use_openai)
                all_results[domain] = res
            except Exception as e:
                all_results[domain] = {"domain": domain, "status": "error", "error": str(e), "data": {}}
            # Небольшая пауза между запросами, чтобы не перегружать API
            time.sleep(1)

        progress_container.empty()
        st.success("✅ Анализ завершён!")

        # Вывод результатов в контейнер
        with results_container:
            for pos, domain in valid:
                res = all_results.get(domain, {"status": "error", "error": "Неизвестная ошибка"})
                with st.expander(f"📊 {domain}", expanded=True):
                    if res["status"] == "error":
                        st.error(f"Ошибка: {res['error']}")
                        continue
                    data = res["data"]

                    st.markdown("**1. Тип сайта и география бизнеса**")
                    st.write(f"**Тип сайта:** {data.get('point1', {}).get('type', '—')}")
                    st.write(f"**География:** {data.get('point1', {}).get('geography', '—')}")

                    st.markdown("**2. Семантика (10 коммерческих запросов)**")
                    st.markdown(data.get("point2", "Нет данных"))

                    st.markdown("**3. Прямые конкуренты**")
                    comps = data.get("point3", [])
                    if comps:
                        for url in comps:
                            st.markdown(f"- [{url}]({url})")
                    else:
                        if pos == 0:
                            st.write("Конкуренты не найдены")
                        else:
                            st.write("Конкуренты ищутся только для сайта 1")

                    # Статистика токенов для первого сайта
                    if pos == 0 and data.get("openai_usage"):
                        usage = data["openai_usage"]
                        st.markdown("---")
                        st.markdown("**Статистика использования OpenAI:**")
                        st.write(f"- Входные токены: {usage.get('prompt_tokens', 0)}")
                        st.write(f"- Выходные токены: {usage.get('completion_tokens', 0)}")
                        st.write(f"- Всего токенов: {usage.get('total_tokens', 0)}")

                    st.markdown("**4. Мессенджеры и площадки для привлечения клиентов**")
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

                    st.markdown("**5. Имиджевый анализ**")
                    st.write(data.get("point5", "Нет данных"))

# ========== 12. КНОПКА 3 АУДИТА ==========
st.markdown("---")
st.subheader("3 Аудит (отдельный пул Groq)")
audit_url = st.text_input("Введите URL для 3 аудита", key="audit_input", placeholder="https://...")
if st.button("Выполнить 3 аудит"):
    if audit_url:
        with st.spinner("Выполняем 3 аудит..."):
            res = run_3_audit(audit_url)
            st.subheader("Результат 3 аудита")
            st.markdown(res)
