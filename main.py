import requests
from io import BytesIO
from PIL import Image
import logging
from config import BOT_TOKEN
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, MessageHandler, ConversationHandler, ContextTypes, \
    Application, filters, CallbackQueryHandler
import sqlite3

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG
)

logger = logging.getLogger(__name__)
WAITING_FOR_GEOCODE_INPUT = 1
WAITING_FOR_FIRST_OBJECT = 2
WAITING_FOR_SECOND_OBJECT = 3
WAITING_FOR_WEATHER_INPUT = 4
WAITING_FOR_TYPE_INPUT = 5
WAITING_FOR_PLACE_INPUT = 6
API_KEY = '8013b162-6b42-4997-9691-77b7074026e0'
WEATHER_KEY = 'c0c8ea3bf67266e89078d8488a2ac94d'


# Формирование OverpassQL-запроса
def get_overpass_query(query: str, lat: float, lon: float, radius: int = 10000) -> str:
    osm_key_value = f'name~"{query.lower()}",i'
    overpass_query = f"""
[out:json][timeout:25];
node[{osm_key_value}](around:{radius},{lat},{lon});
out body;
"""
    return overpass_query


def get_coords(user_input):
    geocoder_request = f'http://geocode-maps.yandex.ru/1.x/?apikey={API_KEY}&geocode={user_input}&format=json'
    response = requests.get(geocoder_request)
    data = response.json()
    coordinates = data['response']['GeoObjectCollection']['featureMember'][0]['GeoObject']['Point']['pos']
    return coordinates


# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать! Используйте команды или введите текст для получения списка команд.")


# Обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Это справка по боту. Доступные команды: /start (запуск), /help (справка), /geocode (поиск объекта), "
        "/route (построение маршрута между двумя объектами), /weather (получение информации о погоде), /history (просмотр истории запросов), "
        "/favorite (просмотр избранных мест), /search (поиск нужных мест поблизости (в России))."
    )


async def show_history_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        [InlineKeyboardButton("Показать историю погоды", callback_data='weather_history')],
        [InlineKeyboardButton("Показать историю карт", callback_data='map_history')],
        [InlineKeyboardButton("Показать всю историю", callback_data='all_history')],
        [InlineKeyboardButton("Очистить историю", callback_data='clear_history')]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text('Выберите один из предложенных вариантов:', reply_markup=reply_markup)


async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def history(update: Update, context: ContextTypes.DEFAULT_TYPE, type):
    chat_id = update.message.chat_id
    con = sqlite3.connect('requests.db')
    # Создание курсора
    cur = con.cursor()
    if type == 4:
        cur.execute('''DELETE from history''')
        con.commit()
        await update.message.reply_text('История успешно очищена.')
        con.close()
        return
    elif type == 1:
        # Запрашиваем только записи с ссылкой на OpenWeather
        all_requests = cur.execute(
            '''SELECT * FROM history WHERE link LIKE "https://openweathermap.org/city/%"''').fetchall()
    elif type == 2:
        all_requests = cur.execute(
            '''SELECT * FROM history WHERE link NOT LIKE "https://openweathermap.org/city/%"''').fetchall()
    elif type == 3:
        all_requests = cur.execute('''SELECT * from history''').fetchall()
    if len(all_requests) == 0:
        if type == 1:
            await update.message.reply_text('В последнее время не было запросов на получение информации о погоде.')
        elif type == 2:
            await update.message.reply_text('В последнее время не было запросов на получение Яндекс.карт.')
        elif type == 3:
            await update.message.reply_text('В последнее время не было запросов.')
        con.close()
        return
    if len(all_requests) > 5:
        all_requests = all_requests[-5:]
    if type == 1:
        await update.message.reply_text('Вот история запросов на получение информации о погоде:')
    elif type == 2:
        await update.message.reply_text('Вот история запросов Яндекс.Карт:')
    elif type == 3:
        await update.message.reply_text('Вот вся история запросов:')
    for message in all_requests:
        # Открываем изображение
        image = Image.open(BytesIO(message[1]))
        image.save("img.png")
        # Формируем клавиатуру
        if message[3] and message[3].startswith('https://openweathermap.org/city/'):
            keyboard = [[InlineKeyboardButton("Открыть подробную сводку о погоде", url=message[3])]]
        else:
            keyboard = [[InlineKeyboardButton("Открыть карту", url=message[3])]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        with open("img.png", 'rb') as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=message[2],
                reply_markup=reply_markup
            )
    con.close()
    return


