import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
import threading
import time
from datetime import datetime, timedelta
import firebase_admin
from firebase_admin import credentials, firestore
import imaplib
import email

# ================= কনফিগারেশন =================
API_TOKEN = 'আপনার_বট_টোকেন_এখানে_দিন'
ADMIN_ID = 123456789  # আপনার টেলিগ্রাম আইডি

bot = telebot.Telebot(API_TOKEN)
app = Flask(__name__)

# ================= ফায়ারবেস সেটআপ =================
cred = credentials.Certificate("firebase-key.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# ================= ফ্লাস্ক সার্ভার (২৪/৭ লাইভ রাখার জন্য) =================
@app.route('/')
def home():
    return "Waleya Mail Bot is Running 24/7!"

def run_server():
    app.run(host="0.0.0.0", port=8080)

# ================= বাটন মেনু =================
def user_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("🛒 Buy a New Mail"), KeyboardButton("📧 My Mail"),
        KeyboardButton("💰 Balance"), KeyboardButton("👤 Profile"),
        KeyboardButton("ℹ️ Bot Info")
    )
    return markup

def admin_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("📊 Dashboard"), KeyboardButton("👥 User Management"),
        KeyboardButton("📢 Send Notice"), KeyboardButton("➕ Add Mails")
    )
    return markup

# ================= স্টার্ট কমান্ড =================
@bot.message_handler(commands=['start'])
def welcome(message):
    user_id = message.chat.id
    
    # নতুন ইউজার হলে ডাটাবেসে সেভ করা
    user_ref = db.collection('users').document(str(user_id))
    if not user_ref.get().exists:
        user_ref.set({'balance': 0, 'joined': datetime.now()})
        
    if user_id == ADMIN_ID:
        bot.send_message(user_id, "অ্যাডমিন প্যানেলে স্বাগতম!", reply_markup=admin_menu())
    else:
        bot.send_message(user_id, "আমাদের Mail Bot-এ স্বাগতম! মেনু থেকে আপনার অপশন বেছে নিন।", reply_markup=user_menu())

# ================= ইউজার প্যানেল =================

@bot.message_handler(func=lambda message: message.text == "💰 Balance")
def balance_menu(message):
    user_id = message.chat.id
    balance = db.collection('users').document(str(user_id)).get().to_dict().get('balance', 0)
    bot.send_message(user_id, f"💵 আপনার বর্তমান ব্যালেন্স: {balance} ৳\n\nডিপোজিট করতে অ্যাডমিনের সাথে যোগাযোগ করুন অথবা অটোমেটিক পেমেন্ট সেটআপ করুন।")

@bot.message_handler(func=lambda message: message.text == "ℹ️ Bot Info")
def bot_info(message):
    info_text = """
ℹ️ **Bot Information**
━━━━━━━━━━━━━━
📜 **Rules:**
1. ২০ মিনিটের মধ্যে কোড না আসলে অটো রিফান্ড।
2. মেয়াদ শেষ হলে মেইল অটো রিমুভ হবে।

👨‍💻 **Developer:** Waleya
👑 **Admin Contact:** @YourAdminUser
━━━━━━━━━━━━━━
"""
    bot.send_message(message.chat.id, info_text, parse_mode='Markdown')

# ================= মেইল কেনা ও ইনবক্স চেক (অ্যানিমেশন সহ) =================

@bot.message_handler(func=lambda message: message.text == "📧 My Mail")
def my_mails(message):
    user_id = message.chat.id
    # ফায়ারবেস থেকে ইউজারের কেনা মেইল খোঁজা
    active_mails = db.collection('active_sales').where('user_id', '==', user_id).stream()
    
    found = False
    for m in active_mails:
        found = True
        data = m.to_dict()
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("📩 Check Inbox", callback_data=f"inbox|{data['email']}|{data['password']}"))
        bot.send_message(user_id, f"📧 Email: `{data['email']}`\n🔑 Pass: `{data['password']}`", reply_markup=markup, parse_mode='Markdown')
        
    if not found:
        bot.send_message(user_id, "আপনার কোনো সক্রিয় মেইল নেই।")

@bot.callback_query_handler(func=lambda call: call.data.startswith("inbox|"))
def check_inbox_animated(call):
    user_id = call.message.chat.id
    _, email_address, password = call.data.split('|')
    
    # অ্যানিমেশন ফ্রেম
    frames = [
        "🔄 সার্ভারের সাথে কানেক্ট করা হচ্ছে ⬛⬜⬜⬜",
        "🔄 ইনবক্স স্ক্যান করা হচ্ছে ⬛⬛⬜⬜",
        "🔄 নতুন মেসেজ খোঁজা হচ্ছে ⬛⬛⬛⬜",
        "🔄 ডাটা ফেচ করা হচ্ছে ⬛⬛⬛⬛"
    ]
    
    msg = bot.send_message(user_id, "অপেক্ষা করুন...")
    
    for frame in frames:
        time.sleep(0.5)
        bot.edit_message_text(frame, chat_id=user_id, message_id=msg.message_id)
    
    # IMAP কানেকশন (Hotmail/Outlook)
    try:
        mail = imaplib.IMAP4_SSL('imap-mail.outlook.com')
        mail.login(email_address, password)
        mail.select('inbox')
        status, data = mail.search(None, 'ALL')
        mail_ids = data[0].split()

        if not mail_ids:
            bot.edit_message_text("❌ ইনবক্সে কোনো নতুন মেসেজ পাওয়া যায়নি।", chat_id=user_id, message_id=msg.message_id)
        else:
            # মেসেজ পাওয়া গেলে রিফান্ড বন্ধ করার জন্য ডাটাবেস আপডেট
            docs = db.collection('active_sales').where('email', '==', email_address).stream()
            for doc in docs:
                doc.reference.update({'msg_received': True})
            
            # লেটেস্ট মেসেজ ডেমো হিসেবে দেখানো হলো (বাস্তবে fetch করতে হবে)
            bot.edit_message_text("✅ **New Message Found!**\nদয়া করে আপনার মেইল চেক করুন।", chat_id=user_id, message_id=msg.message_id, parse_mode='Markdown')
            
    except Exception as e:
        bot.edit_message_text("❌ মেইলে লগিন করতে সমস্যা হচ্ছে।", chat_id=user_id, message_id=msg.message_id)

# ================= রান স্ক্রিপ্ট =================
if __name__ == "__main__":
    # ফ্লাস্ক সার্ভার ব্যাকগ্রাউন্ডে চালু করা
    threading.Thread(target=run_server, daemon=True).start()
    print("Bot is running...")
    # টেলিগ্রাম বট চালু করা
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
