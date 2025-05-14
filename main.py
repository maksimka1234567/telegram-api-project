# импортируем все необходимые модули и библиотеки
import requests
from io import BytesIO
from PIL import Image
import logging
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, InputMediaPhoto
from telegram.ext import CommandHandler, MessageHandler, ConversationHandler, ContextTypes, \
    Application, filters, CallbackQueryHandler
import sqlite3

# Запускаем логгирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG
)

logger = logging.getLogger(__name__)
WAITING_FOR_GEOCODE_INPUT = 1  # переменные для ожидания ввода текста после сообщений бота
WAITING_FOR_FIRST_OBJECT = 2
WAITING_FOR_SECOND_OBJECT = 3
WAITING_FOR_WEATHER_INPUT = 4
WAITING_FOR_TYPE_INPUT = 5
WAITING_FOR_PLACE_INPUT = 6
API_KEY = '8013b162-6b42-4997-9691-77b7074026e0'  # ключ для yandex api
WEATHER_KEY = 'c0c8ea3bf67266e89078d8488a2ac94d'  # ключ для openweathermap api


# Формирование OverpassQL-запроса (для поиска мест поблизости в радиусе 10 км)
def get_overpass_query(query: str, lat: float, lon: float, radius: int = 10000) -> str:
    osm_key_value = f'name~"{query.lower()}",i'
    overpass_query = f"""
[out:json][timeout:25];
node[{osm_key_value}](around:{radius},{lat},{lon});
out body;
"""
    return overpass_query


def get_coords(user_input):  # получение координат объекта
    geocoder_request = f'http://geocode-maps.yandex.ru/1.x/?apikey={API_KEY}&geocode={user_input}&format=json'
    response = requests.get(geocoder_request)
    data = response.json()
    coordinates = data['response']['GeoObjectCollection']['featureMember'][0]['GeoObject']['Point']['pos']
    return coordinates


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):  # приветствие бота
    await update.message.reply_text(
        "Привет! Я бот для поиска информации о погоде, географических объектах, местах поблизости и для построения маршрутов.")
    await help_command(update, context)


# Обработчик команды для справки по боту
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Доступные команды:\n"
        "/start - запуск\n"
        "/help - справка\n"
        "/geocode - поиск объекта\n"
        "/route - построение маршрута\n"
        "/weather - информация о погоде\n"
        "/search - поиск мест поблизости\n"
        "/history - история запросов"
    )


# Начало диалога для поиска объекта
async def start_geocode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Введите название географического объекта:')
    return WAITING_FOR_GEOCODE_INPUT


# Обработка ввода пользователя и поиск объекта
async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        logger.debug("Получено обновление без текстового сообщения")
        return

    user_input = update.message.text
    user_id = update.message.from_user.id
    chat_id = update.message.chat_id

    try:  # запрос к введённому месту, получение его координат и отображение на статической карте в виде фото с ссылкой на Яндекс.Карты
        longitude, latitude = map(float, get_coords(user_input).split())
        # Вычисляем bbox для одного объекта (небольшая область вокруг точки)
        delta = 0.01  # Размер области вокруг точки (широта/долгота)
        bbox = f"{longitude - delta},{latitude - delta}~{longitude + delta},{latitude + delta}"
        geocoder_request = [
            f"http://yandex.ru/maps/?ll={longitude},{latitude}&z=15&l=map&pt={longitude},{latitude},pm2rdm",
            f"http://static-maps.yandex.ru/1.x/?ll={longitude},{latitude}&bbox={bbox}&l=map&pt={longitude},{latitude},pm2rdm"
        ]

        keyboard = [
            [InlineKeyboardButton("Открыть карту", url=geocoder_request[0])]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        response1 = requests.get(geocoder_request[1])
        image_data = response1.content
        image = Image.open(BytesIO(image_data))
        image.save("img.png")

        with open("img.png", 'rb') as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=f"Найден объект: {user_input}\nНажмите на кнопку, чтобы открыть карту:",
                reply_markup=reply_markup
            )
        con = sqlite3.connect('requests.db')
        # Считываем бинарные данные из файла
        with open("img.png", "rb") as file:
            photo_blob = file.read()
        # Создание курсора
        cur = con.cursor()
        cur.execute('''INSERT INTO history (photo, text, link, user_id) VALUES (?, ?, ?, ?)''', (
            photo_blob, f"Найден объект: {user_input}\nНажмите на кнопку, чтобы открыть карту:", geocoder_request[0],
            user_id))
        con.commit()
        con.close()
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Произошла ошибка: {e}")
        await update.message.reply_text('Не удаётся найти данный географический объект. Попробуйте снова.')
        await update.message.reply_text('Введите название географического объекта:')
        return WAITING_FOR_GEOCODE_INPUT


