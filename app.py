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
        "description": "Проверить сайт по URL. Обязательно используй для каждого конкурента, чтобы убедиться, что он живой и релевантный.",
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
        return f"Сайт {url} мёртвый или недоступен: {str(e)}"

# Промпт без площадок, с акцентом только на живые сайты конкурентов
base_prompt = """
Ты аналитик сайтов. Отвечай ТОЛЬКО по пунктам, коротко, без лишнего текста.
ОБЯЗАТЕЛЬНО используй инструмент browse_page для проверки каждого сайта конкурента.
- Исключай все мёртвые/недоступные сайты.
- Выдавай только живые, реальные и прямые конкуренты (похожего масштаба, не гиганты).
- НЕ упоминай площадки типа Avito, OLX, Wildberries и т.д. — только сайты конкурентов.
- В пункте 7 выдай ТОЛЬКО 10 чистых кликабельных ссылок на живых конкурентов, без описаний!

Структура ответа строго такая:

1. Коммерческий или некоммерческий?
2. Страна, регион/город:
3. По всей стране или локально?
4. Топ-10 запросов:
5. 10 конкурентов (коротко: живой? тематика? масштаб?):
6. Мессенджеры (%):
7. Конкуренты (только 10 ссылок):
   - https://site1.ru
   - https://site2.ru
   ...
8. Противоречия / отсутствие данных:

Анализируй домен: {domain}
"""

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

    try:
        r = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=60)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]
    except Exception as e:
        raise Exception(f"Ошибка Mistral: {str(e)}")

if st.button("Провести анализ"):
    if domain:
        with st.spinner("Анализирую..."):
            try:
                prompt = base_prompt.format(domain=domain)
                messages = [{"role": "user", "content": prompt}]

                while True:
                    resp = call_mistral(messages, use_tools=True)
                    messages.append(resp)

                    tool_calls = resp.get('tool_calls')
                    if tool_calls and isinstance(tool_calls, list):
                        for tool_call in tool_calls:
                            func = tool_call.get('function')
                            if func and func.get('name') == "browse_page":
                                try:
                                    args = json.loads(func.get('arguments', '{}'))
                                    url = args.get('url')
                                    if url:
                                        content = browse_page(url)
                                        messages.append({
                                            "role": "tool",
                                            "tool_call_id": tool_call['id'],
                                            "name": "browse_page",
                                            "content": content
                                        })
                                except:
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tool_call['id'],
                                        "name": "browse_page",
                                        "content": "Ошибка URL"
                                    })
                    else:
                        st.session_state.result = resp.get('content', 'Нет ответа')
                        break
            except Exception as e:
                st.error(f"Ошибка: {str(e)}")
    else:
        st.warning("Введи домен")

# Кнопка переделки только пункта 7
if st.session_state.result and st.button("Переделай только пункт 7 (конкуренты)"):
    with st.spinner("Ищу только живых конкурентов..."):
        try:
            refine_prompt = f"""
            Переделай ТОЛЬКО пункт 7.
            Текущий результат: {st.session_state.result}
            
            Найди 10 живых, рабочих сайтов прямых конкурентов похожего масштаба.
            Проверь каждый через browse_page.
            Исключай мёртвые сайты и площадки (Avito, OLX и т.д.).
            Выдай ТОЛЬКО 10 чистых ссылок:
            - https://site1.ru
            - https://site2.ru
            ...
            """

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
            
            # Заменяем только пункт 7
            old_result = st.session_state.result
            if "7." in old_result:
                parts = old_result.split("7.", 1)
                new_result = parts[0] + "7." + new_content
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
