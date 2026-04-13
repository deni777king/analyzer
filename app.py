import json
import re
import time
import random
from urllib.parse import urlparse

import requests
import streamlit as st
from bs4 import BeautifulSoup

st.set_page_config(page_title="Конкурентный Анализатор | 2 платных ИИ", layout="wide")
st.title("Конкурентный Анализатор (два платных ИИ, по 5 сайтов)")

# ========== 1. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (для загрузки профиля сайта) ==========
REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
}

def clean_text(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()

def build_url_variants(value: str) -> list[str]:
    raw = value.strip()
    if not raw: return []
    raw = re.sub(r"^[\-\s]+", "", raw)
    raw = re.sub(r"[\s/]+$", "", raw)
    raw = raw.replace("http://", "").replace("https://", "")
    raw = raw.replace("www.", "")
    domain = raw.split("/", 1)[0]
    return [f"https://{domain}", f"https://www.{domain}", f"http://{domain}", f"http://www.{domain}"]

def normalize_root_url(value: str) -> str:
    parsed = urlparse(value if value.startswith(("http://", "https://")) else f"https://{value}")
    netloc = parsed.netloc or parsed.path
    netloc = netloc.lower().strip().replace("http://", "").replace("https://", "").rstrip("/")
    return f"https://{netloc}"

def get_domain_key(value: str) -> str:
    parsed = urlparse(value if value.startswith(("http://", "https://")) else f"https://{value}")
    netloc = (parsed.netloc or parsed.path).lower().strip().replace("http://", "").replace("https://", "").rstrip("/")
    if netloc.startswith("www."):
        netloc = netloc[4:]
    return netloc

@st.cache_data(show_spinner=False, ttl=3600)
def fetch_site_profile(url_or_domain: str) -> dict:
    variants = build_url_variants(url_or_domain)
    for candidate in variants:
        try:
            response = requests.get(candidate, headers=REQUEST_HEADERS, timeout=15, allow_redirects=True)
            if response.status_code >= 400:
                continue
            content_type = response.headers.get("Content-Type", "")
            if "html" not in content_type and "text" not in content_type:
                continue
            soup = BeautifulSoup(response.text, "html.parser")
            for tag in soup(["script", "style", "noscript", "svg", "iframe"]):
                tag.decompose()
            title = clean_text(soup.title.get_text(" ", strip=True) if soup.title else "")
            description = clean_text(
                (soup.find("meta", attrs={"name": "description"}) or
                 soup.find("meta", attrs={"property": "og:description"}) or {}).get("content", "")
            )
            headings = [clean_text(tag.get_text(" ", strip=True)) for tag in soup.find_all(["h1", "h2"], limit=8) if clean_text(tag.get_text(" ", strip=True))]
            text = clean_text(soup.get_text(" ", strip=True))[:15000]
            final_url = response.url
            final_domain = get_domain_key(final_url)
            return {
                "ok": True,
                "final_url": normalize_root_url(final_url),
                "domain": final_domain,
                "title": title,
                "description": description,
                "headings": headings[:5],
                "text": text,
                "snippet": text[:1500],
                "issue": ""
            }
        except Exception:
            continue
    return {"ok": False, "issue": "Не удалось открыть сайт"}

# ========== 2. ФУНКЦИЯ ВЫЗОВА LLM (платной) ==========
def call_llm(messages, api_key, model="gpt-4o", temperature=0.3, max_tokens=3000):
    url = "https://api.openai.com/v1/chat/completions"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    response = requests.post(url, json=payload, headers=headers, timeout=120)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]["content"]
    else:
        raise Exception(f"LLM ошибка {response.status_code}: {response.text}")

# ========== 3. ЕДИНЫЙ ПРОМТ ДЛЯ АНАЛИЗА ОДНОГО САЙТА ==========
ANALYSIS_PROMPT = """
Твоя роль - аналитик сайтов / SEO-специалист.

Проанализируй сайт по следующему URL и его содержимому:

URL: {url}
Заголовок: {title}
Описание: {description}
Заголовки H1/H2: {headings}
Текст (первые 3000 символов): {text}

Задание:
1) Определи тематику сайта и регион работы. Регион определяй строго по офферу услуг, учитывая:
   - Блок «О компании», первый экран, раздел «Услуги / География работ», страницу доставки,
   - Упоминания «работаем по России», «по всей территории РФ», «выезд по регионам», «федеральный уровень»,
   - Кейсы, портфолио.
   Контакты (адрес офиса) не являются основным фактором географии бизнеса.
   Если сайт работает по всей стране, укажи «Россия». Если только в одном регионе/городе — укажи конкретный регион/город.
   Для доменов .uz или .kz — регион Узбекистан или Казахстан.

2) Найди 10 прямых конкурентов, работающих в ТОЙ ЖЕ ТЕМАТИКЕ и В ТОМ ЖЕ РЕГИОНЕ.
   - Конкуренты должны иметь собственные рабочие сайты (проверь, что сайт доступен, не маркетплейс, не доска объявлений, не госучреждение).
   - Оцени релевантность каждого по 5‑балльной системе (5 — идеальный конкурент).
   - Верни список в формате: URL — релевантность X/5

3) Дай 10 самых релевантных коммерческих поисковых запросов для этого сайта.
   - Только коммерческий интент (купить, заказать, получить расчет/консультацию).
   - Средне- и низкочастотные, строго релевантные услугам.
   - Не используй название региона в запросе.
   - Формат: запрос — примерное количество просмотров в месяц (ориентир на Яндекс.Вордстат или Google Ads). Если данных нет, просто укажи запрос.

4) Найди мессенджеры и соцсети, которые размещены на сайтах конкурентов (из пункта 2). Перечисли их (названия, без процентов).

5) Найди маркетплейсы и площадки (каталоги-агрегаторы, справочники), где размещены сайты конкурентов. Перечисли их (названия).

Верни ответ в виде структурированного JSON, строго следующего формата:
{{
  "theme_and_region": "Тематика: ... | Регион: ...",
  "competitors": [
    ["https://example1.com", 5],
    ["https://example2.com", 4]
  ],
  "queries": [
    "запрос1 — 100-200",
    "запрос2 — 300-400"
  ],
  "messengers_and_socials": ["Telegram", "WhatsApp", "VK"],
  "marketplaces": ["Avito", "Яндекс.Маркет"]
}}

Не добавляй никаких пояснений, только JSON.
"""