# кнопки для выбора варианта при вызове команды /history
async def show_history_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Показать историю погоды", callback_data='weather_history')],
        [InlineKeyboardButton("Показать историю карт", callback_data='map_history')],
        [InlineKeyboardButton("Показать всю историю", callback_data='all_history')],
        [InlineKeyboardButton("Очистить всю историю", callback_data='clear_history')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите один из предложенных вариантов:', reply_markup=reply_markup)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):  # обработчик этих кнопок
    query = update.callback_query
    await query.answer()

    history_type = query.data

    if history_type == 'weather_history':
        await history(query, context, type=1)
    elif history_type == 'map_history':
        await history(query, context, type=2)
    elif history_type == 'all_history':
        await history(query, context, type=3)
    elif history_type == 'clear_history':
        await history(query, context, type=4)


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE,
                  type):  # обработка сообщений бота и запросов в базу данных после нажатия кнопки
    user_id = update.from_user  # чтобы получать доступ к истории конкретного пользователя
    con = sqlite3.connect('requests.db')
    cur = con.cursor()

    if type == 4:
        cur.execute('''DELETE from history WHERE user_id = ?''', (user_id,))  # очистить историю данного пользователя
        con.commit()
        await update.message.reply_text('История успешно очищена.')
        con.close()
        return

    elif type == 1:
        all_requests = cur.execute(
            '''SELECT * FROM history WHERE link LIKE "https://openweathermap.org/city/%" AND user_id = ?''',
            (user_id,)
        ).fetchall()  # история запросов погоды
    elif type == 2:
        all_requests = cur.execute(
            '''SELECT * FROM history WHERE link NOT LIKE "https://openweathermap.org/city/%" AND user_id = ?''',
            (user_id,)
        ).fetchall()  # история запросов карт
    elif type == 3:
        all_requests = cur.execute('''SELECT * from history WHERE user_id = ?''', (user_id,)).fetchall()  # вся история

    if len(all_requests) == 0:  # в случае отсутствия истории
        if type == 1:
            await update.message.reply_text('В последнее время не было запросов на получение информации о погоде.')
        elif type == 2:
            await update.message.reply_text('В последнее время не было запросов на получение Яндекс.Карт.')
        elif type == 3:
            await update.message.reply_text('В последнее время не было запросов.')
        con.close()
        return

    if type == 1:
        await update.message.reply_text('Вот история запросов на получение информации о погоде:')
    elif type == 2:
        await update.message.reply_text('Вот история запросов Яндекс.Карт:')
    elif type == 3:
        await update.message.reply_text('Вот вся история запросов:')

    all_requests.reverse()
    context.user_data[
        'history_results'] = all_requests  # для сохранения списка и последующей отправки сообщения с кнопками навигации
    context.user_data['current_history_index'] = 0
    con.close()
    await send_history_result(update, context, index=0)
    return ConversationHandler.END


async def send_history_result(update: Update, context: ContextTypes.DEFAULT_TYPE,
                              index):  # отправка нужного результата в зависимости от типа запроса к истории
    results = context.user_data.get('history_results', [])  # получение нужного списка с историей из данных в боте
    current_index = index
    item = results[current_index]
    photo_blob = item[1]
    caption = item[2]
    link = item[3]

    # Используем BytesIO вместо временного файла
    photo_io = Image.open(BytesIO(photo_blob))
    photo_io.save('img.png')

    keyboard = [[InlineKeyboardButton("Открыть подробную информацию", url=link)]]

    nav_buttons = []  # кнопки навигации
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"hist_prev:{current_index}"))
    nav_buttons.append(InlineKeyboardButton(f"{current_index + 1} / {len(results)}", callback_data="noop"))
    if current_index < len(results) - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ Вперёд", callback_data=f"hist_next:{current_index}"))

    keyboard.append(nav_buttons)
    reply_markup = InlineKeyboardMarkup(keyboard)
    with open('img.png', 'rb') as photo:  # отправка текущего запроса
        if isinstance(update, CallbackQuery):  # просто изменение сообщения при нажатии на кнопку навигации
            media = InputMediaPhoto(media=photo, caption=caption)
            await update.edit_message_media(media=media, reply_markup=reply_markup)
        else:  # отправка сообщения в первый раз
            await context.bot.send_photo(
                chat_id=update.effective_chat.id,
                photo=photo,
                caption=caption,
                reply_markup=reply_markup
            )