async def input_place(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Введите название географического объекта для поиска объектов рядом с ним:')
    return WAITING_FOR_PLACE_INPUT


async def input_type(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        logger.debug("Получено обновление без текстового сообщения")
        return

    user_input = update.message.text
    try:
        longitude, latitude = map(float, get_coords(user_input).split())
        context.user_data['place'] = [(longitude, latitude), user_input]
        await update.message.reply_text('Объект найден. Введите тип объекта, который вы хотите найти рядом с ним:')
        return WAITING_FOR_TYPE_INPUT
    except Exception as e:
        logger.error(f"Произошла ошибка при обработке объекта: {e}")
        await update.message.reply_text('Не удаётся найти данный географический объект. Попробуйте снова.')
        await update.message.reply_text('Введите название географического объекта для поиска объектов рядом с ним:')
        return WAITING_FOR_PLACE_INPUT


async def search(update, context):
    chat_id = update.message.chat_id
    if not update.message:
        logger.debug("Получено обновление без текстового сообщения")
        return

    user_input = update.message.text.strip()
    lat, lon = context.user_data.get('place')[0]
    try:
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
        for element in data["elements"]:
            name = element["tags"].get("name", 'Без названия')
            coords = (element["lon"], element["lat"])
            distance = ((coords[0] - lon) ** 2 + (coords[1] - lat) ** 2) ** 0.5

            results.append({
                'name': name,
                "coords": coords,
                "distance": distance
            })
        results.sort(key=lambda x: x["distance"])
        top_results = results[:3]
        await update.message.reply_text(
            f'Вблизи от места "{context.user_data.get('place')[1]}" найдены следующие объекты типа "{user_input}":')
        for i in top_results:
            name = i['name']
            lon, lat = i['coords']
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
            keyboard = [
                [InlineKeyboardButton("Открыть карту",
                                      url=f"http://yandex.ru/maps/?ll={lon},{lat}&z=15&l=map&pt={lon},{lat},pm2rdm")]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            image_data = response1.content
            image = Image.open(BytesIO(image_data))
            image.save("img.png")

            with open("img.png", 'rb') as photo:
                await context.bot.send_photo(
                    chat_id=chat_id,
                    photo=photo,
                    caption=f"{str(user_input).capitalize()}: {name}\nПо адресу: {address}\nНажмите на кнопку, чтобы открыть карту:",
                    reply_markup=reply_markup
                )
            con = sqlite3.connect('requests.db')
            # Считываем бинарные данные из файла
            with open("img.png", "rb") as file:
                photo_blob = file.read()
            # Создание курсора
            cur = con.cursor()
            cur.execute('''INSERT INTO history (photo, text, link) VALUES (?, ?, ?)''', (
                photo_blob,
                f"{str(user_input).capitalize()}: {name}\nПо адресу: {address}\nНажмите на кнопку, чтобы открыть карту:",
                f"http://yandex.ru/maps/?ll={lon},{lat}&z=15&l=map&pt={lon},{lat},pm2rdm"))
            con.commit()
            con.close()
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Ошибка при поиске через Overpass API: {e}")
        await update.message.reply_text("Не удалось выполнить поиск. Попробуйте снова.")
        return WAITING_FOR_TYPE_INPUT


# Начало диалога
async def start_geocode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Введите название географического объекта:')
    return WAITING_FOR_GEOCODE_INPUT


async def start_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Введите название населённого пункта:')
    return WAITING_FOR_WEATHER_INPUT


# Обработка ввода пользователя
async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        logger.debug("Получено обновление без текстового сообщения")
        return

    user_input = update.message.text

    chat_id = update.message.chat_id

    try:
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
        cur.execute('''INSERT INTO history (photo, text, link) VALUES (?, ?, ?)''', (
            photo_blob, f"Найден объект: {user_input}\nНажмите на кнопку, чтобы открыть карту:", geocoder_request[0]))
        con.commit()
        con.close()
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Произошла ошибка: {e}")
        await update.message.reply_text('Не удаётся найти данный географический объект. Попробуйте снова.')
        await update.message.reply_text('Введите название географического объекта:')
        return WAITING_FOR_GEOCODE_INPUT


async def start_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Введите название первого географического объекта:')
    return WAITING_FOR_FIRST_OBJECT


async def handle_first_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def handle_second_object(update: Update, context: ContextTypes.DEFAULT_TYPE):
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


async def route(update: Update, context: ContextTypes.DEFAULT_TYPE, start, end):
    try:
        response_for_route = (
            f"https://static-maps.yandex.ru/1.x/?l=map&pl="
            f"c:ec473fFF,w:5,{start[0]},{start[1]},{end[0]},{end[1]}"
            f"&pt={start[0]},{start[1]},pm2rdm~{end[0]},{end[1]},pm2rdm"
        )
        chat_id = update.message.chat_id
        response = requests.get(response_for_route)
        image_data = response.content
        image = Image.open(BytesIO(image_data))
        keyboard = [
            [InlineKeyboardButton("Открыть карту",
                                  url=f"https://yandex.ru/maps/?rtext={start[1]},{start[0]}~{end[1]},{end[0]}")]
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
        cur.execute('''INSERT INTO history (photo, text, link) VALUES (?, ?, ?)''', (
            photo_blob, f"Маршрут построен: {start} - {end}\nНажмите на кнопку, чтобы открыть карту:",
            f"https://yandex.ru/maps/?rtext={start[1]},{start[0]}~{end[1]},{end[0]}"))
        con.commit()
        con.close()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Произошла ошибка при обработке второго объекта: {e}")
        await update.message.reply_text('Не удаётся построить маршрут. Попробуйте снова.')
        await update.message.reply_text('Введите название первого географического объекта:')
        return WAITING_FOR_FIRST_OBJECT


async def handle_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global WEATHER_KEY
    if not update.message:
        logger.debug("Получено обновление без текстового сообщения")
        return

    city = update.message.text
    chat_id = update.message.chat_id
    try:
        url = f"https://api.openweathermap.org/data/2.5/weather?q={city}&appid={WEATHER_KEY}&units=metric&lang=ru"
        response = requests.get(url)
        data = response.json()
        image_url = f'https://openweathermap.org/img/wn/{data['weather'][0]['icon']}@2x.png'
        response_to_image = requests.get(image_url)
        image = Image.open(BytesIO(response_to_image.content))
        # Создание нового изображения с голубым фоном
        background_color = (135, 206, 250)  # RGB-значение голубого цвета
        new_image = Image.new("RGB", image.size, background_color)

        # Наложение исходного изображения на новый фон
        new_image.paste(image, (0, 0), image if image.mode == 'RGBA' else None)
        new_image.save('img.png')
        city_id = data['id']
        keyboard = [
            [InlineKeyboardButton("Открыть подробную сводку о погоде",
                                  url=f"https://openweathermap.org/city/{city_id}")]
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
        # Создание курсора
        cur = con.cursor()
        cur.execute('''INSERT INTO history (photo, text, link) VALUES (?, ?, ?)''', (
            photo_blob,
            f"Город: {city.capitalize()}\nСтрана: {country}\n{temp}\n{feels_like}\n{condition}\n{humidity}\n{pressure}\n{visibility}\n"
            f"{wind_speed}\nНажмите на кнопку, чтобы посмотреть подробную сводку о погоде:",
            f"https://openweathermap.org/city/{city_id}"))
        con.commit()
        con.close()
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Произошла ошибка при обработке города: {e}")
        await update.message.reply_text(
            'Не удаётся получить информацию о погоде в этом населённом пункте. Попробуйте снова.')
        await update.message.reply_text('Введите название населённого пункта:')
        return WAITING_FOR_WEATHER_INPUT


def main():
    application = Application.builder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('geocode', start_geocode),
                      CommandHandler('route', start_route),
                      CommandHandler('weather', start_weather),
                      CommandHandler('search', input_place)
                      ],
        states={
            WAITING_FOR_GEOCODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_location)],
            WAITING_FOR_FIRST_OBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_first_object)],
            WAITING_FOR_SECOND_OBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_second_object)],
            WAITING_FOR_WEATHER_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weather)],
            WAITING_FOR_PLACE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, input_type)],
            WAITING_FOR_TYPE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, search)],
        },
        fallbacks=[CommandHandler('geocode', start_geocode),
                   CommandHandler('route', start_route),
                   CommandHandler('weather', start_weather),
                   CommandHandler('search', input_place),
                   CommandHandler('history', show_history_options)],
        per_message=False
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("history", show_history_options))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.run_polling()


if __name__ == '__main__':
    main()
