import streamlit as st
import requests
from bs4 import BeautifulSoup
import json

st.title("Конкурентный Анализатор")

# Поле для ввода API-ключа Mistral
api_key = st.text_input("Введи свой API-ключ Mistral", type="password")

if not api_key:
    st.warning("Введите ключ Mistral, чтобы начать анализ.")
    st.info("Получить ключ: https://console.mistral.ai/api-keys")
    st.stop()

# Проверка ключа на валидный вид (примерно)
if len(api_key) < 20:
    st.error("Ключ выглядит слишком коротким. Проверьте, правильно ли скопировали.")
    st.stop()

MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

# Инструмент для просмотра сайтов
tools = [{
    "type": "function",
    "function": {
        "name": "browse_page",
        "description": "Посмотреть содержимое сайта по URL и извлечь текст. Используй для анализа домена и сайтов конкурентов.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "Полный URL сайта"}
            },
            "required": ["url"]
        }
    }
}]

# Функция просмотра страницы
def browse_page(url):
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
        r = requests.get(url, timeout=12, headers=headers)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, 'html.parser')
        text = soup.get_text(separator=' ', strip=True)
        return text[:12000]  # Ограничим, чтобы не превысить токены
    except Exception as e:
        return f"Не удалось открыть сайт {url}: {str(e)}"

# Твой промпт с инструкцией использовать инструмент
base_prompt = """
Ты аналитик сайтов. ОБЯЗАТЕЛЬНО используй инструмент browse_page для просмотра домена и сайтов конкурентов перед ответом.
- Перед анализом просмотри основной домен: проверь страну, регион, доставку, контакты, масштаб.
- Для конкурентов: найди их через поиск, затем просмотри каждый сайт browse_page, проверь живость, тематику, масштаб (команда/штат), регион.
- Исключай доски объявлений и госучреждения.
- Основывайся ТОЛЬКО на реальных данных из интернета (из инструментов). Не додумывай.
- Для запросов (1.3): ищи актуальные данные в Яндекс Вордстат / Google Ads через поиск.
- Если сайт не открывается — укажи это.

Пункты анализа:
1.1 Страна, регион/город
1.2 Работает ли по всей стране или локально
1.3 Топ 10 запросов в месяц (с цифрами или фразами для проверки)
1.4 10 ближайших конкурентов (проверь каждый сайт)
1.5 Подходящие мессенджеры в % (учти блокировки в РФ)
1.6 Подходящие площадки (Avito и др.) в %
1.7 Ссылки на 10 конкурентов
1.8 Коммерческий или некоммерческий
1.9 Только факты из интернета, противоречия указывай
"""

domain = st.text_input("Введи домен сайта (например, example.com):")

if 'result' not in st.session_state:
    st.session_state.result = ""
if 'refine' not in st.session_state:
    st.session_state.refine = False

def call_mistral(messages, use_tools=False):
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json"
    }
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
            raise Exception("Сервер Mistral временно недоступен (503). Попробуйте через 5–15 минут.")
        elif r.status_code == 429:
            raise Exception("Лимит запросов исчерпан. Подождите или пополните баланс.")
        else:
            raise Exception(f"HTTP ошибка {r.status_code}: {r.text}")
    except Exception as e:
        raise Exception(f"Ошибка связи с Mistral: {str(e)}")

if st.button("Провести анализ"):
    if domain:
        with st.spinner("Анализирую сайты и конкурентов..."):
            try:
                prompt = base_prompt + f"\n\nАнализируй домен: {domain}"
                messages = [{"role": "user", "content": prompt}]

                while True:
                    resp = call_mistral(messages, use_tools=True)
                    messages.append(resp)

                    # Проверка на tool_calls
                    if 'tool_calls' in resp and resp['tool_calls'] is not None:
                        for tool_call in resp['tool_calls']:
                            if tool_call.get('function', {}).get('name') == "browse_page":
                                try:
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
                                except Exception as e:
                                    messages.append({
                                        "role": "tool",
                                        "tool_call_id": tool_call['id'],
                                        "name": "browse_page",
                                        "content": f"Ошибка обработки инструмента: {str(e)}"
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
    st.text_area("Анализ", st.session_state.result, height=600)

if st.session_state.result and st.button("Переанализировать"):
    with st.spinner("Уточняю данные и сайты..."):
        try:
            refine = base_prompt + f"\nДомен: {domain}\nПредыдущий анализ: {st.session_state.result}\nУточни, перепроверь сайты."
            messages = [{"role": "user", "content": refine}]

            while True:
                resp = call_mistral(messages, use_tools=True)
                messages.append(resp)

                if 'tool_calls' in resp and resp['tool_calls'] is not None:
                    for tool_call in resp['tool_calls']:
                        if tool_call.get('function', {}).get('name') == "browse_page":
                            try:
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
                            except:
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call['id'],
                                    "name": "browse_page",
                                    "content": "Ошибка инструмента"
                                })
                else:
                    st.session_state.result = resp.get('content', 'Нет ответа')
                    st.session_state.refine = True
                    break
        except Exception as e:
            st.error(f"Ошибка уточнения: {str(e)}")

if st.session_state.refine:
    st.info("Анализ уточнён с дополнительным просмотром сайтов")
