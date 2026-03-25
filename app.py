import json
import math
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
# Mistral (основные)
MISTRAL_API_KEYS = [
    "S7ZtbybPJ6eVtI6SXpLrWTxZg5ScQSPR",
    "RciSeumN9OBaOuhUNcQ0ynbjKSVkw6kF",
    "jMinLgK9DSNsMJ6gSQM7yATFNRfoOvxx",
    "hzCXFKU2QmiHcVN7nbuHWSDKCkqW29MJ",
]

# Groq (резерв)
GROQ_API_KEY = "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"
GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
GROQ_MODEL = "llama-3.3-70b-versatile"

# Gemini (резерв)
GEMINI_API_KEY = "AIzaSyCRhU1ahpgwh9xCRaFgIaII6FxxjYfbDh0"
GEMINI_API_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash-exp:generateContent"
GEMINI_MODEL = "gemini-2.0-flash-exp"

# Exa
EXA_API_KEYS = [
    "5c8f7269-38ce-4f0d-8059-de075646d002",
    "3d9ba739-d0ca-4c27-9be5-5d0543944737",
    "473e4118-05cf-43a4-b21c-29d833390442",
]

# Jina Reader
JINA_API_KEYS = [
    "jina_d3ebb125d2f24e938e21abf8d562e5498EdB-_JFA3jU8lgOtlvxURphhdBe",
    "jina_486b05a2544e4acba496d5733d044ad9GDR0gPHC7hHlOUaxBRXrGAcGMCT7",
]
JINA_READER_URL = "https://r.jina.ai/"

# Потокобезопасные счётчики для round-robin
_mistral_lock = threading.Lock()
_mistral_idx = 0

_exa_lock = threading.Lock()
_exa_idx = 0

_jina_lock = threading.Lock()
_jina_idx = 0

def get_next_mistral_key():
    global _mistral_idx
    if not MISTRAL_API_KEYS:
        return None
    with _mistral_lock:
        key = MISTRAL_API_KEYS[_mistral_idx % len(MISTRAL_API_KEYS)]
        _mistral_idx += 1
        return key

def get_next_exa_key():
    global _exa_idx
    if not EXA_API_KEYS:
        return None
    with _exa_lock:
        key = EXA_API_KEYS[_exa_idx % len(EXA_API_KEYS)]
        _exa_idx += 1
        return key

def get_next_jina_key():
    global _jina_idx
    if not JINA_API_KEYS:
        return None
    with _jina_lock:
        key = JINA_API_KEYS[_jina_idx % len(JINA_API_KEYS)]
        _jina_idx += 1
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

# ========== ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (без изменений) ==========
# ... (все функции от fetch_site_profile до exclude_domains остаются как в предыдущем коде)
# Для краткости они здесь не приведены, но должны быть.

# ========== ИНТЕГРАЦИЯ EXA AI ==========
def search_exa(query: str, num_results: int = 15) -> list[str]:
    api_key = get_next_exa_key()
    if not api_key:
        return []
    url = "https://api.exa.ai/search"
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "query": query,
        "type": "neural",
        "numResults": num_results,
        "contents": {"text": False}
    }
    try:
        response = requests.post(url, json=payload, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        urls = [normalize_root_url(r["url"]) for r in data.get("results", [])]
        return dedupe_urls(urls)
    except Exception as e:
        st.warning(f"Exa API ошибка: {e}")
        return []


# ========== ФУНКЦИИ ДЛЯ РАБОТЫ С LLM ==========
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

# Промты
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


def call_mistral(messages, use_tools=False, temperature=0.3, max_tokens=4096):
    api_key = get_next_mistral_key()
    if not api_key:
        raise Exception("Нет доступных ключей Mistral")
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
    else:
        raise Exception(f"Mistral ошибка {response.status_code}: {response.text}")


def call_groq(messages, use_tools=False, temperature=0.3, max_tokens=4096):
    if use_tools:
        raise Exception("Groq не поддерживает функции (tools)")
    headers = {"Authorization": f"Bearer {GROQ_API_KEY}", "Content-Type": "application/json"}
    payload = {
        "model": GROQ_MODEL,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    response = requests.post(GROQ_API_URL, json=payload, headers=headers, timeout=90)
    if response.status_code == 200:
        return response.json()["choices"][0]["message"]
    else:
        raise Exception(f"Groq ошибка {response.status_code}: {response.text}")


def call_gemini(messages, use_tools=False, temperature=0.3, max_tokens=4096):
    if use_tools:
        raise Exception("Gemini adapter does not support tools yet")
    # Преобразуем сообщения в формат Gemini
    contents = []
    for msg in messages:
        role = "model" if msg["role"] == "assistant" else msg["role"]
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})
    url = f"{GEMINI_API_URL}?key={GEMINI_API_KEY}"
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
        raise Exception(f"Gemini ошибка {response.status_code}: {response.text}")