async def handle_history_navigation(update: Update,
                                    context: ContextTypes.DEFAULT_TYPE):  # обработчик перелистывания запросов в истории поиска в одном сообщении бота
    query = update.callback_query
    await query.answer()
    data = query.data
    action, index = data.split(':')
    index = int(index)
    results = context.user_data.get('history_results')

    if not results:
        await query.message.reply_text("Результаты не найдены.")
        return

    if action == 'hist_next':
        new_index = index + 1
    elif action == 'hist_prev':
        new_index = index - 1
    else:
        return

    if 0 <= new_index < len(results):  # следующий/предыдущий запрос
        context.user_data['current_history_index'] = new_index
        await send_history_result(query, context, index=new_index)


async def input_place(update: Update,
                      context: ContextTypes.DEFAULT_TYPE):  # начало диалога с ботом при использовании функции для поиска поблизости
    await update.message.reply_text('Введите название географического объекта для поиска объектов рядом с ним:')
    return WAITING_FOR_PLACE_INPUT


async def input_type(update: Update,
                     context: ContextTypes.DEFAULT_TYPE):  # обработка введённого места и ожидание ввода типа искомых объектов рядом
    if not update.message:
        logger.debug("Получено обновление без текстового сообщения")
        return

    user_input = update.message.text
    try:
        longitude, latitude = map(float, get_coords(user_input).split())
        context.user_data['place'] = [(longitude, latitude), user_input]  # сохраняем координаты в память бота
        await update.message.reply_text('Объект найден. Введите тип объекта, который вы хотите найти рядом с ним:')
        return WAITING_FOR_TYPE_INPUT
    except Exception as e:
        logger.error(f"Произошла ошибка при обработке объекта: {e}")
        await update.message.reply_text('Не удаётся найти данный географический объект. Попробуйте снова.')
        await update.message.reply_text('Введите название географического объекта для поиска объектов рядом с ним:')
        return WAITING_FOR_PLACE_INPUT


async def search(update,
                 context):  # Обработчик введённых данных и поиск нужных мест поблизости в радиусе 10 км через overpass api
    if not update.message:
        logger.debug("Получено обновление без текстового сообщения")
        return

    user_input = update.message.text.strip()
    lat, lon = context.user_data.get('place')[0]  # получение координат из памяти бота
    try:
        await update.message.reply_text("Выполняется поиск мест поблизости...")
        # Формируем OverpassQL-запрос
        overpass_ql = get_overpass_query(user_input, lon, lat)
        overpass_url = "https://overpass-api.de/api/interpreter"

        response = requests.post(overpass_url, data={'data': overpass_ql})

        if response.status_code != 200:
            logger.error(f"Overpass API вернул статус: {response.status_code}")
            await update.message.reply_text("Ошибка сервера. Попробуйте позже.")
            return WAITING_FOR_TYPE_INPUT

        data = response.json()
        if not data.get("elements"):
            logger.warning("Ничего не найдено в указанной области.")
            await update.message.reply_text("Ничего не найдено. Попробуйте другой тип объекта.")
            return WAITING_FOR_TYPE_INPUT

        results = []
        for element in data["elements"]:  # получение и обработка всех нужных мест поблизости
            name = element["tags"].get("name", 'Без названия')
            coords = (element["lon"], element["lat"])
            distance = ((coords[0] - lon) ** 2 + (coords[1] - lat) ** 2) ** 0.5
            results.append((name, coords, distance))
        results.sort(key=lambda x: x[2])
        await update.message.reply_text(
            f"Вблизи от места '{context.user_data.get('place')[1]}' найдены следующие объекты типа '{user_input}':")
        # Сохраняем результаты в контекст пользователя
        context.user_data['search_results'] = results  # сохранение для последующей отправки с кнопками навигации
        context.user_data['current_index'] = 0
        context.user_data['type'] = user_input

        # Отправляем первый результат
        await send_search_result(update, context, index=0)
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при поиске через Overpass API: {e}")
        await update.message.reply_text("Не удалось выполнить поиск. Попробуйте снова.")
        return WAITING_FOR_TYPE_INPUT


