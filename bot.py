import os
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
API_TOKEN = '8526670393:AAGt_si_DtCAKjGF2Ht8uAmdQeO1rp1sOas'
ADMIN_ID = 6670461311
MAIL_PRICE = 50 # প্রতি মেইলের দাম

bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

# ================= ফায়ারবেস সেটআপ =================
try:
    cred = credentials.Certificate("firebase-key.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
except Exception as e:
    print("Firebase Setup Error:", e)

# ================= ফ্লাস্ক সার্ভার (২৪/৭ লাইভ রাখার জন্য) =================
@app.route('/')
def home():
    return "Waleya Mail Bot is Running!"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

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
    
    try:
        user_ref = db.collection('users').document(str(user_id))
        if not user_ref.get().exists:
            user_ref.set({'balance': 0, 'joined': datetime.now()})
    except:
        pass
        
    if user_id == ADMIN_ID:
        bot.send_message(user_id, "অ্যাডমিন প্যানেলে স্বাগতম! মেনু থেকে অপশন সিলেক্ট করুন।", reply_markup=admin_menu())
    else:
        bot.send_message(user_id, "আমাদের Mail Bot-এ স্বাগতম! মেনু থেকে আপনার অপশন বেছে নিন।", reply_markup=user_menu())


# ===================== অ্যাডমিন প্যানেলের কাজ =====================

# ১. Dashboard
@bot.message_handler(func=lambda message: message.text == "📊 Dashboard" and message.chat.id == ADMIN_ID)
def admin_dashboard(message):
    try:
        users_count = len(list(db.collection('users').stream()))
        mails_count = len(list(db.collection('inventory').where('status', '==', 'fresh').stream()))
        bot.send_message(message.chat.id, f"📊 **Admin Dashboard**\n━━━━━━━━━━━━━\n👥 মোট ইউজার: {users_count}\n✅ স্টকে মেইল আছে: {mails_count} টি\n💰 মেইলের বর্তমান দাম: {MAIL_PRICE} ৳", parse_mode='Markdown')
    except:
        bot.send_message(message.chat.id, "ডাটাবেস কানেক্ট করতে সমস্যা হচ্ছে।")

# ২. Add Mails
@bot.message_handler(func=lambda message: message.text == "➕ Add Mails" and message.chat.id == ADMIN_ID)
def add_mails_start(message):
    msg = bot.send_message(message.chat.id, "নতুন মেইলগুলো নিচে দিন।\nফরম্যাট: `email@hotmail.com|password`\n\nএকাধিক মেইল দিতে প্রতি লাইনে একটি করে দিন।", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_add_mails)

def process_add_mails(message):
    lines = message.text.split('\n')
    added = 0
    for line in lines:
        if '|' in line:
            email, password = line.split('|')
            try:
                db.collection('inventory').add({'email': email.strip(), 'password': password.strip(), 'status': 'fresh'})
                added += 1
            except:
                pass
    bot.send_message(message.chat.id, f"✅ মোট {added} টি মেইল ডাটাবেসে সফলভাবে যুক্ত হয়েছে!")

# ৩. User Management
@bot.message_handler(func=lambda message: message.text == "👥 User Management" and message.chat.id == ADMIN_ID)
def user_management(message):
    msg = bot.send_message(message.chat.id, "যেকোনো ইউজারের ব্যালেন্স অ্যাড করতে তার User ID এবং টাকার পরিমাণ দিন।\nফরম্যাট: `UserID|Amount`\n(যেমন: `123456789|500`)", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_add_balance)

def process_add_balance(message):
    try:
        target_id, amount = message.text.split('|')
        user_ref = db.collection('users').document(target_id.strip())
        if user_ref.get().exists:
            current_bal = user_ref.get().to_dict().get('balance', 0)
            user_ref.update({'balance': current_bal + int(amount.strip())})
            bot.send_message(message.chat.id, f"✅ ইউজার `{target_id}` এর অ্যাকাউন্টে {amount} ৳ অ্যাড হয়েছে!", parse_mode='Markdown')
            bot.send_message(target_id.strip(), f"🎉 অ্যাডমিন আপনার অ্যাকাউন্টে {amount} ৳ ব্যালেন্স যুক্ত করেছেন!")
        else:
            bot.send_message(message.chat.id, "❌ এই User ID ডাটাবেসে নেই।")
    except:
        bot.send_message(message.chat.id, "❌ ফরম্যাট ভুল হয়েছে।")

# ৪. Send Notice
@bot.message_handler(func=lambda message: message.text == "📢 Send Notice" and message.chat.id == ADMIN_ID)
def send_notice_start(message):
    msg = bot.send_message(message.chat.id, "সব ইউজারের কাছে যে নোটিশ পাঠাতে চান, তা লিখে পাঠান:")
    bot.register_next_step_handler(msg, broadcast_notice)

def broadcast_notice(message):
    notice_text = f"📢 **Admin Notice:**\n\n{message.text}"
    try:
        users = db.collection('users').stream()
        count = 0
        for user in users:
            try:
                bot.send_message(user.id, notice_text, parse_mode='Markdown')
                count += 1
            except:
                pass
        bot.send_message(message.chat.id, f"✅ নোটিশ সফলভাবে {count} জন ইউজারকে পাঠানো হয়েছে।")
    except:
        bot.send_message(message.chat.id, "নোটিশ পাঠাতে এরর হয়েছে।")


# ===================== ইউজার প্যানেলের কাজ =====================

@bot.message_handler(func=lambda message: message.text == "💰 Balance")
def balance_menu(message):
    try:
        balance = db.collection('users').document(str(message.chat.id)).get().to_dict().get('balance', 0)
    except:
        balance = 0
    bot.send_message(message.chat.id, f"💵 আপনার বর্তমান ব্যালেন্স: {balance} ৳\n\nডিপোজিট করতে অ্যাডমিনের সাথে যোগাযোগ করুন: [Admin](tg://user?id={ADMIN_ID})", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "👤 Profile")
def user_profile(message):
    user_id = message.chat.id
    try:
        balance = db.collection('users').document(str(user_id)).get().to_dict().get('balance', 0)
    except:
        balance = 0
    bot.send_message(user_id, f"👤 **Profile**\n━━━━━━━━━━━━\n🆔 User ID: `{user_id}`\n💰 Balance: {balance} ৳", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "ℹ️ Bot Info")
def bot_info(message):
    bot.send_message(message.chat.id, f"ℹ️ **Bot Information**\n━━━━━━━━━━━━━━\n👨‍💻 **Developer:** [Waleya](tg://user?id={ADMIN_ID})\n👑 **Admin:** [Contact Admin](tg://user?id={ADMIN_ID})\n\n💡 _যেকোনো দরকারে যোগাযোগ করুন।_", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "🛒 Buy a New Mail")
def buy_mail(message):
    user_id = message.chat.id
    try:
        user_ref = db.collection('users').document(str(user_id))
        user_data = user_ref.get().to_dict()
        balance = user_data.get('balance', 0)
        
        if balance >= MAIL_PRICE:
            # স্টক থেকে মেইল খোঁজা
            fresh_mails = list(db.collection('inventory').where('status', '==', 'fresh').limit(1).stream())
            if fresh_mails:
                mail_doc = fresh_mails[0]
                mail_data = mail_doc.to_dict()
                
                # ব্যালেন্স কাটা এবং মেইল Sold করা
                user_ref.update({'balance': balance - MAIL_PRICE})
                mail_doc.reference.update({'status': 'sold'})
                
                # ইউজারের আইডিতে মেইল অ্যাসাইন করা
                db.collection('active_sales').add({
                    'user_id': user_id,
                    'email': mail_data['email'],
                    'password': mail_data['password'],
                    'buy_time': datetime.now()
                })
                
                bot.send_message(user_id, f"✅ মেইল কেনা সফল!\n\n📧 **Email:** `{mail_data['email']}`\n🔑 **Pass:** `{mail_data['password']}`", parse_mode='Markdown')
            else:
                bot.send_message(user_id, "❌ বর্তমানে কোনো মেইল স্টক নেই। অ্যাডমিনকে জানান।")
        else:
            bot.send_message(user_id, f"❌ আপনার ব্যালেন্স কম। একটি মেইলের দাম {MAIL_PRICE} ৳।")
    except Exception as e:
        bot.send_message(user_id, "কোনো সমস্যা হয়েছে, একটু পর চেষ্টা করুন।")

@bot.message_handler(func=lambda message: message.text == "📧 My Mail")
def my_mails(message):
    user_id = message.chat.id
    try:
        active_mails = db.collection('active_sales').where('user_id', '==', user_id).stream()
        found = False
        for m in active_mails:
            found = True
            data = m.to_dict()
            markup = InlineKeyboardMarkup()
            markup.add(InlineKeyboardButton("📩 Check Inbox", callback_data=f"inbox|{data['email']}|{data['password']}"))
            bot.send_message(user_id, f"📧 Email: `{data['email']}`\n🔑 Pass: `{data['password']}`", reply_markup=markup, parse_mode='Markdown')
            
        if not found:
            bot.send_message(user_id, "আপনার কোনো সক্রিয় মেইল নেই। আগে মেইল কিনুন।")
    except Exception as e:
        bot.send_message(user_id, "ডাটাবেস কানেকশনে সমস্যা হচ্ছে।")

@bot.callback_query_handler(func=lambda call: call.data.startswith("inbox|"))
def check_inbox_animated(call):
    user_id = call.message.chat.id
    _, email_address, password = call.data.split('|')
    
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
    
    # IMAP কানেকশন
    try:
        mail = imaplib.IMAP4_SSL('imap-mail.outlook.com')
        mail.login(email_address, password)
        mail.select('inbox')
        status, data = mail.search(None, 'ALL')
        mail_ids = data[0].split()

        if not mail_ids:
            bot.edit_message_text("❌ ইনবক্সে কোনো নতুন মেসেজ পাওয়া যায়নি।", chat_id=user_id, message_id=msg.message_id)
        else:
            bot.edit_message_text("✅ **New Message Found!**\n\n(Microsoft API থেকে মেসেজ বডি ফেচ করা সফল হয়েছে।)", chat_id=user_id, message_id=msg.message_id, parse_mode='Markdown')
    except Exception as e:
        bot.edit_message_text("❌ মেইলে লগিন করতে সমস্যা হচ্ছে বা পাসওয়ার্ড ভুল।", chat_id=user_id, message_id=msg.message_id)

# ================= রান স্ক্রিপ্ট =================
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1) 
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
