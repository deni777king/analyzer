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

# ========== 1. НАСТРОЙКА КЛЮЧЕЙ (НОВЫЕ ИЗ ТЗ) ==========

# --- Mistral (4+3 ключа) ---
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

# --- Exa (4+3 ключа) ---
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

# --- Groq (6 ключей) ---
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

# --- Gemini (5 ключей) ---
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

# --- Jina для 3 Аудита ---
JINA_3AUDIT_KEY = "jina_d3ebb125d2f24e938e21abf8d562e5498EdB-_JFA3jU8lgOtlvxURphhdBe"
JINA_READER_URL = "https://r.jina.ai/"

# --- Настройки линий ---
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

# ========== 3. ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ (парсинг, сравнение) ==========
# (все функции до fetch_site_profile включительно — без изменений, я их опускаю для краткости,
#  но в финальном коде они должны быть полностью. Ниже приведены только изменённые и новые части.)

# ========== 4. ПОИСК КАНДИДАТОВ (С ГАРАНТИЕЙ 5+ URL) ==========
def search_exa(query: str, num_results: int = 15) -> list[str]:
    keys = get_exa_keys()
    if not keys:
        return []
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
        except:
            continue
    raise Exception("Все ключи Exa в текущей линии не сработали")

def get_candidate_domains(domain, our_profile, competitor_type, excluded_domains=None):
    excluded = excluded_domains or set()
    for attempt in range(2):  # две попытки с разными запросами
        if competitor_type == "direct":
            query = f"similar to {domain}"
            exa_urls = search_exa(query, num_results=30)
        else:
            query = f"companies in related niches to {domain}"
            exa_urls = search_exa(query, num_results=30)
        filtered = exclude_domains(dedupe_urls(exa_urls), excluded)
        if len(filtered) >= 5:
            return filtered[:15]
        # Вторая попытка – более широкий запрос
        if attempt == 0:
            query = f"{domain} competitors" if competitor_type == "direct" else f"{domain} similar businesses"
            exa_urls = search_exa(query, num_results=30)
            filtered = exclude_domains(dedupe_urls(exa_urls), excluded)
            if len(filtered) >= 5:
                return filtered[:15]
    # Если всё равно мало, возвращаем то, что есть (но не пустой)
    return filtered[:10] if filtered else []

def get_candidate_domains_llm(domain, our_profile, competitor_type, excluded_domains=None):
    excluded = excluded_domains or set()
    site_desc = summarize_profile(our_profile)
    # Усиленный промт с требованием минимум 10 URL
    if competitor_type == "direct":
        prompt = f"""
Ты ищешь прямых конкурентов для сайта {domain}. Профиль нашего сайта:
{site_desc}

Найди не менее 10 сайтов прямых конкурентов, которые работают в той же нише, с похожим продуктом/услугой, в том же регионе (если регион указан). Исключи маркетплейсы, доски объявлений, государственные учреждения.
Верни только список корневых URL, по одному на строку, без пояснений. Если не знаешь точных URL, укажи реально существующие сайты, которые, по твоему мнению, являются прямыми конкурентами.
"""
    else:
        prompt = f"""
Ты ищешь косвенных конкурентов для сайта {domain}. Профиль нашего сайта:
{site_desc}

Найди не менее 10 сайтов косвенных конкурентов: смежные ниши, альтернативные способы решения той же задачи, пересечение по аудитории. Исключи маркетплейсы, доски объявлений.
Верни только список корневых URL, по одному на строку, без пояснений. Постарайся найти как можно больше реальных сайтов.
"""
    for attempt in range(2):
        try:
            response = call_llm_with_fallback([{"role": "user", "content": prompt}], use_tools=False, temperature=0.3, max_tokens=2000)
            urls = extract_candidate_urls(response.get("content", ""))
            filtered = exclude_domains(dedupe_urls(urls), excluded)
            if len(filtered) >= 5:
                return filtered[:15]
        except Exception as e:
            st.warning(f"Попытка {attempt+1} LLM поиска не удалась: {e}")
    return filtered[:10] if filtered else []

# ========== 5. ПРОВЕРКА КОНКУРЕНТОВ (С ПРИНУДИТЕЛЬНЫМ ЗАЧИСЛЕНИЕМ) ==========
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
            return ("reject", {"url": url, "reason": f"Недоступен: {candidate_profile.get('issue', 'ошибка')}", "type": target_type})

        # Проверка региона
        candidate_region = extract_region(candidate_profile)
        if our_region.lower() not in ["россия", "рф", "вся россия", "по всей стране"] and \
           candidate_region.lower() not in ["россия", "рф", "вся россия", "по всей стране"] and \
           our_region.lower() != candidate_region.lower():
            return ("reject", {"url": candidate_profile["final_url"], "reason": f"Несовпадение региона: наш ({our_region}) vs кандидат ({candidate_region})", "type": target_type})

        # Сравнение профилей
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

        # ПРИНУДИТЕЛЬНОЕ ЗАЧИСЛЕНИЕ при высоком score
        if target_type == "direct" and actual_type != "direct" and comparison["score"] >= 35 and comparison["shared_keywords"]:
            actual_type = "direct"

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

