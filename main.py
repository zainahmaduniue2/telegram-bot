import logging
import json
import os
import time
from flask import Flask
from threading import Thread
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes, MessageHandler, filters
from telegram.error import BadRequest, Forbidden

# --- Web Server to Keep the Bot Alive ---
app = Flask('')

@app.route('/')
def home():
    return "Bot is alive and running!"

def run_flask():
  # Render provides the PORT environment variable.
  port = int(os.environ.get('PORT', 8080))
  app.run(host='0.0.0.0', port=port)

def keep_alive():
    t = Thread(target=run_flask)
    t.start()

# --- Bot Configuration (from Environment Variables) ---
# IMPORTANT: These are now set in Render's Environment Variables section
BOT_TOKEN = os.environ.get('BOT_TOKEN')
ADMIN_ID = int(os.environ.get('ADMIN_ID'))
CHANNEL_USERNAME = "@tzgiveaways"
BOT_USERNAME = "tzgiveawaybot"
# On platforms like Render, we can't save files locally. We will store data in memory.
# For permanent storage, a database like Redis or Postgres (available on Render) would be needed.
# For now, data will reset if the bot restarts.
USERS_DATA = {}
STOCK_DATA = {}


# --- Logging Setup ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- In-Memory Data Functions (No more JSON files) ---
def load_data(data_type):
    """Loads data from memory."""
    if data_type == 'users':
        return USERS_DATA
    elif data_type == 'stock':
        return STOCK_DATA
    return {}

def save_data(data, data_type):
    """Saves data to memory."""
    global USERS_DATA, STOCK_DATA
    if data_type == 'users':
        USERS_DATA = data
    elif data_type == 'stock':
        STOCK_DATA = data

def get_user_data(user: Update.effective_user):
    """User ka data save ya update karta hai."""
    users = load_data('users')
    user_id_str = str(user.id)
    
    if user_id_str not in users or \
       users[user_id_str].get("first_name") != user.first_name or \
       users[user_id_str].get("username") != user.username:
        
        points = users.get(user_id_str, {}).get("points", 0)
        referred_by = users.get(user_id_str, {}).get("referred_by")
        referrals_made = users.get(user_id_str, {}).get("referrals_made", 0)

        users[user_id_str] = {
            "points": points, "referred_by": referred_by, "referrals_made": referrals_made,
            "first_name": user.first_name, "username": user.username or "N/A"
        }
        save_data(users, 'users')
        
    return users[user_id_str]

def initialize_stock():
    """Initializes stock in memory."""
    global STOCK_DATA
    if not STOCK_DATA:
        STOCK_DATA = {
            "crunchyroll": [],
            "prime": []
        }

# --- Bot Handlers ---

async def is_user_in_channel(user_id: int, context: ContextTypes.DEFAULT_TYPE) -> bool:
    try:
        member = await context.bot.get_chat_member(chat_id=CHANNEL_USERNAME, user_id=user_id)
        return member.status in ['creator', 'administrator', 'member', 'restricted']
    except Exception:
        return False