def call_llm_with_fallback(messages, use_tools=False, temperature=0.3, max_tokens=4096):
    """
    Вызывает LLM с автоматическим переключением между провайдерами.
    Для use_tools=True используется только Mistral (остальные не поддерживают tools).
    """
    if use_tools:
        # Для вызовов с функциями используем только Mistral
        return call_mistral(messages, use_tools=True, temperature=temperature, max_tokens=max_tokens)
    else:
        # Для обычных текстовых запросов пробуем всех по очереди
        providers = [
            ("Mistral", call_mistral),
            ("Gemini", call_gemini),
            ("Groq", call_groq),
        ]
        last_error = None
        for name, adapter in providers:
            try:
                return adapter(messages, use_tools=False, temperature=temperature, max_tokens=max_tokens)
            except Exception as e:
                last_error = f"{name}: {e}"
                continue
        raise RuntimeError(f"Все провайдеры не смогли обработать запрос. Последняя ошибка: {last_error}")


def complete_with_tools(messages, temperature=0.3, max_tokens=4096):
    conversation = list(messages)
    max_rounds = 12

    for _ in range(max_rounds):
        # Для tools используем только Mistral
        try:
            msg = call_mistral(conversation, use_tools=True, temperature=temperature, max_tokens=max_tokens)
        except Exception as e:
            st.error(f"Ошибка вызова Mistral (необходим для работы с функциями): {e}")
            raise

        conversation.append(msg)
        tool_calls = msg.get("tool_calls") or []
        if not tool_calls:
            return msg.get("content", "")

        def process(tc):
            func = tc.get("function", {})
            if func.get("name") != "browse_page":
                return None
            try:
                args = json.loads(func.get("arguments", "{}"))
                url = args.get("url", "")
                content = browse_page(url) if url else json.dumps({"error": "Пустой URL"}, ensure_ascii=False)
            except Exception as e:
                content = json.dumps({"error": str(e)}, ensure_ascii=False)
            return {"role": "tool", "tool_call_id": tc["id"], "name": "browse_page", "content": content}

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as ex:
            results = list(ex.map(process, tool_calls))

        for r in results:
            if r:
                conversation.append(r)

    return "Не удалось завершить обработку tool calls."


# ========== ОСНОВНЫЕ ФУНКЦИИ АНАЛИЗА ==========
def get_site_outline(our_profile):
    prompt = SITE_SUMMARY_PROMPT.format(site_summary=summarize_profile(our_profile))
    response = call_llm_with_fallback([{"role": "user", "content": prompt}], use_tools=False, temperature=0.2, max_tokens=1200)
    return response.get("content", "")


