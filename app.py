import json
import math
import os
import re
from collections import Counter
from urllib.parse import urlparse

import requests
import streamlit as st
import streamlit.components.v1 as components
from bs4 import BeautifulSoup

st.set_page_config(page_title="Конкурентный Анализатор", layout="wide")
st.title("Конкурентный Анализатор")

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"
REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}
MARKETPLACE_BLOCKLIST = {
    "avito.ru",
    "www.avito.ru",
    "olx.ua",
    "www.olx.ua",
    "wildberries.ru",
    "www.wildberries.ru",
    "ozon.ru",
    "www.ozon.ru",
    "market.yandex.ru",
    "yandex.market",
    "tiu.ru",
    "www.tiu.ru",
    "prom.ua",
    "www.prom.ua",
    "aliexpress.com",
    "www.aliexpress.com",
    "satu.kz",
    "www.satu.kz",
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


def get_default_api_key() -> str:
    try:
        return str(st.secrets["MISTRAL_API_KEY"]).strip()
    except Exception:
        return os.getenv("MISTRAL_API_KEY", "").strip()


# API ключ оставлен в коде, но поле ввода в интерфейсе убрано
api_key = "S7ZtbybPJ6eVtI6SXpLrWTxZg5ScQSPR"

tools = [
    {
        "type": "function",
        "function": {
            "name": "browse_page",
            "description": (
                "Проверить сайт по URL и вернуть краткий профиль страницы: живая ли она, тема, заголовок, "
                "описание, ключевые слова и краткий фрагмент текста. Используй для каждого кандидата "
                "в конкуренты перед тем, как включать его в ответ."
            ),
            "parameters": {
                "type": "object",
                "properties": {"url": {"type": "string"}},
                "required": ["url"],
            },
        },
    }
]

SITE_SUMMARY_PROMPT = """
Ты аналитик сайтов. Ниже профиль нашего сайта:

{site_summary}

Сделай краткую оценку по пунктам 1-4 и 6. Не выдумывай недоступные факты, а там где уверенности нет — так и укажи.

Структура ответа строго такая:
1. Коммерческий или некоммерческий?
2. Страна, регион/город:
3. По всей стране или локально?
4. Топ-10 запросов:
6. Мессенджеры (%):
"""

CANDIDATE_PROMPT = """
Ты ищешь кандидатов в прямые конкуренты для сайта {domain}.
Ниже профиль нашего сайта:

{site_summary}

Правила:
- Ищи сайты максимально похожей тематики и масштаба.
- Исключай маркетплейсы, агрегаторы, доски объявлений, соцсети, каталоги франшиз и гигантов вне нашей ниши.
- Для каждого кандидата обязательно используй инструмент browse_page.
- Оставляй только сайты, по содержимому которых видно похожие товары/услуги.
- Верни только список из 15-20 корневых URL, по одному на строку, без пояснений.
"""

FINAL_REPORT_PROMPT = """
Ты аналитик сайтов. Используй только данные ниже и не выдумывай новые сайты.

Профиль нашего сайта:
{site_summary}

Черновик анализа:
{site_outline}

Проверенные и релевантные конкуренты:
{verified_json}

Отклонённые кандидаты:
{rejected_json}

Сформируй итоговый ответ строго по структуре:
1. Коммерческий или некоммерческий?
2. Страна, регион/город:
3. По всей стране или локально?
4. Топ-10 запросов:
5. 10 конкурентов (коротко: живой? тематика? масштаб? релевантность?):
6. Мессенджеры (%):
7. Конкуренты (только 10 ссылок):
   - https://site1.ru
   - https://site2.ru
8. Противоречия / отсутствие данных:

Правила:
- В пункте 5 перечисляй только проверенные релевантные сайты из блока verified_json.
- В пункте 7 укажи только проверенные ссылки из verified_json.
- Если проверенных сайтов меньше 10, честно так и напиши.
- В пункте 8 укажи, какие кандидаты были отброшены и почему.
- Отвечай коротко и по делу.
"""


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

    is_relevant = bool(
        final_score >= 20
        and (
            len(shared_keywords) >= 2
            or body_cosine >= 0.10
            or header_overlap >= 0.08
        )
    )

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
        "is_relevant": is_relevant,
    }


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



def call_mistral(messages: list[dict], *, use_tools: bool = False, temperature: float = 0.3, max_tokens: int = 4096) -> dict:
    if not api_key:
        raise RuntimeError(
            "Не указан Mistral API key. Добавь MISTRAL_API_KEY в st.secrets или в переменные окружения."
        )

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "mistral-large-latest",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if use_tools:
        payload["tools"] = tools

    response = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=90)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]


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

        appended_tool_result = False
        for tool_call in tool_calls:
            func = tool_call.get("function") or {}
            if func.get("name") != "browse_page":
                continue
            try:
                arguments = json.loads(func.get("arguments", "{}"))
                url = arguments.get("url", "")
                content = browse_page(url) if url else json.dumps({"error": "Пустой URL"}, ensure_ascii=False)
            except Exception as exc:
                content = json.dumps({"error": str(exc)}, ensure_ascii=False)

            conversation.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call["id"],
                    "name": "browse_page",
                    "content": content,
                }
            )
            appended_tool_result = True

        if not appended_tool_result:
            break

    return "Не удалось завершить обработку tool calls."


