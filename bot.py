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
from email.header import decode_header

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

# ================= ফ্লাস্ক সার্ভার (২৪/৭ লাইভ) =================
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


# ===================== অ্যাডমিন প্যানেল =====================

@bot.message_handler(func=lambda message: message.text == "📊 Dashboard" and message.chat.id == ADMIN_ID)
def admin_dashboard(message):
    try:
        users_count = len(list(db.collection('users').stream()))
        mails_count = len(list(db.collection('inventory').where('status', '==', 'fresh').stream()))
        bot.send_message(message.chat.id, f"📊 **Admin Dashboard**\n━━━━━━━━━━━━━\n👥 মোট ইউজার: {users_count}\n✅ স্টকে মেইল আছে: {mails_count} টি\n💰 মেইলের বর্তমান দাম: {MAIL_PRICE} ৳", parse_mode='Markdown')
    except:
        bot.send_message(message.chat.id, "ডাটাবেস কানেক্ট করতে সমস্যা হচ্ছে।")

@bot.message_handler(func=lambda message: message.text == "➕ Add Mails" and message.chat.id == ADMIN_ID)
def add_mails_start(message):
    msg = bot.send_message(message.chat.id, "নতুন মেইলগুলো নিচে দিন।\nফরম্যাট: `email@hotmail.com|password`\nএকাধিক মেইল দিতে প্রতি লাইনে একটি করে দিন।", parse_mode='Markdown')
    bot.register_next_step_handler(msg, process_add_mails)

def process_add_mails(message):
    lines = message.text.split('\n')
    added = 0
    for line in lines:
        if '|' in line:
            email_addr, password = line.split('|')
            try:
                db.collection('inventory').add({'email': email_addr.strip(), 'password': password.strip(), 'status': 'fresh'})
                added += 1
            except:
                pass
    bot.send_message(message.chat.id, f"✅ মোট {added} টি মেইল ডাটাবেসে সফলভাবে যুক্ত হয়েছে!")

@bot.message_handler(func=lambda message: message.text == "👥 User Management" and message.chat.id == ADMIN_ID)
def user_management(message):
    msg = bot.send_message(message.chat.id, "ব্যালেন্স অ্যাড করতে User ID এবং টাকার পরিমাণ দিন।\nফরম্যাট: `UserID|Amount`", parse_mode='Markdown')
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


# ===================== ইউজার প্যানেল =====================

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
            fresh_mails = list(db.collection('inventory').where('status', '==', 'fresh').limit(1).stream())
            if fresh_mails:
                mail_doc = fresh_mails[0]
                mail_data = mail_doc.to_dict()
                
                user_ref.update({'balance': balance - MAIL_PRICE})
                mail_doc.reference.update({'status': 'sold'})
                
                db.collection('active_sales').add({
                    'user_id': user_id,
                    'email': mail_data['email'],
                    'password': mail_data['password'],
                    'buy_time': datetime.now()
                })
                
                # ইউজারের থেকে পাসওয়ার্ড হাইড করা হলো 
                bot.send_message(user_id, f"🎉 **মেইল কেনা সফল হয়েছে!**\n━━━━━━━━━━━━━━\n📧 **Email:** `{mail_data['email']}`\n\n💡 _মেইলে মেসেজ আসলে নিচের মেনু থেকে 'My Mail'-এ গিয়ে ইনবক্স চেক করুন।_", parse_mode='Markdown')
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
            # পাসওয়ার্ড শুধু ব্যাকএন্ডের জন্য কলব্যাকে লুকানো থাকছে, ইউজার দেখবে না
            markup.add(InlineKeyboardButton("📩 Check Inbox", callback_data=f"inbox|{data['email']}|{data['password']}"))
            
            # ইউজারের ভিউ থেকে পাসওয়ার্ড হাইড
            bot.send_message(user_id, f"📧 **Email:** `{data['email']}`", reply_markup=markup, parse_mode='Markdown')
            
        if not found:
            bot.send_message(user_id, "আপনার কোনো সক্রিয় মেইল নেই। আগে মেইল কিনুন।")
    except Exception as e:
        bot.send_message(user_id, "ডাটাবেস কানেকশনে সমস্যা হচ্ছে।")