async def send_search_result(update: Update, context: ContextTypes.DEFAULT_TYPE,
                             index):  # отправка результатов поиска поблизости с кнопками для навигации
    results = context.user_data.get('search_results', [])
    type = context.user_data.get('type', "")
    current_index = index
    item = results[current_index]
    name = item[0]
    lon, lat = item[1]
    # отображение полученных результатов на фото со статической картой, описанием и ссылкой
    geocoder_request = f'http://geocode-maps.yandex.ru/1.x/?apikey={API_KEY}&geocode={lon},{lat}&format=json'
    response = requests.get(geocoder_request)
    json_response = response.json()
    address = \
        json_response["response"]["GeoObjectCollection"]["featureMember"][0]["GeoObject"]["metaDataProperty"][
            "GeocoderMetaData"]['text']
    # Вычисляем bbox для одного объекта (небольшая область вокруг точки)
    delta = 0.01  # Размер области вокруг точки (широта/долгота)
    bbox = f"{lon - delta},{lat - delta}~{lon + delta},{lat + delta}"
    response1 = requests.get(
        f"http://static-maps.yandex.ru/1.x/?ll={lon},{lat}&bbox={bbox}&l=map&pt={lon},{lat},pm2rdm")
    url = f"http://yandex.ru/maps/?ll={lon},{lat}&z=15&l=map&pt={lon},{lat},pm2rdm"
    keyboard = [
        [InlineKeyboardButton("Открыть карту",
                              url=url)]
    ]
    # Кнопки навигации
    nav_buttons = []
    if current_index > 0:
        nav_buttons.append(InlineKeyboardButton("⬅️ Назад", callback_data=f"prev:{current_index}"))
    nav_buttons.append(InlineKeyboardButton(f"{current_index + 1} / {len(results)}", callback_data="noop"))
    if current_index < len(results) - 1:
        nav_buttons.append(InlineKeyboardButton("➡️ Вперёд", callback_data=f"next:{current_index}"))

    keyboard.append(nav_buttons)
    reply_markup = InlineKeyboardMarkup(keyboard)
    image_data = response1.content
    image = Image.open(BytesIO(image_data))
    image.save("img.png")

    with open("img.png", 'rb') as photo:
        # Считываем бинарные данные из файла
        photo_blob = photo.read()
        # Создаём новое "файло-подобное" представление для отправки
        photo.seek(0)  # Возвращаем указатель в начало файла
        if isinstance(update, CallbackQuery):  # при нажатии на кнопку
            # Формируем медиа
            media = InputMediaPhoto(media=photo,
                                    caption=f"{type.capitalize()}: {name}\nПо адресу: {address}\nНажмите на кнопку, чтобы открыть карту:")
            # Редактируем сообщение
            await update.edit_message_media(media=media, reply_markup=reply_markup)
        else:  # при отправке в первый раз
            await context.bot.send_photo(
                chat_id=update.effective_message.chat_id,
                photo=photo,
                caption=f"{type.capitalize()}: {name}\nПо адресу: {address}\nНажмите на кнопку, чтобы открыть карту:",
                reply_markup=reply_markup
            )
        # сохранение просматриваемых запросов в историю поиска (в базу данных)
        con = sqlite3.connect('requests.db')
        # Создание курсора
        cur = con.cursor()
        cur.execute('''INSERT INTO history (photo, text, link, user_id) VALUES (?, ?, ?, ?)''', (
            photo_blob,
            f"{str(type).capitalize()}: {name}\nПо адресу: {address}\nНажмите на кнопку, чтобы открыть карту:",
            f"http://yandex.ru/maps/?ll={lon},{lat}&z=15&l=map&pt={lon},{lat},pm2rdm",
            update.message.from_user.id
        ))
    con.commit()
    con.close()


async def handle_search_navigation(update: Update, context: ContextTypes.DEFAULT_TYPE):  # обработчик кнопок навигации
    query = update.callback_query
    await query.answer()

    data = query.data
    action, index = data.split(':')
    index = int(index)

    results = context.user_data.get('search_results')
    if not results:
        await query.message.reply_text("Результаты не найдены.")
        return

    if action == 'next':
        new_index = index + 1
    elif action == 'prev':
        new_index = index - 1
    else:
        return

    if 0 <= new_index < len(results):  # следующий/предыдущий результат поиска
        context.user_data['current_index'] = new_index
        await send_search_result(query, context, index=new_index)


async def start_route(update: Update,
                      context: ContextTypes.DEFAULT_TYPE):  # начало диалога для построения маршрута и ожидание ввода первого объекта
    await update.message.reply_text('Введите название первого географического объекта:')
    return WAITING_FOR_FIRST_OBJECT


