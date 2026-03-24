import json
import math
import os
import re
import threading
import concurrent.futures
from collections import Counter
from urllib.parse import urlparse

import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup

st.set_page_config(page_title="Конкурентный Анализатор", layout="wide")
st.title("Конкурентный Анализатор")

# ===== НАСТРОЙКА API-КЛЮЧЕЙ =====
MISTRAL_API_KEYS = [
    "S7ZtbybPJ6eVtI6SXpLrWTxZg5ScQSPR",
    "RciSeumN9OBaOuhUNcQ0ynbjKSVkw6kF",
    "jMinLgK9DSNsMJ6gSQM7yATFNRfoOvxx",
    "hzCXFKU2QmiHcVN7nbuHWSDKCkqW29MJ",
]

MISTRAL_MODEL = "mistral-small-latest"
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

# Потокобезопасный счётчик для round-robin
_api_key_lock = threading.Lock()
_api_key_index = 0

def get_next_api_key() -> str:
    """Возвращает следующий API-ключ по кругу (потокобезопасно)."""
    global _api_key_index
    if not MISTRAL_API_KEYS:
        raise RuntimeError("Нет ни одного API-ключа")
    with _api_key_lock:
        key = MISTRAL_API_KEYS[_api_key_index % len(MISTRAL_API_KEYS)]
        _api_key_index += 1
        return key

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

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ==========

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_site_profile(url_or_domain: str) -> dict:
    variants = build_url_variants(url_or_domain)
    last_error = "Не удалось открыть сайт"

    for candidate in variants:
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
                [title] * 4 + [description] * 3 + headings * 2 + [text]
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
    norm_a = math.sqrt(sum(value * value for value in counter_a.values()))
    norm_b = math.sqrt(sum(value * value for value in counter_b.values()))
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

    our_text_length = max(our_profile.get("text_length", 0), 1)
    candidate_text_length = max(candidate_profile.get("text_length", 0), 1)
    text_ratio = min(our_text_length, candidate_text_length) / max(our_text_length, candidate_text_length)

    our_links = max(our_profile.get("internal_links", 0), 1)
    candidate_links = max(candidate_profile.get("internal_links", 0), 1)
    link_ratio = min(our_links, candidate_links) / max(our_links, candidate_links)
    scale_score = (0.6 * text_ratio) + (0.4 * link_ratio)

    thematic_score = (0.55 * body_cosine) + (0.30 * keyword_overlap) + (0.15 * header_overlap)
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

    if score >= 24 and (shared_count >= 3 or body_cosine >= 0.12 or header_overlap >= 0.10):
        return "direct"
    if score >= 12 and (shared_count >= 1 or body_cosine >= 0.06 or header_overlap >= 0.05):
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


# ========== ИЗМЕНЁННЫЕ ФУНКЦИИ С ПАРАЛЛЕЛЬНОЙ ОБРАБОТКОЙ ==========