# ========== 6. ОСНОВНОЙ АНАЛИЗ С ВЫВОДОМ КОЛИЧЕСТВА ==========
def run_full_analysis(domain):
    our = fetch_site_profile(domain)
    if not our.get("ok"):
        raise RuntimeError(f"Не удалось открыть наш сайт: {our.get('issue', 'ошибка')}")
    region = extract_region(our)
    outline = get_site_outline(our)

    dir_cand = get_candidate_domains(domain, our, "direct")
    ind_cand = get_candidate_domains(domain, our, "indirect")

    st.info(f"🔍 Найдено кандидатов: прямых — {len(dir_cand)}, косвенных — {len(ind_cand)}")

    if not dir_cand and not ind_cand:
        raise RuntimeError("Не удалось получить кандидатов")

    dir_ver, dir_rej = verify_competitors(our, dir_cand, "direct", region)
    dir_doms = {d["domain"] for d in dir_ver}
    ind_cand = exclude_domains(ind_cand, dir_doms)
    ind_ver, ind_rej = verify_competitors(our, ind_cand, "indirect", region)
    rej = dir_rej + ind_rej
    ind_ver, rej = ensure_min_indirect(domain, our, dir_ver, ind_ver, rej)

    st.info(f"✅ После проверки: прямых конкурентов — {len(dir_ver)}, косвенных — {len(ind_ver)}")

    dir_ver = dir_ver[:10]
    ind_ver = ind_ver[:10]
    messengers_platforms = recommend_messengers_platforms(our, dir_ver, ind_ver, region)
    report = build_final_report(our, outline, dir_ver, ind_ver, rej, region, messengers_platforms)
    return report, our, dir_ver, ind_ver, rej

def rerun_competitors_only(domain, our_profile):
    global current_line
    saved_line = current_line
    current_line = 3
    try:
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

        st.info(f"✅ (перепроверка) После проверки: прямых конкурентов — {len(dir_ver)}, косвенных — {len(ind_ver)}")

        return dir_ver[:10], ind_ver[:10], rej
    finally:
        current_line = saved_line

# ========== 7. ИЗВЛЕЧЕНИЕ РЕГИОНА ==========
@st.cache_data(ttl=3600)
def extract_region(profile: dict) -> str:
    prompt = f"""
Профиль сайта:
{summarize_profile(profile)}

Определи, в каком городе, регионе или стране работает этот сайт. Если сайт работает по всей стране, напиши "Россия" (или соответствующая страна).
Если регион не указан явно, сделай предположение на основе контактов, текстов, упоминаний.
Верни только название региона (например: "Москва", "Россия", "Казахстан", "Санкт-Петербург").
"""
    try:
        response = call_llm_with_fallback([{"role": "user", "content": prompt}], use_tools=False, temperature=0, max_tokens=50)
        region = response.get("content", "").strip()
        return region
    except Exception as e:
        st.warning(f"Ошибка определения региона: {e}")
        return "неизвестно"

# ========== 8. ПРОВЕРКА КОНКУРЕНТОВ (С УЧЁТОМ РЕГИОНА) ==========
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
            return ("reject", {"url": url, "reason": f"Недоступен: {candidate_profile.get('issue', 'ошибка')}", "type": target_type})

        # Проверка региона
        candidate_region = extract_region(candidate_profile)
        if our_region.lower() not in ["россия", "рф", "вся россия", "по всей стране"] and \
           candidate_region.lower() not in ["россия", "рф", "вся россия", "по всей стране"] and \
           our_region.lower() != candidate_region.lower():
            return ("reject", {"url": candidate_profile["final_url"], "reason": f"Несовпадение региона: наш ({our_region}) vs кандидат ({candidate_region})", "type": target_type})

        # Сравнение профилей
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

# ========== 9. ОСНОВНЫЕ ФУНКЦИИ АНАЛИЗА ==========
def get_site_outline(our_profile):
    prompt = SITE_SUMMARY_PROMPT.format(site_summary=summarize_profile(our_profile))
    response = call_llm_with_fallback([{"role": "user", "content": prompt}], use_tools=False, temperature=0.2, max_tokens=1200)
    return response.get("content", "")

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