async def handle_first_object(update: Update,
                              context: ContextTypes.DEFAULT_TYPE):  # обработка первого объекта и ожидание ввода второго объекта
    if not update.message:
        logger.debug("Получено обновление без текстового сообщения")
        return

    user_input = update.message.text
    try:
        longitude, latitude = map(float, get_coords(user_input).split())
        context.user_data['first_coords'] = (longitude, latitude)
        await update.message.reply_text('Первый объект найден. Введите название второго географического объекта:')
        return WAITING_FOR_SECOND_OBJECT
    except Exception as e:
        logger.error(f"Произошла ошибка при обработке первого объекта: {e}")
        await update.message.reply_text('Не удаётся найти данный географический объект. Попробуйте снова.')
        await update.message.reply_text('Введите название первого географического объекта:')
        return WAITING_FOR_FIRST_OBJECT


async def handle_second_object(update: Update,
                               context: ContextTypes.DEFAULT_TYPE):  # обработка второго объекта и завершение диалога
    if not update.message:
        logger.debug("Получено обновление без текстового сообщения")
        return

    user_input = update.message.text
    try:
        longitude, latitude = map(float, get_coords(user_input).split())
        first_coords = context.user_data.get('first_coords')
        await update.message.reply_text('Второй объект найден.')
        await route(update, context, first_coords, (longitude, latitude))
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Произошла ошибка при обработке второго объекта: {e}")
        await update.message.reply_text('Не удаётся найти данный географический объект. Попробуйте снова.')
        await update.message.reply_text('Введите название второго географического объекта:')
        return WAITING_FOR_SECOND_OBJECT


