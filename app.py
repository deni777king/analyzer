import streamlit as st
import requests
from bs4 import BeautifulSoup
import json

st.title("Конкурентный Анализатор")

# Окно ввода API-ключа Grok
api_key = st.text_input("Введи API-ключ Grok / xAI (xai-...)", type="password")

if not api_key:
    st.warning("Введите API-ключ Grok, чтобы начать анализ.")
    st.info("Получить ключ: https://console.x.ai/")
    st.stop()

GROK_API_URL = "https://api.x.ai/v1/chat/completions"

tools = [{
    "type": "function",
    "function": {
        "name": "browse_page",
        "description": "Посмотреть сайт по URL и извлечь текст.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"]
        }
    }
}]

def browse_page(url):
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)[:12000]
        return text if len(text) > 200 else "Сайт пустой или не работает"
    except Exception as e:
        return f"Сайт {url} недоступен: {str(e)}"

def call_grok(messages, use_tools=False):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "grok-beta",  # можно заменить на "grok-2" или "grok-2-mini"
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096
    }
    if use_tools:
        payload["tools"] = tools

    try:
        r = requests.post(GROK_API_URL, json=payload, headers=headers, timeout=90)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]
    except requests.exceptions.HTTPError as e:
        if r.status_code == 429:
            raise Exception("Лимит запросов исчерпан. Подождите 10–20 минут или пополните баланс в https://console.x.ai/")
        elif r.status_code == 401 or r.status_code == 403:
            raise Exception("Неверный или просроченный API-ключ. Проверьте ключ в https://console.x.ai/")
        elif r.status_code == 503 or r.status_code == 502:
            raise Exception("Сервер Grok временно недоступен (502/503). Попробуйте позже или используйте VPN.")
        raise Exception(f"Grok HTTP ошибка {r.status_code}: {r.text}")
    except requests.exceptions.Timeout:
        raise Exception("Таймаут соединения. Проверьте интернет или подключите VPN.")
    except Exception as e:
        raise Exception(f"Ошибка связи с Grok: {str(e)}")

domain = st.text_input("Введи домен сайта (например, zaryadiavto.ru):")

if 'result' not in st.session_state:
    st.session_state.result = ""

# Основной анализ
if st.button("Провести анализ"):
    if domain and api_key:
        st.session_state.result = ""
        with st.spinner("Анализирую конкурентов..."):
            try:
                prompt = f"""
Ты аналитик сайтов. Отвечай строго по пунктам, коротко.
ОБЯЗАТЕЛЬНО используй browse_page для проверки каждого сайта конкурента.
- Исключай мёртвые сайты.
- Выдавай только живые, реальные конкуренты похожего масштаба.
- В пункте 7 — ТОЛЬКО 10 чистых ссылок!

1. Коммерческий или некоммерческий?
2. Страна, регион/город:
3. По всей стране или локально?
4. Топ-10 запросов:
5. 10 конкурентов (коротко):
6. Мессенджеры (%):
7. Конкуренты (только 10 ссылок):
   - https://site1.ru
   - https://site2.ru
   ...
8. Противоречия:

Домен: {domain}
"""
                messages = [{"role": "user", "content": prompt}]
                resp = call_grok(messages, use_tools=True)
                st.session_state.result = resp.get('content', 'Нет ответа')
            except Exception as e:
                st.error(str(e))
    else:
        st.warning("Введи домен и API-ключ")

# Переделай пункт 7
if st.session_state.result and st.button("Переделай пункт 7 (конкуренты)"):
    if api_key:
        with st.spinner("Ищу живых конкурентов..."):
            try:
                refine = f"""
Переделай ТОЛЬКО пункт 7.
Текущий результат: {st.session_state.result}

Найди 10 живых сайтов конкурентов похожего масштаба.
Проверь каждый через browse_page.
Исключай мёртвые.
Выдай ТОЛЬКО 10 ссылок:
- https://site1.ru
- https://site2.ru
...
"""
                messages = [{"role": "user", "content": refine}]
                resp = call_grok(messages, use_tools=True)
                new_content = resp.get('content', 'Нет ответа')

                old = st.session_state.result
                if "7." in old:
                    parts = old.split("7.", 1)
                    st.session_state.result = parts[0] + "7." + new_content
                else:
                    st.session_state.result = old + "\n\n" + new_content

                st.success("Пункт 7 переделан!")
            except Exception as e:
                st.error(str(e))
    else:
        st.warning("Введи API-ключ")

# Вывод результата
if st.session_state.result:
    st.subheader("Результат анализа:")
    st.markdown(st.session_state.result, unsafe_allow_html=True)