def get_site_outline(our_profile: dict) -> str:
    prompt = SITE_SUMMARY_PROMPT.format(site_summary=summarize_profile(our_profile))
    return call_mistral(
        [{"role": "user", "content": prompt}],
        use_tools=False,
        temperature=0.2,
        max_tokens=1200,
    ).get("content", "")


def get_candidate_domains(domain: str, our_profile: dict) -> list[str]:
    prompt = CANDIDATE_PROMPT.format(domain=domain, site_summary=summarize_profile(our_profile))
    content = complete_with_tools(
        [{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=1600,
    )
    return extract_candidate_urls(content)


def verify_competitors(our_profile: dict, candidate_urls: list[str]) -> tuple[list[dict], list[dict]]:
    verified = []
    rejected = []
    seen_domains = set()

    for raw_url in candidate_urls:
        url = normalize_root_url(raw_url)
        domain = get_domain_key(url)
        if not domain or domain in seen_domains:
            continue
        seen_domains.add(domain)

        if domain == our_profile.get("domain"):
            rejected.append({"url": url, "reason": "Это наш собственный сайт"})
            continue

        if is_blocked_domain(domain):
            rejected.append({"url": url, "reason": "Маркетплейс / агрегатор"})
            continue

        candidate_profile = fetch_site_profile(url)
        if not candidate_profile.get("ok"):
            rejected.append({"url": url, "reason": f"Недоступен: {candidate_profile.get('issue', 'ошибка')}"})
            continue

        comparison = compare_profiles(our_profile, candidate_profile)
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
        }

        if comparison["is_relevant"]:
            verified.append(record)
        else:
            rejected.append(
                {
                    "url": candidate_profile["final_url"],
                    "reason": (
                        f"Низкая релевантность ({comparison['score']}%). "
                        f"{comparison['reason']} {comparison['scale_comment']}"
                    ),
                }
            )

    verified.sort(key=lambda item: item["score"], reverse=True)
    return verified[:10], rejected


def build_final_report(our_profile: dict, site_outline: str, verified: list[dict], rejected: list[dict]) -> str:
    verified_json = json.dumps(verified[:10], ensure_ascii=False, indent=2)
    rejected_json = json.dumps(rejected[:15], ensure_ascii=False, indent=2)
    prompt = FINAL_REPORT_PROMPT.format(
        site_summary=summarize_profile(our_profile),
        site_outline=site_outline or "Нет черновика анализа",
        verified_json=verified_json,
        rejected_json=rejected_json,
    )
    report = call_mistral(
        [{"role": "user", "content": prompt}],
        use_tools=False,
        temperature=0.25,
        max_tokens=2500,
    ).get("content", "")
    report = replace_section(report, 5, build_section_5(verified))
    report = replace_section(report, 7, build_section_7(verified))
    report = replace_section(report, 8, build_section_8(rejected))
    return report


def build_validation_rows(verified: list[dict], rejected: list[dict]) -> list[dict]:
    rows = []
    for item in verified:
        rows.append(
            {
                "URL": item["url"],
                "Статус": "OK",
                "Релевантность": f"{item['score']}% ({item['relevance']})",
                "Совпадения": ", ".join(item.get("shared_keywords", [])[:5]),
                "Комментарий": item.get("scale_comment", ""),
            }
        )
    for item in rejected:
        rows.append(
            {
                "URL": item.get("url", ""),
                "Статус": "Отклонён",
                "Релевантность": "—",
                "Совпадения": "—",
                "Комментарий": item.get("reason", ""),
            }
        )
    return rows


def run_full_analysis(domain: str) -> tuple[str, dict, list[dict], list[dict]]:
    our_profile = fetch_site_profile(domain)
    if not our_profile.get("ok"):
        raise RuntimeError(f"Не удалось открыть наш сайт: {our_profile.get('issue', 'ошибка')}")

    site_outline = get_site_outline(our_profile)
    candidates = get_candidate_domains(domain, our_profile)
    if not candidates:
        raise RuntimeError("Не удалось получить список кандидатов в конкуренты")

    verified, rejected = verify_competitors(our_profile, candidates)
    report = build_final_report(our_profile, site_outline, verified, rejected)
    return report, our_profile, verified, rejected


def render_validation_table(verified: list[dict], rejected: list[dict]) -> None:
    rows = build_validation_rows(verified, rejected)
    if not rows:
        return

    st.subheader("Проверка найденных доменов")
    st.caption("Сначала проверяется доступность сайта, затем сходство тематики и примерный масштаб относительно нашего сайта.")
    st.dataframe(rows, use_container_width=True, hide_index=True)


def rerun_competitors_only(domain: str, our_profile: dict) -> tuple[list[dict], list[dict]]:
    candidates = get_candidate_domains(domain, our_profile)
    return verify_competitors(our_profile, candidates)


def replace_section(text: str, section_number: int, new_section: str) -> str:
    pattern = re.compile(rf"(?ms)^({section_number}\..*?)(?=^\d+\.|\Z)")
    match = pattern.search(text)
    if not match:
        return f"{text}\n\n{new_section}"
    return text[: match.start()] + new_section.strip() + "\n\n" + text[match.end() :].lstrip()


def build_section_5(verified: list[dict]) -> str:
    lines = ["5. 10 конкурентов (коротко: живой? тематика? масштаб? релевантность?):"]
    if not verified:
        lines.append("- Проверенных релевантных конкурентов не найдено.")
        return "\n".join(lines)

    for item in verified[:10]:
        shared = ", ".join(item.get("shared_keywords", [])[:4]) or "мало общих терминов"
        lines.append(
            f"- {item['url']} — живой, релевантность {item['score']}%, {item['scale_comment']}, совпадения: {shared}."
        )
    return "\n".join(lines)


def build_section_7(verified: list[dict]) -> str:
    lines = ["7. Конкуренты (только 10 ссылок):"]
    if not verified:
        lines.append("- Проверенных ссылок нет")
        return "\n".join(lines)
    for item in verified[:10]:
        lines.append(f"- {item['url']}")
    return "\n".join(lines)


def build_section_8(rejected: list[dict]) -> str:
    lines = ["8. Противоречия / отсутствие данных:"]
    if not rejected:
        lines.append("- Явных противоречий нет, проверенные конкуренты прошли фильтр живости и релевантности.")
        return "\n".join(lines)
    for item in rejected[:10]:
        lines.append(f"- {item.get('url', 'кандидат без URL')} — {item.get('reason', 'нет данных')}")
    return "\n".join(lines)


def render_copyable_domains(verified: list[dict]) -> None:
    if not verified:
        return

    st.subheader("Домены конкурентов")
    st.caption("Можно открыть сайт или скопировать только домен.")

    for index, item in enumerate(verified[:10], start=1):
        url = item.get("url", "")
        domain = item.get("domain") or get_domain_key(url)

        safe_domain = json.dumps(domain, ensure_ascii=False)
        safe_url = json.dumps(url, ensure_ascii=False)

        html = f"""
        <div style="
            display:flex;
            align-items:center;
            justify-content:space-between;
            gap:12px;
            padding:10px 12px;
            border:1px solid #e5e7eb;
            border-radius:10px;
            margin-bottom:8px;
            font-family:Arial, sans-serif;
        ">
            <div style="overflow:hidden;text-overflow:ellipsis;white-space:nowrap;">
                <span style="font-weight:600;margin-right:8px;">{index}.</span>
                <a href={safe_url} target="_blank" style="text-decoration:none;color:#2563eb;">
                    {domain}
                </a>
            </div>
            <button
                onclick='navigator.clipboard.writeText({safe_domain})'
                style="
                    border:1px solid #d1d5db;
                    border-radius:8px;
                    padding:6px 10px;
                    background:#ffffff;
                    cursor:pointer;
                "
            >
                Копировать
            </button>
        </div>
        """
        components.html(html, height=64)


domain = st.text_input("Введи домен сайта (например, zaryadiavto.ru):")

if "result" not in st.session_state:
    st.session_state.result = ""
if "our_profile" not in st.session_state:
    st.session_state.our_profile = None
if "verified_competitors" not in st.session_state:
    st.session_state.verified_competitors = []
if "rejected_competitors" not in st.session_state:
    st.session_state.rejected_competitors = []
if "last_domain" not in st.session_state:
    st.session_state.last_domain = ""

if st.button("Провести анализ"):
    if not domain:
        st.warning("Введи домен")
    elif not api_key:
        st.warning("Не найден Mistral API key в st.secrets или переменных окружения")
    else:
        with st.spinner("Анализирую и проверяю релевантность конкурентов..."):
            try:
                result, our_profile, verified, rejected = run_full_analysis(domain)
                st.session_state.result = result
                st.session_state.our_profile = our_profile
                st.session_state.verified_competitors = verified
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
                verified, rejected = rerun_competitors_only(saved_domain, our_profile)
                updated = replace_section(st.session_state.result, 5, build_section_5(verified))
                updated = replace_section(updated, 7, build_section_7(verified))
                updated = replace_section(updated, 8, build_section_8(rejected))
                st.session_state.result = updated
                st.session_state.verified_competitors = verified
                st.session_state.rejected_competitors = rejected
                st.success("Список конкурентов обновлён")
            except Exception as exc:
                st.error(f"Ошибка переделки: {exc}")

if st.session_state.result:
    st.subheader("Результат анализа")
    st.markdown(st.session_state.result, unsafe_allow_html=True)

    render_copyable_domains(st.session_state.verified_competitors)

    render_validation_table(
        st.session_state.verified_competitors,
        st.session_state.rejected_competitors,
    )