async def route(update: Update, context: ContextTypes.DEFAULT_TYPE, start, end):  # построение маршрута
    user_id = update.message.from_user.id
    try:  # с помощью запроса строим маршрут между объектами и изображаем его на фото с помощью PIL
        response_for_route = (
            f"https://static-maps.yandex.ru/1.x/?l=map&pl="
            f"c:ec473fFF,w:5,{start[0]},{start[1]},{end[0]},{end[1]}"
            f"&pt={start[0]},{start[1]},pm2rdm~{end[0]},{end[1]},pm2rdm"
        )
        chat_id = update.message.chat_id
        response = requests.get(response_for_route)
        image_data = response.content
        image = Image.open(BytesIO(image_data))
        url = f"https://yandex.ru/maps/?rtext={start[1]},{start[0]}~{end[1]},{end[0]}"
        keyboard = [
            [InlineKeyboardButton("Открыть карту",
                                  url=url)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        image.save("img.png")

        with open("img.png", 'rb') as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=f"Маршрут построен: {start} - {end}\nНажмите на кнопку, чтобы открыть карту:",
                reply_markup=reply_markup
            )
        con = sqlite3.connect('requests.db')
        # Считываем бинарные данные из файла
        with open("img.png", "rb") as file:
            photo_blob = file.read()
        # Создание курсора
        cur = con.cursor()
        cur.execute('''INSERT INTO history (photo, text, link, user_id) VALUES (?, ?, ?, ?)''', (
            photo_blob, f"Маршрут построен: {start} - {end}\nНажмите на кнопку, чтобы открыть карту:",
            f"https://yandex.ru/maps/?rtext={start[1]},{start[0]}~{end[1]},{end[0]}", user_id))
        con.commit()
        con.close()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Произошла ошибка при обработке второго объекта: {e}")
        await update.message.reply_text('Не удаётся построить маршрут. Попробуйте снова.')
        await update.message.reply_text('Введите название первого географического объекта:')
        return WAITING_FOR_FIRST_OBJECT


async def start_weather(update: Update,
                        context: ContextTypes.DEFAULT_TYPE):  # начало диалога для запроса к получению информации о погоде
    await update.message.reply_text('Введите название населённого пункта:')
    return WAITING_FOR_WEATHER_INPUT


async def handle_weather(update: Update,
                         context: ContextTypes.DEFAULT_TYPE):  # обработка и получение подробной информации о погоде
    global WEATHER_KEY
    if not update.message:
        logger.debug("Получено обновление без текстового сообщения")
        return

    city = update.message.text
    chat_id = update.message.chat_id
    user_id = update.message.from_user.id
    try:  # c помощью запроса к openweathermap api получаем всю нужную информацию о погоде во введённом населённом пункте
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru"
        response = requests.get(url)
        data = response.json()
        image_url = f"https://openweathermap.org/img/wn/{data['weather'][0]['icon']}@2x.png"  # наглядное изображение с состоянием погоды, взятое из запроса
        response_to_image = requests.get(image_url)
        image = Image.open(BytesIO(response_to_image.content))
        # Создание нового изображения с голубым фоном для более удобного обозрения
        background_color = (135, 206, 250)  # RGB-значение голубого цвета
        new_image = Image.new("RGB", image.size, background_color)

        # Наложение исходного изображения на новый фон
        new_image.paste(image, (0, 0), image if image.mode == 'RGBA' else None)
        new_image.save('img.png')
        city_id = data['id']
        url = f"https://openweathermap.org/city/{city_id}"
        keyboard = [
            [InlineKeyboardButton("Открыть подробную сводку о погоде",
                                  url=url)]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        country = data['sys']['country']
        temp = f"Температура: {data['main']['temp']}°C"
        feels_like = f"Ощущается как: {data['main']['feels_like']}°C"
        condition = f"Состояние: {data['weather'][0]['description']}"
        humidity = f"Влажность: {data['main']['humidity']}%"
        wind_speed = f"Скорость ветра: {data['wind']['speed']} м/с"
        pressure = f"Давление: {data['main']['pressure']} мбар"
        visibility = f"Видимость: {float(data['visibility']) / 1000} км"
        with open("img.png", 'rb') as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                caption=f"Город: {city.capitalize()}\nСтрана: {country}\n{temp}\n{feels_like}\n{condition}\n{humidity}\n{pressure}\n{visibility}\n"
                        f"{wind_speed}\nНажмите на кнопку, чтобы посмотреть подробную сводку о погоде:",
                photo=photo,
                reply_markup=reply_markup
            )
        con = sqlite3.connect('requests.db')
        # Считываем бинарные данные из файла
        with open("img.png", "rb") as file:
            photo_blob = file.read()
        # Создание курсора и сохранение в историю поиска
        cur = con.cursor()
        cur.execute('''INSERT INTO history (photo, text, link, user_id) VALUES (?, ?, ?, ?)''', (
            photo_blob,
            f"Город: {city.capitalize()}\nСтрана: {country}\n{temp}\n{feels_like}\n{condition}\n{humidity}\n{pressure}\n{visibility}\n"
            f"{wind_speed}\nНажмите на кнопку, чтобы посмотреть подробную сводку о погоде:",
            f"https://openweathermap.org/city/{city_id}", user_id))
        con.commit()
        con.close()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Произошла ошибка при обработке города: {e}")
        await update.message.reply_text(
            'Не удаётся получить информацию о погоде в этом населённом пункте. Попробуйте снова.')
        await update.message.reply_text('Введите название населённого пункта:')
        return WAITING_FOR_WEATHER_INPUT


def main():  # основная функция программы
    # создание бота с помощью токена, выданного BotFather
    application = Application.builder().token(
        '7612561980:AAFCPRGsdXARg2ee5kF6hm1-aP5wYdQjMpI').build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('geocode', start_geocode),
                      CommandHandler('route', start_route),
                      CommandHandler('weather', start_weather),
                      CommandHandler('search', input_place)
                      ],  # функции, использующие диалог с ботом (ConversationHandler)
        states={
            # параметры для ожидания ввода текста пользователем и последующая обработка данного ввода
            WAITING_FOR_GEOCODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_location)],
            WAITING_FOR_FIRST_OBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_first_object)],
            WAITING_FOR_SECOND_OBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_second_object)],
            WAITING_FOR_WEATHER_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weather)],
            WAITING_FOR_PLACE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_type)],
            WAITING_FOR_TYPE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, search)],
        },  # далее функции, запускающиеся сразу после вызова той или иной команды в чате с ботом
        fallbacks=[CommandHandler('geocode', start_geocode),
                   CommandHandler('route', start_route),
                   CommandHandler('weather', start_weather),
                   CommandHandler('search', input_place),
                   CommandHandler('history', show_history_options)],
        per_message=False  # параметр для возможности прерывания диалога и вызова какой-либо другой команды
    )

    application.add_handler(conv_handler)  # добавление диалога с ботом
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("history", show_history_options))  # добавление всех остальных команд
    application.add_handler(CallbackQueryHandler(handle_search_navigation,
                                                 pattern=r'^(prev|next):'))
    # добавление обработчиков кнопок под сообщениями бота
    application.add_handler(CallbackQueryHandler(handle_history_navigation, pattern=r'^(hist_prev|hist_next):'))
    application.add_handler(CallbackQueryHandler(button_handler))

    application.run_polling()  # запуск бота


if __name__ == '__main__':
    main()  # запуск всей программы
