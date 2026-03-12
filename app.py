import json
import math
import os
import re
from collections import Counter
from urllib.parse import urlparse
import requests
import streamlit as st
from bs4 import BeautifulSoup
import pyperclip  # добавлена для копирования в буфер обмена

st.set_page_config(page_title="Конкурентный Анализатор", layout="wide")
st.title("Конкурентный Анализатор")

# Ключ встроен напрямую — поле ввода удалено
api_key = "S7ZtbybPJ6eVtI6SXpLrWTxZg5ScQSPR"

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
    """Возвращает профиль сайта для последующего сравнения."""
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
    """Функция-инструмент для Mistral. Возвращает JSON с кратким профилем сайта."""
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

# ... все остальные функции без изменений (build_url_variants, normalize_root_url и т.д.) ...

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

# КНОПКА КОПИРОВАНИЯ ДОМЕНА КОНКУРЕНТА
if st.session_state.verified_competitors:
    st.subheader("Копировать домен конкурента")
    competitors = [item["domain"] for item in st.session_state.verified_competitors]
    selected_domain = st.selectbox("Выбери домен для копирования", competitors, key="copy_domain_select")
    if st.button("Копировать чистый домен"):
        pyperclip.copy(selected_domain)
        st.success(f"Домен скопирован в буфер обмена: {selected_domain}")

if st.session_state.result:
    st.subheader("Результат анализа")
    st.markdown(st.session_state.result, unsafe_allow_html=True)
    render_validation_table(
        st.session_state.verified_competitors,
        st.session_state.rejected_competitors,
    )