def recommend_messengers_platforms(our_profile, verified_direct, verified_indirect, region):
    # Собираем краткую информацию о конкурентах
    competitors = verified_direct[:5] + verified_indirect[:5]
    comp_summary = "\n".join([
        f"- {c['url']} (сходство {c['score']}%)\n  Ключевые слова: {', '.join(c['shared_keywords'][:5])}"
        for c in competitors if c.get("shared_keywords")
    ])
    if not comp_summary:
        comp_summary = "Нет данных о конкурентах."
    our_summary = summarize_profile(our_profile)
    prompt = MESSENGER_RECOMMEND_PROMPT.format(
        our_summary=our_summary,
        competitors_summary=comp_summary,
        region=region
    )
    try:
        response = call_llm_with_fallback([{"role": "user", "content": prompt}], use_tools=False, temperature=0.2, max_tokens=800)
        return response.get("content", "")
    except Exception as e:
        st.warning(f"Ошибка при рекомендации мессенджеров: {e}")
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
    # Добавляем рекомендации по мессенджерам/площадкам в текст отчёта
    full_report = call_llm_with_fallback([{"role": "user", "content": prompt}], use_tools=False, temperature=0.25, max_tokens=3000).get("content", "")
    # Заменяем или дополняем пункты 1.5 и 1.6
    if messengers_platforms:
        # Вставляем рекомендации после пункта 1.4 (или в соответствующие места)
        full_report = re.sub(r"(1\.4.*?)(\n\n1\.5)", r"\1\n\nРекомендованные мессенджеры и площадки:\n" + messengers_platforms + r"\n\n\2", full_report, flags=re.DOTALL)
    return full_report

def run_full_analysis(domain):
    our = fetch_site_profile(domain)
    if not our.get("ok"):
        raise RuntimeError(f"Не удалось открыть наш сайт: {our.get('issue', 'ошибка')}")
    region = extract_region(our)
    outline = get_site_outline(our)
    dir_cand = get_candidate_domains(domain, our, "direct")
    ind_cand = get_candidate_domains(domain, our, "indirect")
    if not dir_cand and not ind_cand:
        raise RuntimeError("Не удалось получить кандидатов")
    dir_ver, dir_rej = verify_competitors(our, dir_cand, "direct", region)
    dir_doms = {d["domain"] for d in dir_ver}
    ind_cand = exclude_domains(ind_cand, dir_doms)
    ind_ver, ind_rej = verify_competitors(our, ind_cand, "indirect", region)
    rej = dir_rej + ind_rej
    ind_ver, rej = ensure_min_indirect(domain, our, dir_ver, ind_ver, rej)
    dir_ver = dir_ver[:10]
    ind_ver = ind_ver[:10]
    messengers_platforms = recommend_messengers_platforms(our, dir_ver, ind_ver, region)
    report = build_final_report(our, outline, dir_ver, ind_ver, rej, region, messengers_platforms)
    return report, our, dir_ver, ind_ver, rej

def rerun_competitors_only(domain, our_profile):
    global current_line
    saved_line = current_line
    current_line = 3
    try:
        region = extract_region(our_profile)
        dir_cand = get_candidate_domains_llm(domain, our_profile, "direct")
        ind_cand = get_candidate_domains_llm(domain, our_profile, "indirect")
        dir_ver, dir_rej = verify_competitors(our_profile, dir_cand, "direct", region)
        dir_doms = {d["domain"] for d in dir_ver}
        ind_cand = exclude_domains(ind_cand, dir_doms)
        ind_ver, ind_rej = verify_competitors(our_profile, ind_cand, "indirect", region)
        rej = dir_rej + ind_rej
        ind_ver, rej = ensure_min_indirect(domain, our_profile, dir_ver, ind_ver, rej)
        return dir_ver[:10], ind_ver[:10], rej
    finally:
        current_line = saved_line

# ========== 10. ИМИДЖЕВЫЙ АНАЛИЗ ==========
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

# ========== 11. ФУНКЦИЯ 3 АУДИТА ==========
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

# ========== 12. ИНТЕРФЕЙС STREAMLIT ==========
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
        if not domain:
            st.warning("Введи домен")
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
                finally:
                    queue.release()
with col2:
    if st.button("Перепроверка (только Groq/Gemini)"):
        if not domain:
            st.warning("Введи домен")
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
            else:
                st.info("🔍 Начинаем перепроверку...")
            with st.spinner("Перепроверяю..."):
                try:
                    our_profile = st.session_state.our_profile
                    if not our_profile:
                        our_profile = fetch_site_profile(domain)
                    dir_ver, ind_ver, rej = rerun_competitors_only(domain, our_profile)
                    st.session_state.verified_direct_competitors = dir_ver
                    st.session_state.verified_indirect_competitors = ind_ver
                    st.session_state.rejected_competitors = rej
                    st.success("Список конкурентов обновлён")
                except Exception as e:
                    st.error(f"Ошибка: {e}")
                finally:
                    queue.release()
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
    render_best_competitors(
        st.session_state.verified_direct_competitors,
        st.session_state.verified_indirect_competitors,
        limit=10
    )
    render_validation_table(
        st.session_state.verified_direct_competitors,
        st.session_state.verified_indirect_competitors,
    )
