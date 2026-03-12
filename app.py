import json
import math
import os
import re
from collections import Counter
from urllib.parse import urlparse
import requests
import streamlit as st
from bs4 import BeautifulSoup
import pyperclip  # для копирования в буфер обмена

st.set_page_config(page_title="Конкурентный Анализатор", layout="wide")
st.title("Конкурентный Анализатор")

# API-ключ встроен напрямую (поле ввода удалено)
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
    "avito.ru", "www.avito.ru",
    "olx.ua", "www.olx.ua",
    "wildberries.ru", "www.wildberries.ru",
    "ozon.ru", "www.ozon.ru",
    "market.yandex.ru", "yandex.market",
    "tiu.ru", "www.tiu.ru",
    "prom.ua", "www.prom.ua",
    "aliexpress.com", "www.aliexpress.com",
    "satu.kz", "www.satu.kz",
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

# Все остальные функции (fetch_site_profile, browse_page, build_url_variants и т.д.) оставляем без изменений
# Я не копирую их сюда, чтобы не загромождать — вставь их из твоего оригинального кода

# Основная логика (run_full_analysis, render_validation_table и т.д.) остаётся как была

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

# НОВАЯ КНОПКА: Копировать домен конкурента (без протокола)
if st.session_state.verified_competitors:
    st.subheader("Скопировать домен конкурента")
    competitors = [item["domain"] for item in st.session_state.verified_competitors]
    selected = st.selectbox("Выбери домен для копирования", competitors)
    if st.button("Копировать домен"):
        pyperclip.copy(selected)
        st.success(f"Домен скопирован в буфер: {selected}")

if st.session_state.result:
    st.subheader("Результат анализа")
    st.markdown(st.session_state.result, unsafe_allow_html=True)
    render_validation_table(
        st.session_state.verified_competitors,
        st.session_state.rejected_competitors,
    )
