import requests
from io import BytesIO
from PIL import Image
import logging
from config import BOT_TOKEN
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, MessageHandler, ConversationHandler, ContextTypes, \
    Application, filters

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG
)

logger = logging.getLogger(__name__)
WAITING_FOR_GEOCODE_INPUT = 1
WAITING_FOR_FIRST_OBJECT = 2
WAITING_FOR_SECOND_OBJECT = 3
WAITING_FOR_WEATHER_INPUT = 4
API_KEY = '8013b162-6b42-4997-9691-77b7074026e0'
WEATHER_KEY = 'c0c8ea3bf67266e89078d8488a2ac94d'


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
        "/route (построение маршрута между двумя объектами), /weather (получение информации о погоде)."
    )


# Начало диалога
async def start_geocode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Введите название географического объекта:')
    return WAITING_FOR_GEOCODE_INPUT


async def start_route(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Введите название первого географического объекта:')
    return WAITING_FOR_FIRST_OBJECT


async def start_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Введите название города:')
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
        return ConversationHandler.END

    except Exception as e:
        logger.error(f"Произошла ошибка: {e}")
        await update.message.reply_text('Не удаётся найти данный географический объект. Попробуйте снова.')
        return WAITING_FOR_GEOCODE_INPUT


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
        return WAITING_FOR_SECOND_OBJECT


async def route(update: Update, context: ContextTypes.DEFAULT_TYPE, start, end):
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
            caption="Маршрут построен\nНажмите на кнопку, чтобы открыть карту:",
            reply_markup=reply_markup
        )
    return ConversationHandler.END


async def handle_weather(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global WEATHER_KEY
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
        condition = f"Состояние: {data['weather'][0]['description']}"
        humidity = f"Влажность: {data['main']['humidity']}%"
        wind_speed = f"Скорость ветра: {data['wind']['speed']} м/с"
        with open("img.png", 'rb') as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                caption=f"Город: {city.capitalize()}\nСтрана: {country}\n{temp}\n{condition}\n{humidity}\n"
                        f"{wind_speed}\nНажмите на кнопку, чтобы посмотреть подробную сводку о погоде:",
                photo=photo,
                reply_markup=reply_markup
            )
        return ConversationHandler.END
    except Exception as e:
        logger.error(f"Произошла ошибка при обработке города: {e}")
        await update.message.reply_text('Не удаётся получить информацию о погоде в этом городе. Попробуйте снова.')
        return WAITING_FOR_WEATHER_INPUT


def main():
    application = Application.builder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('geocode', start_geocode),
                      CommandHandler('route', start_route),
                      CommandHandler('weather', start_weather)
                      ],
        states={
            WAITING_FOR_GEOCODE_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_location)],
            WAITING_FOR_FIRST_OBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_first_object)],
            WAITING_FOR_SECOND_OBJECT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_second_object)],
            WAITING_FOR_WEATHER_INPUT: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_weather)],
        },
        fallbacks=[],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.run_polling()


if __name__ == '__main__':
    main()
