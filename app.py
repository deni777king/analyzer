import streamlit as st
import requests
from bs4 import BeautifulSoup
import json

st.title("Конкурентный Анализатор")

# Ключ встроен напрямую
api_key = "S7ZtbybPJ6eVtI6SXpLrWTxZg5ScQSPR"

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

# Инструмент просмотра сайтов
tools = [{
    "type": "function",
    "function": {
        "name": "browse_page",
        "description": "Посмотреть сайт и извлечь текст. Используй для анализа домена и конкурентов.",
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
        return soup.get_text(separator=' ', strip=True)[:15000]
    except Exception as e:
        return f"Сайт недоступен: {str(e)}"

# Обновлённый промпт — теперь ИИ выдаёт конкурентов только ссылками
base_prompt = """
Ты аналитик сайтов. Используй инструмент browse_page для просмотра основного домена и сайтов конкурентов.
Отвечай строго по пунктам, коротко, без воды.

Пункты:
1. Коммерческий или некоммерческий?
2. Страна, регион/город
3. По всей стране или локально?
4. Топ-10 запросов (цифры или фразы для проверки)
5. 10 конкурентов (только коротко: живой сайт? тематика? масштаб?)
6. Мессенджеры (% из топ-10, учти блокировки)
7. Площадки (% из топ-10)
8. Противоречия / отсутствие данных

Особо важно: в пункте 7 выдай только чистые кликабельные ссылки на 10 конкурентов, без описаний и лишнего текста.

Анализируй домен: {domain}
"""

domain = st.text_input("Введи домен сайта (например, example.com):")

if 'result' not in st.session_state:
    st.session_state.result = ""
if 'refine' not in st.session_state:
    st.session_state.refine = False

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

if st.button("Провести анализ"):
    if domain:
        with st.spinner("Анализирую сайты и конкурентов..."):
            try:
                prompt = base_prompt.format(domain=domain)
                messages = [{"role": "user", "content": prompt}]

                while True:
                    resp = call_mistral(messages, use_tools=True)
                    messages.append(resp)

                    tool_calls = resp.get('tool_calls')
                    if tool_calls and isinstance(tool_calls, list):
                        for tool_call in tool_calls:
                            if tool_call.get('function', {}).get('name') == "browse_page":
                                args = json.loads(tool_call['function']['arguments'])
                                url = args.get('url')
                                if url:
                                    content = browse_page(url)
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tool_call['id'],
                                        "name": "browse_page",
                                        "content": content
                                    })
                    else:
                        st.session_state.result = resp.get('content', 'Нет ответа')
                        st.session_state.refine = False
                        break
            except Exception as e:
                st.error(f"Ошибка: {str(e)}")
    else:
        st.warning("Введи домен")

if st.session_state.result:
    st.subheader("Результат анализа:")
    st.text_area("Анализ", st.session_state.result, height=700)

if st.session_state.result and st.button("Переанализ"):
    with st.spinner("Уточняю..."):
        try:
            refine = base_prompt.format(domain=domain) + f"\nПредыдущий анализ: {st.session_state.result}\nУточни данные."
            messages = [{"role": "user", "content": refine}]

            while True:
                resp = call_mistral(messages, use_tools=True)
                messages.append(resp)

                tool_calls = resp.get('tool_calls')
                if tool_calls and isinstance(tool_calls, list):
                    for tool_call in tool_calls:
                        if tool_call.get('function', {}).get('name') == "browse_page":
                            args = json.loads(tool_call['function']['arguments'])
                            url = args.get('url')
                            if url:
                                content = browse_page(url)
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call['id'],
                                    "name": "browse_page",
                                    "content": content
                                })
                else:
                    st.session_state.result = resp.get('content', 'Нет ответа')
                    st.session_state.refine = True
                    break
        except Exception as e:
            st.error(f"Ошибка: {str(e)}")

if st.session_state.refine:
    st.info("Анализ уточнён")
