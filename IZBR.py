 v  import sqlite3
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CallbackQueryHandler, CommandHandler


def init_favorites_db():
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            query_type TEXT NOT NULL,
            query_text TEXT NOT NULL,
            coordinates TEXT,
            UNIQUE(user_id, query_type, query_text)
        )
    ''')
    conn.commit()
    conn.close()


init_favorites_db()


async def add_to_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    data = query.data.split('|')
    action = data[0]
    user_id = query.from_user.id

    if action == 'add_favorite':
        query_type = data[1]
        query_text = data[2]
        coordinates = data[3] if len(data) > 3 else None

        conn = sqlite3.connect('favorites.db')
        cursor = conn.cursor()

        try:
            cursor.execute(
                'INSERT INTO favorites (user_id, query_type, query_text, coordinates) VALUES (?, ?, ?, ?)',
                (user_id, query_type, query_text, coordinates)
            )
            conn.commit()
            await query.edit_message_text(text=f"Запрос '{query_text}' добавлен в избранное!")
        except sqlite3.IntegrityError:
            await query.edit_message_text(text="Этот запрос уже есть в избранном!")
        finally:
            conn.close()


async def show_favorites(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.message.from_user.id
    conn = sqlite3.connect('favorites.db')
    cursor = conn.cursor()

    cursor.execute('SELECT query_type, query_text FROM favorites WHERE user_id = ?', (user_id,))
    favorites = cursor.fetchall()
    conn.close()

    if not favorites:
        await update.message.reply_text("У вас нет избранных запросов.")
        return

    message = "Избранные запросы:\n\n"
    for i, (query_type, query_text) in enumerate(favorites, 1):
        message += f"{i}. {query_type}: {query_text}\n"

    await update.message.reply_text(message)


def get_favorite_keyboard(query_type: str, query_text: str, coordinates: str = None):
    callback_data = f"add_favorite|{query_type}|{query_text}"
    if coordinates:
        callback_data += f"|{coordinates}"

    keyboard = [
        [InlineKeyboardButton("Добавить в избранное", callback_data=callback_data)]
    ]
    return InlineKeyboardMarkup(keyboard)


def setup_favorites_handlers(application):
    application.add_handler(CallbackQueryHandler(add_to_favorites, pattern='^add_favorite\|'))
    application.add_handler(CommandHandler("favorite", show_favorites))
