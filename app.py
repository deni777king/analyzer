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
        "description": "Посмотреть сайт и проверить, живой ли он. Обязательно используй для конкурентов.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"]
        }
    }
}]

def browse_page(url):
    try:
        r = requests.get(url, timeout=12, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)[:10000]
        return text if len(text) > 100 else "Сайт пустой или недоступен"
    except:
        return "Сайт недоступен или не работает"

base_prompt = """
Ты аналитик сайтов. ОБЯЗАТЕЛЬНО используй инструмент browse_page для проверки живости каждого сайта конкурента.
- Исключай все неработающие сайты.
- Выдавай только живые, реальные и близкие конкуренты (похожего масштаба, не гиганты).
- Отвечай строго по пунктам, коротко.

Пункты:
1. Коммерческий или некоммерческий?
2. Страна, регион/город
3. По всей стране или локально?
4. Топ-10 запросов
5. 10 конкурентов (коротко: живой сайт? тематика? масштаб?)
6. Мессенджеры (%)
7. Площадки (%)
8. Противоречия

Анализируй домен: {domain}
"""

domain = st.text_input("Введи домен сайта:")

if 'result' not in st.session_state:
    st.session_state.result = ""

if st.button("Провести анализ"):
    if domain:
        with st.spinner("Анализирую..."):
            try:
                prompt = base_prompt.format(domain=domain)
                messages = [{"role": "user", "content": prompt}]
                # ... (тот же цикл с tool calls, как раньше)
                # (я сократил для удобства, но логика та же)
            except Exception as e:
                st.error(f"Ошибка: {str(e)}")
    else:
        st.warning("Введи домен")

# === НОВАЯ КНОПКА: Переделать только пункт 7 ===
if st.session_state.result and st.button("Переделай только пункт 7 (конкуренты)"):
    with st.spinner("Ищу только живых и близких конкурентов..."):
        try:
            refine_prompt = f"""
            Переделай ТОЛЬКО пункт 7.
            Текущий результат: {st.session_state.result}
            
            Найди 10 живых, рабочих сайтов прямых конкурентов похожего масштаба.
            Обязательно проверь каждый сайт через инструмент browse_page.
            Выдай ТОЛЬКО чистые кликабельные ссылки, без описаний.
            Формат:
            7. Конкуренты:
            - https://site1.ru
            - https://site2.ru
            ...
            """

            # Здесь вызываем Mistral только для перегенерации пункта 7
            headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
            payload = {
                "model": "mistral-large-latest",
                "messages": [{"role": "user", "content": refine_prompt}],
                "tools": tools,
                "temperature": 0.6
            }
            r = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=60)
            r.raise_for_status()
            new_content = r.json()["choices"][0]["message"]["content"]
            
            # Заменяем только пункт 7 в результате
            old_result = st.session_state.result
            if "7." in old_result:
                new_result = old_result.split("7.")[0] + new_content
            else:
                new_result = old_result + "\n\n" + new_content
                
            st.session_state.result = new_result
            st.success("Пункт 7 переделан!")
        except Exception as e:
            st.error(f"Ошибка переделки: {str(e)}")

# Вывод результата
if st.session_state.result:
    st.subheader("Результат анализа:")
    st.markdown(st.session_state.result, unsafe_allow_html=True)