def get_candidate_domains(domain, our_profile, competitor_type, excluded_domains=None):
    excluded = excluded_domains or set()
    candidates = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures = []
        if EXA_API_KEYS:
            if competitor_type == "direct":
                futures.append(executor.submit(search_exa, f"similar to {domain}", 15))
            else:
                futures.append(executor.submit(search_exa, f"companies in related niches to {domain}", 15))
        if competitor_type == "direct":
            prompt = DIRECT_CANDIDATE_PROMPT.format(domain=domain, site_summary=summarize_profile(our_profile))
        else:
            prompt = INDIRECT_CANDIDATE_PROMPT.format(domain=domain, site_summary=summarize_profile(our_profile))
        def mistral_task():
            content = complete_with_tools([{"role": "user", "content": prompt}], temperature=0.2, max_tokens=1800)
            return extract_candidate_urls(content)
        futures.append(executor.submit(mistral_task))
        for fut in concurrent.futures.as_completed(futures):
            try:
                candidates.extend(fut.result())
            except Exception as e:
                st.warning(f"Ошибка при поиске: {e}")
    candidates = dedupe_urls(candidates)
    candidates = exclude_domains(candidates, excluded)
    return candidates


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
        prof = fetch_site_profile(url)
        if not prof.get("ok"):
            return ("reject", {"url": url, "reason": f"Недоступен: {prof.get('issue', 'ошибка')}", "type": target_type})
        comp = compare_profiles(our_profile, prof)
        actual = classify_competitor(comp)
        if not comp["shared_keywords"]:
            return ("reject", {"url": prof["final_url"], "reason": "Нет общих ключевых слов", "type": target_type})
        rec = {
            "url": prof["final_url"], "domain": prof["domain"], "title": prof["title"],
            "description": prof["description"], "keywords": prof.get("keywords", [])[:10],
            "live": True, "score": comp["score"], "relevance": comp["relevance"],
            "shared_keywords": comp["shared_keywords"], "scale_comment": comp["scale_comment"],
            "reason": comp["reason"], "competitor_type": actual or "rejected",
        }
        if target_type == "direct":
            if actual == "direct":
                return ("verify", rec)
            else:
                return ("reject", {"url": prof["final_url"], "reason": f"Не прошёл как точный ({comp['score']}%). {comp['reason']}", "type": "direct"})
        else:
            if actual == "indirect":
                return ("verify", rec)
            elif actual == "direct":
                return ("reject", {"url": prof["final_url"], "reason": "Слишком близок к прямому", "type": "indirect"})
            else:
                return ("reject", {"url": prof["final_url"], "reason": f"Недостаточная близость ({comp['score']}%). {comp['reason']}", "type": "indirect"})

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
    dir_cand = get_candidate_domains(domain, our_profile, "direct")
    ind_cand = get_candidate_domains(domain, our_profile, "indirect")
    dir_ver, dir_rej = verify_competitors(our_profile, dir_cand, "direct")
    dir_doms = {d["domain"] for d in dir_ver}
    ind_cand = exclude_domains(ind_cand, dir_doms)
    ind_ver, ind_rej = verify_competitors(our_profile, ind_cand, "indirect")
    rej = dir_rej + ind_rej
    ind_ver, rej = ensure_min_indirect(domain, our_profile, dir_ver, ind_ver, rej)
    return dir_ver[:10], ind_ver[:10], rej


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


# ========== ИНТЕРФЕЙС ==========
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

if st.button("Провести анализ"):
    if not domain:
        st.warning("Введи домен")
    elif not MISTRAL_API_KEYS and not GROQ_API_KEY and not GEMINI_API_KEY:
        st.warning("Нет ни одного API-ключа для LLM.")
    else:
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

if st.session_state.result and st.button("Обновить конкурентов"):
    saved = st.session_state.last_domain or domain
    prof = st.session_state.our_profile
    if not saved or not prof:
        st.warning("Сначала запусти полный анализ")
    else:
        with st.spinner("Обновляю..."):
            try:
                dir_ver, ind_ver, rej = rerun_competitors_only(saved, prof)
                st.session_state.verified_direct_competitors = dir_ver
                st.session_state.verified_indirect_competitors = ind_ver
                st.session_state.rejected_competitors = rej
                st.success("Обновлено")
            except Exception as e:
                st.error(f"Ошибка: {e}")

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
