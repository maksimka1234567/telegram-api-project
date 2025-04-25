import requests
from io import BytesIO
from PIL import Image
import logging
from config import BOT_TOKEN
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import CommandHandler, MessageHandler, CallbackQueryHandler, ConversationHandler, ContextTypes, \
    Application, filters

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.DEBUG
)

logger = logging.getLogger(__name__)
WAITING_FOR_INPUT = 1


# Обработчик команды /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "Добро пожаловать! Используйте команды или введите текст для получения списка команд.")


# Обработчик команды /help
async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Это справка по боту. Доступные команды: /start, /help, /geocode.")


# Начало диалога
async def start_geocode(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('Введите название географического объекта:')
    return WAITING_FOR_INPUT


# Обработка ввода пользователя
async def handle_location(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message:
        logger.debug("Получено обновление без текстового сообщения")
        return

    user_input = update.message.text

    chat_id = update.message.chat_id
    server_address = 'http://geocode-maps.yandex.ru/1.x/?'
    api_key = '8013b162-6b42-4997-9691-77b7074026e0'

    try:
        geocoder_request = f'{server_address}apikey={api_key}&geocode={user_input}&format=json'
        response = requests.get(geocoder_request)
        data = response.json()
        coordinates = data['response']['GeoObjectCollection']['featureMember'][0]['GeoObject']['Point']['pos']
        longitude, latitude = map(float, coordinates.split())
        geocoder_request = [
            f"http://yandex.ru/maps/?ll={longitude},{latitude}&spn=0.01,0.01&l=map&pt={longitude},{latitude},pm2rdm",
            f"http://static-maps.yandex.ru/1.x/?ll={longitude},{latitude}&spn=0.01,0.01&l=map&pt={longitude},{latitude},pm2rdm"
        ]

        keyboard = [
            [InlineKeyboardButton("Открыть карту", url=geocoder_request[0])]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        response1 = requests.get(geocoder_request[1])
        image_data = response1.content
        image = Image.open(BytesIO(image_data))
        image.save("yandex_map.png")

        with open('yandex_map.png', 'rb') as photo:
            await context.bot.send_photo(
                chat_id=chat_id,
                photo=photo,
                caption=f"Найден объект: {user_input}\nНажмите на кнопку, чтобы открыть карту:",
                reply_markup=reply_markup
            )
    except Exception as e:
        logger.error(f"Произошла ошибка: {e}")
        await update.message.reply_text('Не удаётся найти данный географический объект.')
    return ConversationHandler.END


def main():
    application = Application.builder().token(BOT_TOKEN).build()
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('geocode', start_geocode)],
        states={
            WAITING_FOR_INPUT: [MessageHandler(filters.ALL, handle_location)],
        },
        fallbacks=[],
    )

    application.add_handler(conv_handler)
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.run_polling()


if __name__ == '__main__':
    main()

