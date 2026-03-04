import streamlit as st
import requests
from bs4 import BeautifulSoup  # Для парсинга страниц

st.title("Конкурентный Анализатор")

# Поле для ввода API-ключа Mistral
api_key = st.text_input("Введи свой API-ключ Mistral (начинается с m- или просто токен)", type="password")

if not api_key:
    st.warning("Введите свой API-ключ Mistral, чтобы начать анализ.")
    st.info("Ключ можно получить здесь: https://console.mistral.ai/api-keys")
    st.stop()

# URL API Mistral
MISTRAL_API_URL = "https://api.mistral.ai/v1/chat/completions"

# Определение инструмента для просмотра страниц (browsing)
tools = [
    {
        "type": "function",
        "function": {
            "name": "browse_page",
            "description": "Просмотреть и извлечь текст с сайта по URL. Используй это для анализа домена или конкурентов, чтобы получить актуальную информацию.",
            "parameters": {
                "type": "object",
                "properties": {
                    "url": {"type": "string", "description": "URL сайта для просмотра"}
                },
                "required": ["url"]
            }
        }
    }
]

# Функция для выполнения tool browse_page (извлекает текст с страницы)
def browse_page(url):
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
        # Извлекаем основной текст (без тегов)
        text = soup.get_text(separator=' ', strip=True)
        # Ограничиваем длину, чтобы не превысить токены
        return text[:10000]  # Максимум 10000 символов
    except Exception as e:
        return f"Ошибка при просмотре страницы: {str(e)}"

# Твой промпт с инструкциями для использования инструментов
base_prompt = """
Ты должен использовать доступные инструменты (особенно browse_page) для просмотра и анализа сайтов. 
- Перед анализом ОБЯЗАТЕЛЬНО используй browse_page для посещения указанного домена, чтобы получить актуальную информацию о стране, регионе, работе (локально/по стране), тематике, доставке.
- Для конкурентов: найди их сайты через поиск, затем используй browse_page для каждого конкурента, чтобы проверить живость сайта, тематику, масштаб (команда, штат), регион.
- Основывайся ТОЛЬКО на данных из интернета (из инструментов). Если данных нет — скажи об этом, не додумывай.
- Для пункта 1.3 (запросы): используй поиск в интернете (Яндекс Вордстат или Google Ads данные), чтобы найти актуальные цифры или фразы.
- Для пункта 1.4 и 1.7: найди конкурентов через поиск, проверь каждый сайт browse_page, исключи доски объявлений и госучреждения, выбери 10 похожих по силе.
- Для 1.5 и 1.6: используй поиск для данных о популярных мессенджерах/площадках в стране, учти блокировки.

Выполни эти пункты:
1.1 Страна, регион/город
1.2 Работает ли по всей стране или же локально (это важно смотри на тематику/доставку/выезд по стране/региону)
1.3 Топ 10 точных запросов в месяц в Яндекс Вордстат (если это сайты РФ или Белоруссии) или ads.google (если сайты Узбекские и Казахские) так же смотри внимательно на тематику сайты а не на домен и еще давай топ запросы только по городу или региону но если доставка по стране/онлайн услуги то давай запросы по стране так же напиши это в столбик с количеством просмотров в месяц если информации нету то дай топ 10 фраз для запроса что бы я сам проверил
1.4 Далее ищешь самых ближайших прямых конкурентов у которых есть живые рабочие сайты с подходящей тематикой (город/область и на крайний случай по стране ) так же смотри на то чтобы конкуренты были одинаковой силы (пример наш сайт это команда из 10 человек а конкурент компания со штатом сотрудников из 10 тыщ.) так же не когда не бери за конкурентов доски обьявлений и государственные учериждения 
1.5 Укажи какие мессенджеры подойдут для нашего сайты для привлечения клиентов и т.д в процентном отображении из топ 10 (но обрати внимание что в РФ заблокированы многие мессенджеры их ты не указываешь и так во всех странах ) (так же смотри на нишу подойдет или данный мессенджер/площадка) 
1.6 Делаешь все то же самое что в пункте 1.5 но с площадками пример авито  
1.7 выдай сайты конкурентов именно ссылкой штук 10 то есть топ 10 
1.8 в самом начале напиши это коммерческий или некоммерческий это тоже важно 
1.9 ничего не додумывай основываясь только на той информации которая есть в интернете (если есть противоречия напиши их рядом с коммерческий  ) 
и если меня что то не устроит из пунктов я буду тебе писать пункт который нужно переделать (только то пункт который я укажу)
"""

domain = st.text_input("Введи домен сайта (например, example.com):")

if 'analysis_result' not in st.session_state:
    st.session_state.analysis_result = ""
if 'refine' not in st.session_state:
    st.session_state.refine = False

def call_mistral(messages, tools=None):
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
    if tools:
        payload["tools"] = tools

    response = requests.post(MISTRAL_API_URL, json=payload, headers=headers)
    response.raise_for_status()
    return response.json()["choices"][0]["message"]

if st.button("Провести анализ"):
    if domain:
        with st.spinner("Анализ выполняется с просмотром сайтов..."):
            try:
                initial_prompt = base_prompt + f"\n\nАнализируй этот домен: {domain}"
                messages = [{"role": "user", "content": initial_prompt}]

                while True:
                    response = call_mistral(messages, tools)
                    messages.append(response)

                    if 'tool_calls' in response:
                        for tool_call in response['tool_calls']:
                            func_name = tool_call['function']['name']
                            args = json.loads(tool_call['function']['arguments'])
                            if func_name == "browse_page":
                                url = args['url']
                                result = browse_page(url)
                                messages.append({
                                    "role": "tool",
                                    "tool_call_id": tool_call['id'],
                                    "content": result
                                })
                    else:
                        st.session_state.analysis_result = response['content']
                        st.session_state.refine = False
                        break
            except Exception as e:
                st.error(f"Ошибка: {str(e)}. Проверь ключ, баланс или интернет.")
    else:
        st.warning("Введи домен сначала!")

if st.session_state.analysis_result:
    st.subheader("Результат анализа от Mistral:")
    st.text_area("Подробный анализ:", st.session_state.analysis_result, height=500)

if st.session_state.analysis_result and st.button("Переанализировать (более точно)"):
    with st.spinner("Переанализ выполняется с просмотром сайтов..."):
        try:
            refine_prompt = base_prompt + f"\n\nАнализируй этот домен: {domain}\nПредыдущий анализ: {st.session_state.analysis_result}\nПереанализируй более детально и точно, исправь ошибки, основываясь только на интернете."
            messages = [{"role": "user", "content": refine_prompt}]

            while True:
                response = call_mistral(messages, tools)
                messages.append(response)

                if 'tool_calls' in response:
                    for tool_call in response['tool_calls']:
                        func_name = tool_call['function']['name']
                        args = json.loads(tool_call['function']['arguments'])
                        if func_name == "browse_page":
                            url = args['url']
                            result = browse_page(url)
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call['id'],
                                "content": result
                            })
                else:
                    st.session_state.analysis_result = response['content']
                    st.session_state.refine = True
                    break
        except Exception as e:
            st.error(f"Ошибка: {str(e)}.")

if st.session_state.refine:
    st.info("Анализ был уточнён на основе предыдущего!")