tools = [
    {
        "type": "function",
        "function": {
            "name": "browse_page",
            "description": (
                "Проверить сайт по URL и вернуть краткий профиль страницы: живая ли она, тема, заголовок, "
                "описание, ключевые слова и краткий фрагмент текста. Используй для каждого кандидата "
                "перед тем, как включать его в ответ."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    }
]

# ===== УЛУЧШЕННЫЕ ПРОМТЫ =====

SITE_SUMMARY_PROMPT = """
Ты аналитик сайтов. Ниже профиль нашего сайта:

{site_summary}

Сделай краткую оценку по пунктам 1-4 и 6. Не выдумывай недоступные факты. Если уверенности нет — прямо укажи, что это предположение или данных недостаточно.

Структура ответа строго такая:
1. Коммерческий или некоммерческий?
2. Страна, регион/город:
3. По всей стране или локально?
4. Топ-10 запросов (используй ключевые слова из профиля сайта, не выдумывай):
6. Мессенджеры и площадки для рекламы (какие каналы и площадки лучше всего подходят для продвижения сайта, исходя из его тематики и аудитории):
"""

DIRECT_CANDIDATE_PROMPT = """
Ты ищешь кандидатов в ТОЧНЫЕ (прямые) конкуренты для сайта {domain}.
Ниже профиль нашего сайта:

{site_summary}

Кого считать точным конкурентом:
- сайт предлагает очень похожие товары, услуги или основной продукт;
- у сайта схожий коммерческий сценарий;
- сайт борется за ту же аудиторию с очень близким предложением;
- сайт похож по тематике, структуре предложения и намерению пользователя.

Правила:
- Перед включением сайта в список обязательно вызови инструмент browse_page для его URL.
- Проанализируй полученный профиль: ключевые слова, заголовки, описание. Если профиль показывает недостаточное сходство (например, ключевые слова не пересекаются, тематика отличается) – НЕ включай его.
- Исключай маркетплейсы, агрегаторы, доски объявлений, соцсети, каталоги франшиз, справочники, новостные порталы и гигантов вне нашей ниши.
- Отдавай предпочтение самостоятельным сайтам компаний/сервисов, а не витринам и сборникам.
- Стремись найти минимум 5 хороших точных конкурентов. Если найдёшь меньше – честно укажи это в конце списка (например, "# Найдено только X кандидатов").
- Не выдумывай сайты, только те, которые реально проверил через browse_page.
- Верни только список корневых URL, по одному на строку, без пояснений и без нумерации.
"""

INDIRECT_CANDIDATE_PROMPT = """
Ты ищешь кандидатов в КОСВЕННЫЕ / РАСШИРЕННЫЕ конкуренты для сайта {domain}.
Ниже профиль нашего сайта:

{site_summary}

Кого считать косвенным / расширенным конкурентом:
- сайт работает в смежной нише;
- сайт решает ту же или близкую задачу другим способом;
- сайт закрывает ту же потребность другим продуктом, форматом или моделью;
- сайт частично пересекается по аудитории;
- сайт может быть альтернативой в выборе клиента, даже если это не прямой аналог;
- сайт конкурирует за тот же спрос, намерение пользователя, бюджет или внимание аудитории;
- сайт может быть выбран клиентом вместо нашего сайта как другой способ решить похожую проблему.

Правила:
- Перед включением сайта в список обязательно вызови инструмент browse_page для его URL.
- Проанализируй полученный профиль: ключевые слова, заголовки, описание. Оставляй только те сайты, у которых есть заметная смысловая, продуктовая, аудиторная или поведенческая близость к нашему сайту.
- НЕ предлагай прямых конкурентов, если они слишком буквально совпадают с сайтом.
- Исключай маркетплейсы, агрегаторы, доски объявлений, соцсети, каталоги франшиз, справочники и слишком общие порталы.
- Стремись найти минимум 5 хороших косвенных конкурентов. Если найдёшь меньше – честно укажи это в конце списка (например, "# Найдено только X кандидатов").
- Не выдумывай сайты, только те, которые реально проверил через browse_page.
- Верни только список корневых URL, по одному на строку, без пояснений и без нумерации.
"""

FINAL_REPORT_PROMPT = """
Ты аналитик сайтов. Используй только данные ниже и не выдумывай новые сайты.

Профиль нашего сайта:
{site_summary}

Черновик анализа:
{site_outline}

Проверенные точные конкуренты:
{verified_direct_json}

Проверенные косвенные конкуренты:
{verified_indirect_json}

Отклонённые кандидаты:
{rejected_json}

Сформируй итоговый ответ строго по структуре:
1. Коммерческий или некоммерческий?
2. Страна, регион/город:
3. По всей стране или локально?
4. Топ-10 запросов (используй реальные ключевые слова из профиля нашего сайта, не выдумывай):
5. Точные конкуренты (коротко: живой? тематика? масштаб? релевантность?) – только из списка проверенных точных конкурентов:
6. Мессенджеры и площадки для рекламы (какие каналы и площадки лучше всего подходят для продвижения сайта, исходя из его тематики и аудитории):
7. Точные конкуренты (ссылки):
8. Конкуренты:
   - Отличные конкуренты (прямые): (перечислить сайты из списка точных конкурентов, которые наиболее релевантны, с кратким пояснением)
   - Подходящие (косвенные/расширенные): (перечислить сайты из списка косвенных конкурентов, которые подходят как альтернативы или смежные решения, с кратким пояснением)

Правила:
- Используй только сайты из переданных проверенных списков.
- В пунктах 5 и 7 перечисляй только проверенные точные конкуренты.
- В пункте 8 чётко разделяй на "Отличные конкуренты (прямые)" и "Подходящие (косвенные/расширенные)". Для каждого сайта дай краткое пояснение, почему он подходит.
- Если точных конкурентов меньше 5, укажи это. Если косвенных меньше 5, укажи это.
- Не выдумывай дополнительные компании, ссылки, географию, запросы или факты, которых нет в исходных данных.
- Отвечай коротко, конкретно и по делу.
"""


def call_mistral(messages: list[dict], *, use_tools: bool = False, temperature: float = 0.3, max_tokens: int = 4096) -> dict:
    global _api_key_index
    keys = [k for k in MISTRAL_API_KEYS if k]
    if not keys:
        raise RuntimeError("Нет ни одного API-ключа в списке MISTRAL_API_KEYS")

    start_index = _api_key_index % len(keys)
    for i in range(len(keys)):
        idx = (start_index + i) % len(keys)
        api_key = keys[idx]
        try:
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": MISTRAL_MODEL,
                "messages": messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            if use_tools:
                payload["tools"] = tools

            response = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=90)
            response.raise_for_status()
            with _api_key_lock:
                _api_key_index += 1
            return response.json()["choices"][0]["message"]
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                continue
            else:
                raise
        except Exception:
            continue

    raise RuntimeError(f"Все API-ключи невалидны или не имеют доступа к модели {MISTRAL_MODEL}")


def complete_with_tools(messages: list[dict], *, temperature: float = 0.3, max_tokens: int = 4096) -> str:
    conversation = list(messages)
    max_rounds = 12

    for _ in range(max_rounds):
        response_message = call_mistral(
            conversation,
            use_tools=True,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        conversation.append(response_message)
        tool_calls = response_message.get("tool_calls") or []
        if not tool_calls:
            return response_message.get("content", "")

        def process_tool_call(tool_call):
            func = tool_call.get("function") or {}
            if func.get("name") != "browse_page":
                return None
            try:
                arguments = json.loads(func.get("arguments", "{}"))
                url = arguments.get("url", "")
                content = browse_page(url) if url else json.dumps({"error": "Пустой URL"}, ensure_ascii=False)
            except Exception as exc:
                content = json.dumps({"error": str(exc)}, ensure_ascii=False)
            return {
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "name": "browse_page",
                "content": content,
            }

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            results = list(executor.map(process_tool_call, tool_calls))

        for result in results:
            if result:
                conversation.append(result)

    return "Не удалось завершить обработку tool calls."


def verify_competitors(our_profile: dict, candidate_urls: list[str], target_type: str) -> tuple[list[dict], list[dict]]:
    verified = []
    rejected = []
    seen_domains = set()

    unique_urls = []
    for raw_url in candidate_urls:
        url = normalize_root_url(raw_url)
        domain = get_domain_key(url)
        if domain and domain not in seen_domains:
            seen_domains.add(domain)
            unique_urls.append(url)

    def process_candidate(url):
        domain = get_domain_key(url)
        if domain == our_profile.get("domain"):
            return ("reject", {"url": url, "reason": "Это наш собственный сайт", "type": target_type})
        if is_blocked_domain(domain):
            return ("reject", {"url": url, "reason": "Маркетплейс / агрегатор", "type": target_type})

        candidate_profile = fetch_site_profile(url)
        if not candidate_profile.get("ok"):
            return ("reject", {
                "url": url,
                "reason": f"Недоступен: {candidate_profile.get('issue', 'ошибка')}",
                "type": target_type,
            })

        comparison = compare_profiles(our_profile, candidate_profile)
        actual_type = classify_competitor(comparison)

        record = {
            "url": candidate_profile["final_url"],
            "domain": candidate_profile["domain"],
            "title": candidate_profile["title"],
            "description": candidate_profile["description"],
            "keywords": candidate_profile.get("keywords", [])[:10],
            "live": True,
            "score": comparison["score"],
            "relevance": comparison["relevance"],
            "shared_keywords": comparison["shared_keywords"],
            "scale_comment": comparison["scale_comment"],
            "reason": comparison["reason"],
            "competitor_type": actual_type or "rejected",
        }

        if target_type == "direct":
            if actual_type == "direct":
                return ("verify", record)
            else:
                return ("reject", {
                    "url": candidate_profile["final_url"],
                    "reason": f"Не прошёл как точный конкурент ({comparison['score']}%). {comparison['reason']} {comparison['scale_comment']}",
                    "type": "direct",
                })
        else:
            if actual_type == "indirect":
                return ("verify", record)
            elif actual_type == "direct":
                return ("reject", {
                    "url": candidate_profile["final_url"],
                    "reason": f"Слишком близок к прямому конкуренту ({comparison['score']}%), поэтому не включён в косвенные.",
                    "type": "indirect",
                })
            else:
                return ("reject", {
                    "url": candidate_profile["final_url"],
                    "reason": f"Недостаточная тематическая близость для косвенного конкурента ({comparison['score']}%). {comparison['reason']} {comparison['scale_comment']}",
                    "type": "indirect",
                })

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(process_candidate, url) for url in unique_urls]
        for future in concurrent.futures.as_completed(futures):
            try:
                action, data = future.result()
                if action == "verify":
                    verified.append(data)
                else:
                    rejected.append(data)
            except Exception as e:
                rejected.append({"url": "ошибка обработки", "reason": str(e), "type": target_type})

    verified.sort(key=lambda item: item["score"], reverse=True)
    return verified, rejected


def get_site_outline(our_profile: dict) -> str:
    prompt = SITE_SUMMARY_PROMPT.format(site_summary=summarize_profile(our_profile))
    return call_mistral(
        [{"role": "user", "content": prompt}],
        use_tools=False,
        temperature=0.2,
        max_tokens=1200,
    ).get("content", "")


def get_candidate_domains(domain: str, our_profile: dict, competitor_type: str, excluded_domains: set[str] | None = None) -> list[str]:
    excluded_domains = excluded_domains or set()

    if competitor_type == "direct":
        prompt = DIRECT_CANDIDATE_PROMPT.format(domain=domain, site_summary=summarize_profile(our_profile))
    else:
        prompt = INDIRECT_CANDIDATE_PROMPT.format(domain=domain, site_summary=summarize_profile(our_profile))

    content = complete_with_tools(
        [{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1800,
    )
    urls = extract_candidate_urls(content)
    urls = dedupe_urls(urls)
    urls = exclude_domains(urls, excluded_domains)
    return urls


def ensure_min_indirect(domain: str, our_profile: dict, direct_verified: list[dict], indirect_verified: list[dict], rejected: list[dict]) -> tuple[list[dict], list[dict]]:
    if len(indirect_verified) >= 5:
        return indirect_verified, rejected

    excluded_domains = {our_profile.get("domain", "")}
    excluded_domains.update(item["domain"] for item in direct_verified)
    excluded_domains.update(item["domain"] for item in indirect_verified if item.get("domain"))

    extra_candidates = get_candidate_domains(
        domain,
        our_profile,
        competitor_type="indirect",
        excluded_domains=excluded_domains,
    )
    extra_verified, extra_rejected = verify_competitors(our_profile, extra_candidates, "indirect")

    existing_domains = {item["domain"] for item in indirect_verified}
    for item in extra_verified:
        if item["domain"] not in existing_domains:
            indirect_verified.append(item)
            existing_domains.add(item["domain"])

    rejected.extend(extra_rejected)
    indirect_verified.sort(key=lambda item: item["score"], reverse=True)
    return indirect_verified, rejected


def build_section_5_direct(verified_direct: list[dict]) -> str:
    lines = ["5. Точные конкуренты (коротко: живой? тематика? масштаб? релевантность?):"]
    if not verified_direct:
        lines.append("- Проверенных точных конкурентов не найдено.")
        return "\n".join(lines)

    for item in verified_direct[:10]:
        shared = ", ".join(item.get("shared_keywords", [])[:4]) or "мало общих терминов"
        lines.append(
            f"- {item['url']} — живой, релевантность {item['score']}%, {item['scale_comment']}, совпадения: {shared}."
        )
    return "\n".join(lines)


def build_section_7_direct(verified_direct: list[dict]) -> str:
    lines = ["7. Точные конкуренты (ссылки):"]
    if not verified_direct:
        lines.append("- Проверенных ссылок нет")
        return "\n".join(lines)
    for item in verified_direct[:10]:
        lines.append(f"- {item['url']}")
    return "\n".join(lines)


def build_section_8_competitors(verified_direct: list[dict], verified_indirect: list[dict]) -> str:
    lines = ["8. Конкуренты:"]
    
    # Отличные конкуренты (прямые)
    lines.append("   - Отличные конкуренты (прямые):")
    if verified_direct:
        for item in verified_direct[:10]:
            lines.append(f"      * {item['url']} — {item['scale_comment']}, релевантность {item['score']}%, совпадения: {', '.join(item.get('shared_keywords', [])[:4]) or 'мало общих терминов'}.")
    else:
        lines.append("      * Проверенных точных конкурентов не найдено.")
    
    # Подходящие (косвенные/расширенные)
    lines.append("   - Подходящие (косвенные/расширенные):")
    if verified_indirect:
        for item in verified_indirect[:10]:
            lines.append(f"      * {item['url']} — {item['scale_comment']}, релевантность {item['score']}%, совпадения: {', '.join(item.get('shared_keywords', [])[:4]) or 'мало общих терминов'}.")
    else:
        lines.append("      * Проверенных косвенных конкурентов не найдено.")
    
    return "\n".join(lines)


def build_final_report(
    our_profile: dict,
    site_outline: str,
    verified_direct: list[dict],
    verified_indirect: list[dict],
    rejected: list[dict],
) -> str:
    verified_direct_json = json.dumps(verified_direct[:10], ensure_ascii=False, indent=2)
    verified_indirect_json = json.dumps(verified_indirect[:10], ensure_ascii=False, indent=2)
    rejected_json = json.dumps(rejected[:20], ensure_ascii=False, indent=2)

    prompt = FINAL_REPORT_PROMPT.format(
        site_summary=summarize_profile(our_profile),
        site_outline=site_outline or "Нет черновика анализа",
        verified_direct_json=verified_direct_json,
        verified_indirect_json=verified_indirect_json,
        rejected_json=rejected_json,
    )
    report = call_mistral(
        [{"role": "user", "content": prompt}],
        use_tools=False,
        temperature=0.25,
        max_tokens=3000,
    ).get("content", "")

    report = replace_section(report, 5, build_section_5_direct(verified_direct))
    report = replace_section(report, 7, build_section_7_direct(verified_direct))
    report = replace_section(report, 8, build_section_8_competitors(verified_direct, verified_indirect))
    return report


def build_verified_rows(verified: list[dict]) -> list[dict]:
    rows = []
    for item in verified:
        rows.append(
            {
                "URL": item["url"],
                "Тип": "Точный" if item.get("competitor_type") == "direct" else "Косвенный",
                "Статус": "OK",
                "Релевантность": f"{item['score']}% ({item['relevance']})",
                "Совпадения": ", ".join(item.get("shared_keywords", [])[:5]) or "—",
                "Комментарий": item.get("scale_comment", ""),
            }
        )
    return rows


def run_full_analysis(domain: str) -> tuple[str, dict, list[dict], list[dict], list[dict]]:
    our_profile = fetch_site_profile(domain)
    if not our_profile.get("ok"):
        raise RuntimeError(f"Не удалось открыть наш сайт: {our_profile.get('issue', 'ошибка')}")

    site_outline = get_site_outline(our_profile)

    direct_candidates = get_candidate_domains(domain, our_profile, competitor_type="direct")
    indirect_candidates = get_candidate_domains(domain, our_profile, competitor_type="indirect")

    if not direct_candidates and not indirect_candidates:
        raise RuntimeError("Не удалось получить список кандидатов в конкуренты")

    verified_direct, rejected_direct = verify_competitors(our_profile, direct_candidates, "direct")

    direct_domains = {item["domain"] for item in verified_direct}
    indirect_candidates = exclude_domains(indirect_candidates, direct_domains)
    verified_indirect, rejected_indirect = verify_competitors(our_profile, indirect_candidates, "indirect")

    rejected = rejected_direct + rejected_indirect
    verified_indirect, rejected = ensure_min_indirect(domain, our_profile, verified_direct, verified_indirect, rejected)

    verified_direct = verified_direct[:10]
    verified_indirect = verified_indirect[:10]

    report = build_final_report(
        our_profile,
        site_outline,
        verified_direct,
        verified_indirect,
        rejected,
    )
    return report, our_profile, verified_direct, verified_indirect, rejected


def render_validation_table(verified_direct: list[dict], verified_indirect: list[dict]) -> None:
    all_verified = verified_direct + verified_indirect
    all_verified.sort(key=lambda x: x["score"], reverse=True)
    top_verified = all_verified[:10]
    rows = build_verified_rows(top_verified)
    if not rows:
        return

    st.subheader("Топ-10 проверенных конкурентов")
    st.caption(
        "Сайты, прошедшие проверку доступности и тематической близости. Отсортированы по релевантности."
    )
    st.dataframe(rows, use_container_width=True, hide_index=True)


def rerun_competitors_only(domain: str, our_profile: dict) -> tuple[list[dict], list[dict], list[dict]]:
    direct_candidates = get_candidate_domains(domain, our_profile, competitor_type="direct")
    indirect_candidates = get_candidate_domains(domain, our_profile, competitor_type="indirect")

    verified_direct, rejected_direct = verify_competitors(our_profile, direct_candidates, "direct")
    direct_domains = {item["domain"] for item in verified_direct}

    indirect_candidates = exclude_domains(indirect_candidates, direct_domains)
    verified_indirect, rejected_indirect = verify_competitors(our_profile, indirect_candidates, "indirect")

    rejected = rejected_direct + rejected_indirect
    verified_indirect, rejected = ensure_min_indirect(domain, our_profile, verified_direct, verified_indirect, rejected)

    return verified_direct[:10], verified_indirect[:10], rejected


def replace_section(text: str, section_number: int, new_section: str) -> str:
    pattern = re.compile(rf"(?ms)^({section_number}\..*?)(?=^\d+\.|\Z)")
    match = pattern.search(text)
    if not match:
        return f"{text}\n\n{new_section}"
    return text[: match.start()] + new_section.strip() + "\n\n" + text[match.end() :].lstrip()


def render_best_competitors(verified_direct: list[dict], verified_indirect: list[dict], limit=10):
    combined = verified_direct + verified_indirect
    combined.sort(key=lambda x: x["score"], reverse=True)
    if not combined:
        st.info("Нет проверенных конкурентов для отображения.")
        return
    st.subheader("Лучшие конкуренты (по релевантности)")
    st.caption("Сайты, наиболее подходящие по тематике и масштабу. Можно открыть или скопировать домен.")
    
    for index, item in enumerate(combined[:limit], start=1):
        url = item.get("url", "")
        domain = item.get("domain") or get_domain_key(url)
        safe_domain = json.dumps(domain, ensure_ascii=False)
        safe_url = json.dumps(url, ensure_ascii=False)
        html = f"""
        <div style="display:flex; align-items:center; justify-content:space-between; gap:12px; padding:10px 12px; border:1px solid #e5e7eb; border-radius:10px; margin-bottom:8px; font-family:Arial, sans-serif;">
            <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                <span style="font-weight:600;margin-right:8px;">{index}.</span>
                <a href={safe_url} target="_blank" style="text-decoration:none;color:#2563eb;">{domain}</a>
                <span style="margin-left:8px; color:#6b7280; font-size:0.9em;">({item['score']}%)</span>
            </div>
            <button onclick='navigator.clipboard.writeText({safe_domain})' style="border:1px solid #d1d5db; border-radius:8px; padding:6px 10px; background:#ffffff; cursor:pointer;">Копировать</button>
        </div>
        """
        components.html(html, height=64)


# ========== ИНТЕРФЕЙС STREAMLIT ==========

domain = st.text_input("Введи домен сайта (например, zaryadiavto.ru):")

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

if st.button("Провести анализ"):
    if not domain:
        st.warning("Введи домен")
    elif not MISTRAL_API_KEYS:
        st.warning("Не найдены API-ключи. Добавьте их в список MISTRAL_API_KEYS.")
    else:
        with st.spinner("Анализирую и проверяю точных и косвенных конкурентов..."):
            try:
                result, our_profile, verified_direct, verified_indirect, rejected = run_full_analysis(domain)
                st.session_state.result = result
                st.session_state.our_profile = our_profile
                st.session_state.verified_direct_competitors = verified_direct
                st.session_state.verified_indirect_competitors = verified_indirect
                st.session_state.rejected_competitors = rejected
                st.session_state.last_domain = domain
            except Exception as exc:
                st.error(f"Ошибка: {exc}")

if st.session_state.result and st.button("Обновить список конкурентов с проверкой релевантности"):
    saved_domain = st.session_state.last_domain or domain
    our_profile = st.session_state.our_profile
    if not saved_domain or not our_profile:
        st.warning("Сначала запусти полный анализ")
    else:
        with st.spinner("Перепроверяю конкурентов..."):
            try:
                verified_direct, verified_indirect, rejected = rerun_competitors_only(saved_domain, our_profile)
                updated = replace_section(st.session_state.result, 5, build_section_5_direct(verified_direct))
                updated = replace_section(updated, 7, build_section_7_direct(verified_direct))
                updated = replace_section(updated, 8, build_section_8_competitors(verified_direct, verified_indirect))

                st.session_state.result = updated
                st.session_state.verified_direct_competitors = verified_direct
                st.session_state.verified_indirect_competitors = verified_indirect
                st.session_state.rejected_competitors = rejected
                st.success("Список конкурентов обновлён")
            except Exception as exc:
                st.error(f"Ошибка переделки: {exc}")

if st.session_state.result:
    st.subheader("Результат анализа")
    st.markdown(st.session_state.result, unsafe_allow_html=True)

    # Блок с лучшими конкурентами (кнопки копирования)
    render_best_competitors(
        st.session_state.verified_direct_competitors,
        st.session_state.verified_indirect_competitors,
        limit=10
    )

    # Таблица с топ-10 проверенных конкурентов
    render_validation_table(
        st.session_state.verified_direct_competitors,
        st.session_state.verified_indirect_competitors,
    )