# ================= ইনবক্স চেকিং এবং রিয়েল মেসেজ এক্সট্রাক্ট =================

@bot.callback_query_handler(func=lambda call: call.data.startswith("inbox|"))
def check_inbox_animated(call):
    user_id = call.message.chat.id
    _, email_address, password = call.data.split('|')
    
    # সুন্দর টেক্সট অ্যানিমেশন
    frames = [
        "🚀 সার্ভারের সাথে সংযোগ স্থাপন করা হচ্ছে...",
        "🔐 মেইলে সিকিউর লগিন করা হচ্ছে...",
        "📥 ইনবক্স চেক করা হচ্ছে...",
        "🔎 নতুন মেসেজ বা OTP খোঁজা হচ্ছে..."
    ]
    
    msg = bot.send_message(user_id, "অপেক্ষা করুন...")
    
    for frame in frames:
        time.sleep(0.6)
        bot.edit_message_text(frame, chat_id=user_id, message_id=msg.message_id)
    
    # IMAP কানেকশন এবং মেসেজ রিডিং
    try:
        mail = imaplib.IMAP4_SSL('imap-mail.outlook.com')
        mail.login(email_address, password)
        mail.select('inbox')
        status, data = mail.search(None, 'ALL')
        mail_ids = data[0].split()

        if not mail_ids:
            bot.edit_message_text(f"❌ `{email_address}`\nএই ইনবক্সে এখনো কোনো নতুন মেসেজ বা কোড আসেনি। একটু পর আবার চেষ্টা করুন।", chat_id=user_id, message_id=msg.message_id, parse_mode='Markdown')
        else:
            # সবচেয়ে লেটেস্ট মেসেজটি বের করা
            latest_email_id = mail_ids[-1]
            status, msg_data = mail.fetch(latest_email_id, '(RFC822)')
            
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg_obj = email.message_from_bytes(response_part[1])
                    
                    # সাবজেক্ট ডিকোড করা
                    subject, encoding = decode_header(msg_obj["Subject"])[0]
                    if isinstance(subject, bytes):
                        subject = subject.decode(encoding if encoding else "utf-8")
                    
                    # সেন্ডার (From) ডিকোড করা
                    sender, encoding = decode_header(msg_obj.get("From"))[0]
                    if isinstance(sender, bytes):
                        sender = sender.decode(encoding if encoding else "utf-8")

                    # মেইলের বডি থেকে কোড/টেক্সট বের করা
                    body = ""
                    if msg_obj.is_multipart():
                        for part in msg_obj.walk():
                            if part.get_content_type() == "text/plain":
                                try:
                                    body = part.get_payload(decode=True).decode()
                                    break
                                except: pass
                    else:
                        try:
                            body = msg_obj.get_payload(decode=True).decode()
                        except: pass
                    
                    # বডির প্রথম ২০০ অক্ষর নেওয়া (যাতে অনেক বড় মেসেজ না আসে)
                    body_snippet = body[:200].strip() if body else "No text found. Check subject."
                    
                    final_text = f"✅ **New Message Found!**\n━━━━━━━━━━━━━━\n👤 **From:** `{sender}`\n📌 **Subject:** `{subject}`\n\n💬 **Code/Message:**\n`{body_snippet}`\n━━━━━━━━━━━━━━"
                    
                    bot.edit_message_text(final_text, chat_id=user_id, message_id=msg.message_id, parse_mode='Markdown')
    except Exception as e:
        bot.edit_message_text("❌ সার্ভারে কানেক্ট করতে সমস্যা হচ্ছে।", chat_id=user_id, message_id=msg.message_id)

# ================= রান স্ক্রিপ্ট =================
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    bot.remove_webhook()
    time.sleep(1) 
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
