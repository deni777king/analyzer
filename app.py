import streamlit as st
import requests
from bs4 import BeautifulSoup
import json

st.title("Конкурентный Анализатор")

# Ключ встроен
api_key = "S7ZtbybPJ6eVtI6SXpLrWTxZg5ScQSPR"

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

tools = [{
    "type": "function",
    "function": {
        "name": "browse_page",
        "description": "Просмотреть сайт и извлечь текст. Обязательно используй для проверки домена.",
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
        return f"Сайт недоступен: {str(e)}"

domain = st.text_input("Введи домен сайта (например, zaryadiavto.ru):")

if 'result' not in st.session_state:
    st.session_state.result = ""

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

    r = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=60)
    r.raise_for_status()
    return r.json()["choices"][0]["message"]

# ====================== 1. Основной анализ ======================
if st.button("Провести анализ"):
    if domain:
        with st.spinner("Анализирую..."):
            try:
                # (твой текущий промпт для конкурентов — оставил как был)
                prompt = base_prompt.format(domain=domain)  # если у тебя есть base_prompt
                # ... (логика как раньше)
            except Exception as e:
                st.error(f"Ошибка: {str(e)}")

# ====================== 2. Переделай только пункт 7 ======================
if st.session_state.result and st.button("Переделай только пункт 7 (конкуренты)"):
    # (твоя текущая логика переделки пункта 7 — оставил)

# ====================== 3. НОВАЯ КНОПКА: 3 аудит ======================
if st.button("3 аудит"):
    if domain:
        with st.spinner("Делаю 3 аудит..."):
            try:
                audit_prompt = f"""
Ты делаешь "3 аудит" по шаблону. Посети сайт {domain} через инструмент.

Бонусы:
- Узбекистан: 250 000
- Казахстан: 10 000
- Россия: 1 500

Посещаемость: проверь через данные сайта или укажи "не найдено".
Регион: определи по сайту.
Запросы и % заявок: оцени по нише.

Верни результат СТРОГО в формате:

URL: {domain}
Тематика сайта:
Регион работы:
Потенциал целевых поисковых запросов в месяц:
Потенциальные обращения (3–5%):
Бонус: [сумма по стране]
Краткое пояснение:

Используй инструмент browse_page для точной проверки сайта.
"""

                messages = [{"role": "user", "content": audit_prompt}]
                resp = call_mistral(messages, use_tools=True)
                st.session_state.result = resp.get('content', 'Нет ответа')
            except Exception as e:
                st.error(f"Ошибка 3 аудита: {str(e)}")

# ====================== 4. НОВАЯ КНОПКА: Имиджевый клиент ======================
if st.button("Имиджевый клиент"):
    if domain:
        with st.spinner("Проверяю имиджевость..."):
            try:
                image_prompt = f"""
Проверь сайт {domain} и ответь только одним словом:

Имиджевый или Не имиджевый

Критерии имиджевого клиента:
- Муниципальные учреждения (школы, больницы, администрации, дома культуры)
- Известные городские компании
- Иностранные бренды
- Публичные личности (артисты, эксперты)

Если не соответствует — "Не имиджевый".
Используй инструмент browse_page для проверки сайта.
"""

                messages = [{"role": "user", "content": image_prompt}]
                resp = call_mistral(messages, use_tools=True)
                st.session_state.result = resp.get('content', 'Нет ответа')
            except Exception as e:
                st.error(f"Ошибка: {str(e)}")

# Вывод результата
if st.session_state.result:
    st.subheader("Результат:")
    st.markdown(st.session_state.result, unsafe_allow_html=True)
