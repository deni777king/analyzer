import streamlit as st
import requests
from bs4 import BeautifulSoup
import json

st.title("Конкурентный Анализатор")

# Поле ввода API-ключа (с твоим новым ключом по умолчанию)
api_key = st.text_input(
    "Введи API-ключ (например Mistral или xAI)",
    value="uvKEJOMuk6YpTTHdCXi7zdhTDWe0Jbvb",
    type="password"
)

if not api_key:
    st.warning("Введите API-ключ, чтобы начать анализ.")
    st.info("Ключ можно получить в консоли твоего провайдера ИИ.")
    st.stop()

# Эндпоинт Mistral (можно потом заменить на xAI или другой)
API_URL = "https://api.mistral.ai/v1/chat/completions"

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

def call_api(messages, use_tools=False):
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    payload = {
        "model": "mistral-large-latest",
        "messages": messages,
        "temperature": 0.7,
        "max_tokens": 4096
    }
    if use_tools:
        payload["tools"] = tools

    try:
        r = requests.post(API_URL, json=payload, headers=headers, timeout=90)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]
    except requests.exceptions.HTTPError as e:
        try:
            error_detail = r.json().get("error", {}).get("message", str(e))
        except:
            error_detail = str(e)
        st.error(f"HTTP ошибка {r.status_code}: {error_detail}")
        st.stop()
    except requests.exceptions.Timeout:
        st.error("Таймаут соединения (90 сек). Сервер не отвечает.")
        st.stop()
    except Exception as e:
        st.error(f"Ошибка связи: {str(e)}")
        st.stop()

domain = st.text_input("Введи домен сайта (например, zaryadiavto.ru):")

if 'result' not in st.session_state:
    st.session_state.result = ""

# Основной анализ
if st.button("Провести анализ"):
    if domain:
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
                resp = call_api(messages, use_tools=True)
                st.session_state.result = resp.get('content', 'Нет ответа')
            except Exception as e:
                st.error(str(e))
    else:
        st.warning("Введи домен")

# Переделай пункт 7
if st.session_state.result and st.button("Переделай пункт 7 (конкуренты)"):
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
            resp = call_api(messages, use_tools=True)
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

# Вывод результата
if st.session_state.result:
    st.subheader("Результат анализа:")
    st.markdown(st.session_state.result, unsafe_allow_html=True)
