import streamlit as st
import requests
from bs4 import BeautifulSoup
import json

st.title("Конкурентный Анализатор")

# Поле для ключа Mistral
api_key = st.text_input("API-ключ Mistral", type="password")

if not api_key:
    st.warning("Введите ключ Mistral для анализа.")
    st.info("Получить: https://console.mistral.ai/api-keys")
    st.stop()

if len(api_key) < 20:
    st.error("Ключ слишком короткий. Проверьте копирование.")
    st.stop()

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

# Инструмент просмотра сайта
tools = [{
    "type": "function",
    "function": {
        "name": "browse_page",
        "description": "Посмотреть сайт по URL и извлечь основной текст. Используй для проверки домена и конкурентов.",
        "parameters": {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"]
        }
    }
}]

# Функция просмотра страницы
def browse_page(url):
    try:
        r = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)[:15000]
        return text
    except Exception as e:
        return f"Сайт {url} недоступен: {str(e)}"

# Твой промпт + инструкция отвечать коротко по пунктам + использовать инструмент
base_prompt = """
Ты аналитик сайтов. ОБЯЗАТЕЛЬНО используй инструмент browse_page для просмотра домена и сайтов конкурентов перед ответом.
- Перед анализом просмотри основной домен: проверь страну, регион, доставку, контакты, масштаб.
- Для конкурентов: найди их через поиск, затем просмотри каждый сайт browse_page, проверь живость, тематику, масштаб, регион.
- Исключай доски объявлений и госучреждения.
- Основывайся ТОЛЬКО на реальных данных из интернета. Не додумывай.
- Отвечай строго по пунктам, коротко и по делу.

Пункты:
1. Коммерческий или некоммерческий? (в начале)
2. Страна, регион/город
3. По всей стране или локально? (доставка/выезд)
4. Топ-10 запросов (цифры или фразы для проверки)
5. 10 конкурентов (ссылки + коротко: живой сайт, тематика, масштаб)
6. Мессенджеры (% из топ-10, учти блокировки в РФ)
7. Площадки (% из топ-10, пример Avito)
8. Противоречия или отсутствие данных (если есть)

Анализируй домен: {domain}
"""

domain = st.text_input("Домен сайта (например, example.com):")

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

    try:
        r = requests.post(MISTRAL_API_URL, json=payload, headers=headers, timeout=30)
        r.raise_for_status()
        return r.json()["choices"][0]["message"]
    except requests.exceptions.HTTPError as e:
        if r.status_code == 503:
            raise Exception("Сервер Mistral недоступен (503). Попробуйте через 10–15 мин.")
        raise Exception(f"HTTP ошибка {r.status_code}: {r.text}")
    except Exception as e:
        raise Exception(f"Ошибка Mistral: {str(e)}")

if st.button("Анализ"):
    if domain:
        with st.spinner("Просматриваю сайты и конкурентов..."):
            try:
                prompt = base_prompt.format(domain=domain)
                messages = [{"role": "user", "content": prompt}]

                while True:
                    resp = call_mistral(messages, use_tools=True)
                    messages.append(resp)

                    # Защищённая проверка tool_calls
                    tool_calls = resp.get('tool_calls')
                    if tool_calls and isinstance(tool_calls, list):
                        for tool_call in tool_calls:
                            func = tool_call.get('function')
                            if func and func.get('name') == "browse_page":
                                try:
                                    args = json.loads(func['arguments'])
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
                                        "content": "Ошибка обработки URL"
                                    })
                    else:
                        # Финальный ответ
                        st.session_state.result = resp.get('content', 'Нет ответа от ИИ')
                        st.session_state.refine = False
                        break
            except Exception as e:
                st.error(f"Ошибка: {str(e)}")
    else:
        st.warning("Введите домен")

if st.session_state.result:
    st.subheader("Результат анализа:")
    st.text_area("Анализ", st.session_state.result, height=700)

if st.session_state.result and st.button("Переанализ"):
    with st.spinner("Уточняю сайты и данные..."):
        try:
            refine = base_prompt.format(domain=domain) + f"\nПредыдущий анализ: {st.session_state.result}\nУточни, перепроверь сайты заново."
            messages = [{"role": "user", "content": refine}]

            while True:
                resp = call_mistral(messages, use_tools=True)
                messages.append(resp)

                tool_calls = resp.get('tool_calls')
                if tool_calls and isinstance(tool_calls, list):
                    for tool_call in tool_calls:
                        func = tool_call.get('function')
                        if func and func.get('name') == "browse_page":
                            try:
                                args = json.loads(func['arguments'])
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
                    st.session_state.refine = True
                    break
        except Exception as e:
            st.error(f"Ошибка уточнения: {str(e)}")

if st.session_state.refine:
    st.info("Анализ уточнён с просмотром сайтов")
