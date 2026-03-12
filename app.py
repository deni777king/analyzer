import streamlit as st
import requests
from bs4 import BeautifulSoup
import json

st.title("Конкурентный Анализатор")

# Ключ встроен напрямую
api_key = "S7ZtbybPJ6eVtI6SXpLrWTxZg5ScQSPR"

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

tools = [{
    "type": "function",
    "function": {
        "name": "browse_page",
        "description": "Просмотреть сайт по URL и извлечь текст.",
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
        return soup.get_text(separator=' ', strip=True)[:15000]
    except Exception as e:
        return f"Сайт {url} недоступен: {str(e)}"

def call_mistral(messages, use_tools=False):
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
        r = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]
    except Exception as e:
        raise Exception(f"Ошибка Mistral: {str(e)}")

domain = st.text_input("Введи домен сайта (например, zaryadiavto.ru):")

if 'result' not in st.session_state:
    st.session_state.result = ""

# Основной анализ (твой старый промпт)
if st.button("Провести анализ"):
    if domain:
        with st.spinner("Анализирую..."):
            try:
                prompt = f"""
Ты аналитик сайтов. Отвечай строго по пунктам, коротко.
Используй browse_page для проверки сайтов.

Пункты:
1. Коммерческий или некоммерческий?
2. Страна, регион/город
3. По всей стране или локально?
4. Топ-10 запросов
5. 10 конкурентов (коротко)
6. Мессенджеры (%)
7. Конкуренты (только 10 ссылок):
   - https://site1.ru
   - https://site2.ru
   ...
8. Противоречия

Анализируй: {domain}
"""
                messages = [{"role": "user", "content": prompt}]
                resp = call_mistral(messages, use_tools=True)
                st.session_state.result = resp.get('content', 'Нет ответа')
            except Exception as e:
                st.error(f"Ошибка: {str(e)}")
    else:
        st.warning("Введи домен")

# Кнопка 3 аудит
if st.button("3 аудит"):
    if domain:
        with st.spinner("Делаю 3 аудит..."):
            try:
                audit_prompt = f"""
Проведи "3 аудит" по шаблону. Посети сайт {domain}.

Бонусы:
- Узбекистан: 250 000
- Казахстан: 10 000
- Россия: 1 500

Посещаемость: проверь данные сайта.
Регион: по сайту.
Запросы: оцени по нише.

Формат ответа:
URL: {domain}
Тематика:
Регион:
Потенциал запросов в месяц:
Обращения (3–5%):
Бонус:
Пояснение:
"""

                messages = [{"role": "user", "content": audit_prompt}]
                resp = call_mistral(messages, use_tools=True)
                st.session_state.result = resp.get('content', 'Нет ответа')
            except Exception as e:
                st.error(f"Ошибка 3 аудита: {str(e)}")
    else:
        st.warning("Введи домен")

# Кнопка Имиджевый клиент
if st.button("Имиджевый клиент"):
    if domain:
        with st.spinner("Проверяю имиджевость..."):
            try:
                image_prompt = f"""
Проверь сайт {domain} и ответь одним словом:

Имиджевый или Не имиджевый

Критерии имиджевого:
- Муниципальные учреждения (школы, больницы, администрации)
- Известные городские компании
- Иностранные бренды
- Публичные личности

Если не соответствует — "Не имиджевый".
Используй browse_page для проверки.
"""

                messages = [{"role": "user", "content": image_prompt}]
                resp = call_mistral(messages, use_tools=True)
                st.session_state.result = resp.get('content', 'Нет ответа')
            except Exception as e:
                st.error(f"Ошибка: {str(e)}")
    else:
        st.warning("Введи домен")

# Вывод результата
if st.session_state.result:
    st.subheader("Результат:")
    st.markdown(st.session_state.result, unsafe_allow_html=True)