def analyze_site_with_llm(domain: str, api_key: str) -> dict:
    profile = fetch_site_profile(domain)
    if not profile.get("ok"):
        return {"error": f"Не удалось загрузить сайт: {profile.get('issue', 'ошибка')}"}
    prompt = ANALYSIS_PROMPT.format(
        url=profile["final_url"],
        title=profile["title"][:300],
        description=profile["description"][:500],
        headings="; ".join(profile["headings"])[:500],
        text=profile["text"][:3000]
    )
    try:
        response_text = call_llm([{"role": "user", "content": prompt}], api_key)
        # Извлекаем JSON из ответа (может быть обёрнут в ```json ... ```)
        json_match = re.search(r'```json\s*(.*?)\s*```', response_text, re.DOTALL)
        if json_match:
            response_text = json_match.group(1)
        else:
            # Попробуем найти фигурные скобки
            start = response_text.find('{')
            end = response_text.rfind('}')
            if start != -1 and end != -1:
                response_text = response_text[start:end+1]
        data = json.loads(response_text)
        # Приводим к единообразному виду
        return {
            "theme_and_region": data.get("theme_and_region", ""),
            "competitors": data.get("competitors", []),
            "queries": data.get("queries", []),
            "messengers_and_socials": data.get("messengers_and_socials", []),
            "marketplaces": data.get("marketplaces", [])
        }
    except Exception as e:
        return {"error": f"Ошибка анализа: {e}"}

# ========== 4. ФУНКЦИЯ ОТРИСОВКИ РЕЗУЛЬТАТОВ ==========
def render_results(results, domain):
    with st.expander(f"📊 {domain}", expanded=True):
        if "error" in results:
            st.error(results["error"])
            return
        st.markdown("**1. Тематика и регион**")
        st.write(results.get("theme_and_region", "—"))

        st.markdown("**2. Конкуренты (10)**")
        comps = results.get("competitors", [])
        if comps:
            for url, score in comps:
                st.markdown(f"- [{url}]({url}) — релевантность {score}/5")
        else:
            st.write("Не найдены")

        st.markdown("**3. Коммерческие запросы (10)**")
        queries = results.get("queries", [])
        if queries:
            for q in queries[:10]:
                st.write(f"- {q}")
        else:
            st.write("Нет данных")

        st.markdown("**4. Мессенджеры и соцсети конкурентов**")
        messengers = results.get("messengers_and_socials", [])
        if messengers:
            st.write(", ".join(messengers))
        else:
            st.write("Нет данных")

        st.markdown("**5. Маркетплейсы и площадки конкурентов**")
        marketplaces = results.get("marketplaces", [])
        if marketplaces:
            st.write(", ".join(marketplaces))
        else:
            st.write("Нет данных")

# ========== 5. ИНТЕРФЕЙС ДЛЯ ДВУХ ЛИНИЙ ==========
st.sidebar.header("Настройки платных ИИ")
api_key_1 = st.sidebar.text_input("API‑ключ для линии 1 (OpenAI)", type="password", key="key1")
api_key_2 = st.sidebar.text_input("API‑ключ для линии 2 (OpenAI)", type="password", key="key2")
st.sidebar.markdown("Используется модель `gpt-4o`. Введите ключи для каждой линии.")

# Линия 1
st.header("👤 Линия 1 (платный ИИ)")
domains1 = []
cols1 = st.columns(5)
for i in range(5):
    with cols1[i]:
        domains1.append(st.text_input(f"Сайт {i+1}", key=f"line1_domain_{i}", placeholder="example.com"))

if st.button("Анализировать линию 1", key="btn_line1"):
    valid_domains = [d.strip() for d in domains1 if d.strip()]
    if not valid_domains:
        st.warning("Введите хотя бы один домен")
    elif not api_key_1:
        st.warning("Введите API‑ключ для линии 1 в боковой панели")
    else:
        with st.spinner("Анализируем сайты (это может занять время)..."):
            for domain in valid_domains:
                st.write(f"Обработка {domain}...")
                result = analyze_site_with_llm(domain, api_key_1)
                render_results(result, domain)
                time.sleep(1)  # небольшая задержка для соблюдения лимитов
        st.success("Анализ линии 1 завершён!")

# Линия 2
st.header("👤 Линия 2 (платный ИИ)")
domains2 = []
cols2 = st.columns(5)
for i in range(5):
    with cols2[i]:
        domains2.append(st.text_input(f"Сайт {i+1}", key=f"line2_domain_{i}", placeholder="example.com"))

if st.button("Анализировать линию 2", key="btn_line2"):
    valid_domains = [d.strip() for d in domains2 if d.strip()]
    if not valid_domains:
        st.warning("Введите хотя бы один домен")
    elif not api_key_2:
        st.warning("Введите API‑ключ для линии 2 в боковой панели")
    else:
        with st.spinner("Анализируем сайты (это может занять время)..."):
            for domain in valid_domains:
                st.write(f"Обработка {domain}...")
                result = analyze_site_with_llm(domain, api_key_2)
                render_results(result, domain)
                time.sleep(1)
        st.success("Анализ линии 2 завершён!")