async def show_join_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("➡️ Join Channel", url=f"https://t.me/{CHANNEL_USERNAME.replace('@', '')}")],
                [InlineKeyboardButton("✅ Verify", callback_data="verify_join")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    message_text = f"Bot istemal karne ke liye, pehle hamara channel {CHANNEL_USERNAME} join karein aur 'Verify' par click karein."
    if update.callback_query:
        await update.callback_query.edit_message_text(message_text, reply_markup=reply_markup)
    else:
        await update.message.reply_text(message_text, reply_markup=reply_markup)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    get_user_data(user)
    
    if context.args and len(context.args) > 0:
        referrer_id = context.args[0]
        users = load_data('users')
        if str(referrer_id) != str(user.id) and str(referrer_id) in users:
            user_record = get_user_data(user)
            if user_record.get("referred_by") is None:
                user_record["referred_by"] = referrer_id
                referrer_data = users[str(referrer_id)]
                referrer_data["points"] = referrer_data.get("points", 0) + 1
                referrer_data["referrals_made"] = referrer_data.get("referrals_made", 0) + 1
                users[str(user.id)] = user_record
                users[str(referrer_id)] = referrer_data
                save_data(users, 'users')
                try:
                    await context.bot.send_message(chat_id=referrer_id, text=f"🎉 Mubarak ho! Ek naye user ne aapke link se join kiya hai. Aapke paas ab {referrer_data['points']} points hain.")
                except Exception as e:
                    logger.error(f"Referral notification bhejne mein error: {e}")

    if await is_user_in_channel(user.id, context):
        await show_main_menu(update, context)
    else:
        await show_join_prompt(update, context)

async def verify_join_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    if await is_user_in_channel(query.from_user.id, context):
        await query.edit_message_text("✅ Verification kamyab! Khush amdeed.")
        await show_main_menu(update, context)
    else:
        await query.answer("❌ Aapne abhi tak channel join nahi kiya.", show_alert=True)

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    keyboard = [[InlineKeyboardButton("💰 My Points", callback_data="my_points")],
                [InlineKeyboardButton("🏆 Redeem Prizes", callback_data="redeem_prizes")],
                [InlineKeyboardButton("🔗 Get Referral Link", callback_data="get_referral_link")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    menu_text = "Giveaway Bot mein khush amdeed! Neeche diye gaye menu ka istemal karein."
    if update.callback_query:
         await update.callback_query.edit_message_text(menu_text, reply_markup=reply_markup)
    else:
        await update.effective_message.reply_text(menu_text, reply_markup=reply_markup)

async def menu_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    if not await is_user_in_channel(query.from_user.id, context):
        await query.answer("Aapko bot istemal karne ke liye channel join karna hoga.", show_alert=True)
        await show_join_prompt(update, context)
        return

    user_data = get_user_data(query.from_user)

    if query.data == "my_points":
        points = user_data.get("points", 0)
        await query.message.reply_text(f"Aapke paas abhi {points} points hain.")

    elif query.data == "get_referral_link":
        referral_link = f"https://t.me/{BOT_USERNAME}?start={query.from_user.id}"
        await query.message.reply_text(f"Yeh aapka personal referral link hai:\n\n`{referral_link}`\n\nIse doston ke sath share karein. Har dost ke join karne par aapko 1 point milega!", parse_mode='Markdown')

    elif query.data == "redeem_prizes":
        stock = load_data('stock')
        crunchy_stock = len(stock.get("crunchyroll", []))
        prime_stock = len(stock.get("prime", []))
        
        keyboard = [
            [InlineKeyboardButton(f"Crunchyroll (1 Pt) - Stock: {crunchy_stock}", callback_data="redeem_crunchyroll")],
            [InlineKeyboardButton(f"Prime Video (5 Pts) - Stock: {prime_stock}", callback_data="redeem_prime")],
            [InlineKeyboardButton("« Back", callback_data="back_to_main")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text("Redeem karne ke liye prize chunein:", reply_markup=reply_markup)

    elif query.data.startswith("redeem_"):
        prize = query.data.split("_")[1]
        costs = {"crunchyroll": 1, "prime": 5}
        cost = costs.get(prize)
        
        if cost is None: return

        stock = load_data('stock')
        if not stock.get(prize):
            await query.answer("Sorry, currently no account available for this prize.", show_alert=True)
            return

        users = load_data('users')
        user_data_dict = users.get(str(query.from_user.id), {})
        
        if user_data_dict.get("points", 0) >= cost:
            user_data_dict["points"] -= cost
            account_details = stock[prize].pop(0)
            save_data(users, 'users')
            save_data(stock, 'stock')
            await query.edit_message_text(f"✅ Redemption kamyab! Aapke paas ab {user_data_dict['points']} points hain.\n\nAapke account ki details:\n`{account_details}`", parse_mode='Markdown')
        else:
            await query.answer("❌ Is prize ko redeem karne ke liye aapke paas points kafi nahi hain.", show_alert=True)

    elif query.data == "back_to_main":
        await show_main_menu(update, context)

async def main_message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    if user.id == ADMIN_ID:
        users = load_data('users')
        user_ids = list(users.keys())
        await update.message.reply_text(f"📢 {len(user_ids)} users ko broadcast shuru kiya ja raha hai...")
        success_count, fail_count = 0, 0
        for user_id in user_ids:
            try:
                await context.bot.copy_message(chat_id=user_id, from_chat_id=update.message.chat_id, message_id=update.message.message_id)
                success_count += 1
            except (Forbidden, BadRequest):
                fail_count += 1
            time.sleep(0.1) 
        await update.message.reply_text(f"✅ Broadcast mukammal!\n\nKamyabi se bheja gaya: {success_count} users.\nBhejne mein nakami: {fail_count} users.")
    else:
        if not await is_user_in_channel(user.id, context):
            await show_join_prompt(update, context)
            return
        user_info = f"Naya paigham from: {user.first_name} (@{user.username}, ID: {user.id})"
        await context.bot.send_message(chat_id=ADMIN_ID, text=user_info)
        await context.bot.forward_message(chat_id=ADMIN_ID, from_chat_id=user.id, message_id=update.message.message_id)
        await update.message.reply_text("Aapka message admin ko bhej diya gaya hai. Jald hi jawab milega.")

# --- Admin Commands ---

async def stats_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID: return
    total_users = len(load_data('users'))
    await update.message.reply_text(f"📊 **Bot Statistics** 📊\n\nTotal Unique Users: **{total_users}**", parse_mode='Markdown')

async def users_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID: return
    users = load_data('users')
    if not users:
        await update.message.reply_text("Abhi tak kisi user ne bot start nahi kiya.")
        return
    # We can't send files from memory easily, so we send the text directly.
    # For a large number of users, this might hit Telegram's message length limit.
    user_list_str = "User List\n" + "="*20 + "\n\n"
    for user_id, data in users.items():
        user_list_str += f"Name: {data.get('first_name', 'N/A')}\n"
        user_list_str += f"Username: @{data.get('username', 'N/A')}\n"
        user_list_str += f"Points: {data.get('points', 0)}\n"
        user_list_str += f"Referrals Made: {data.get('referrals_made', 0)}\n" + "-"*20 + "\n"
    
    # Split message if too long
    for i in range(0, len(user_list_str), 4096):
        await update.message.reply_text(user_list_str[i:i+4096])


async def add_stock_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID: return
    try:
        parts = context.args
        prize_name = parts[0].lower()
        account_details = " ".join(parts[1:])
        
        allowed_prizes = ["crunchyroll", "prime"]
        if prize_name not in allowed_prizes:
            await update.message.reply_text(f"Ghalat prize name. Sirf inko add kar sakte hain: {', '.join(allowed_prizes)}")
            return

        if not account_details:
            await update.message.reply_text("Ghalat format. Istemal karein: /addstock <prize_name> <account_details>")
            return
            
        stock = load_data('stock')
        if prize_name not in stock:
            stock[prize_name] = []
        
        stock[prize_name].append(account_details)
        save_data(stock, 'stock')
        await update.message.reply_text(f"✅ Kamyabi! 1 account '{prize_name}' ke stock mein add kar diya gaya hai.")
    except (IndexError, ValueError):
        await update.message.reply_text("Ghalat format. Istemal karein: /addstock <prize_name> <account_details>\nMaslan: /addstock prime user@email.com:pass")

async def view_stock_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if update.effective_user.id != ADMIN_ID: return
    stock = load_data('stock')
    message = "📦 **Mojooda Stock Levels** 📦\n\n"
    for prize, accounts in stock.items():
        message += f"**{prize.capitalize()}**: {len(accounts)} accounts\n"
    await update.message.reply_text(message, parse_mode='Markdown')

def main() -> None:
    """Starts the bot."""
    if not BOT_TOKEN or not ADMIN_ID:
        print("!!! BOT STOPPED: CONFIGURATION ERROR !!!")
        print("Please set BOT_TOKEN and ADMIN_ID in your hosting environment variables.")
        return

    print("--- Starting Bot Script ---")
    initialize_stock()
    
    # The web server is only for Render to detect the service is alive.
    keep_alive()
    
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("stats", stats_handler))
    application.add_handler(CommandHandler("users", users_handler))
    application.add_handler(CommandHandler("addstock", add_stock_handler))
    application.add_handler(CommandHandler("viewstock", view_stock_handler))
    
    application.add_handler(CallbackQueryHandler(verify_join_callback, pattern="^verify_join$"))
    application.add_handler(CallbackQueryHandler(menu_callback_handler))
    
    application.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, main_message_handler))
    
    print("Bot is running...")
    application.run_polling()

if __name__ == "__main__":
    main()
