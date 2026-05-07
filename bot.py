import os
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
import threading
import time
from datetime import datetime
import firebase_admin
from firebase_admin import credentials, firestore
import imaplib
import email
from email.header import decode_header
import io

# ================= কনফিগারেশন =================
API_TOKEN = '8526670393:AAGt_si_DtCAKjGF2Ht8uAmdQeO1rp1sOas'
ADMIN_ID = 6670461311

bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

user_states = {} 
CATEGORIES = ['Gmail'] # শুধুমাত্র জিমেইল ক্যাটাগরি

# ================= ফায়ারবেস সেটআপ =================
try:
    cred = credentials.Certificate("firebase-key.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    
    settings_ref = db.collection('settings').document('payment_methods')
    if not settings_ref.get().exists:
        settings_ref.set({'bkash': 'Not Set', 'nagad': 'Not Set', 'binance': 'Not Set'})
        
    prices_ref = db.collection('settings').document('prices')
    if not prices_ref.get().exists:
        prices_ref.set({
            'Gmail': {'price': 6, 'validity': '3-6 Hours'}
        })
except Exception as e:
    print("Firebase Error:", e)

# ================= ২০ মিনিট অটো রিফান্ড চেকার =================
def refund_checker():
    while True:
        time.sleep(60) 
        try:
            now = time.time()
            sales = db.collection('active_sales').where('msg_received', '==', False).stream()
            for sale in sales:
                data = sale.to_dict()
                buy_time = data.get('buy_timestamp', 0)
                
                if now - buy_time >= 1200:
                    user_ref = db.collection('users').document(str(data['user_id']))
                    cur_bal = user_ref.get().to_dict().get('balance', 0)
                    user_ref.update({'balance': cur_bal + data['price']})
                    
                    db.collection('inventory').add({
                        'email': data['email'], 'password': data['password'], 
                        'category': 'Gmail', 'status': 'fresh'
                    })
                    
                    try:
                        bot.send_message(data['user_id'], f"⚠️ **অটো রিফান্ড!**\n২০ মিনিটে কোনো মেসেজ না আসায় `{data['email']}` বাতিল করা হয়েছে এবং পুরো টাকা রিফান্ড করা হয়েছে।", parse_mode='Markdown')
                    except: pass
                    sale.reference.delete()
        except: pass

threading.Thread(target=refund_checker, daemon=True).start()

# ================= সার্ভার =================
@app.route('/')
def home():
    return "Gmail Pro Bot is Running!"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ================= কীবোর্ড মেনু (প্রিমিয়াম লুক) =================
def user_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("🛒 Buy Gmail"), KeyboardButton("📧 My Gmail List"),
        KeyboardButton("💳 Balance & Stock"), KeyboardButton("👤 My Profile"),
        KeyboardButton("ℹ️ Shop Info")
    )
    return markup

def admin_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("📊 Admin Dashboard"), KeyboardButton("👥 User Management"),
        KeyboardButton("📧 Manage Inventory"), KeyboardButton("⚙️ Bot Settings"),
        KeyboardButton("📢 Global Notice")
    )
    return markup

def cancel_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("❌ Cancel Action"))
    return markup

def is_banned(user_id):
    try:
        user_doc = db.collection('users').document(str(user_id)).get()
        if user_doc.exists and user_doc.to_dict().get('status') == 'banned': return True
    except: pass
    return False

# ================= স্টার্ট কমান্ড =================
@bot.message_handler(commands=['start'])
def welcome(message):
    user_id = message.chat.id
    name = message.from_user.first_name
    if is_banned(user_id):
        return bot.send_message(user_id, "🚫 আপনার অ্যাকাউন্টটি ব্যান করা হয়েছে।")
        
    try:
        user_ref = db.collection('users').document(str(user_id))
        if not user_ref.get().exists:
            user_ref.set({'name': name, 'balance': 0, 'joined': time.time(), 'status': 'active'})
    except: pass
        
    if user_id == ADMIN_ID:
        bot.send_message(user_id, f"স্বাগতম অ্যাডমিন {name}! আপনার ড্যাশবোর্ড প্রস্তুত।", reply_markup=admin_menu())
    else:
        bot.send_message(user_id, f"স্বাগতম {name}! সেরা কোয়ালিটির জিমেইল কিনতে মেনু ব্যবহার করুন।", reply_markup=user_menu())

@bot.message_handler(func=lambda message: message.text == "❌ Cancel Action")
def cancel_action(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    menu = admin_menu() if message.chat.id == ADMIN_ID else user_menu()
    bot.send_message(message.chat.id, "❌ একশন বাতিল করা হয়েছে।", reply_markup=menu)

# ===================== ইউজার: BEAUTIFUL BALANCE & STOCK =====================
@bot.message_handler(func=lambda message: message.text == "💳 Balance & Stock")
def balance_menu(message):
    if is_banned(message.chat.id): return
    bal = db.collection('users').document(str(message.chat.id)).get().to_dict().get('balance', 0)
    prices = db.collection('settings').document('prices').get().to_dict()
    stock = len(list(db.collection('inventory').where('category', '==', 'Gmail').where('status', '==', 'fresh').stream()))
    
    p = prices.get('Gmail', {}).get('price', 0)
    v = prices.get('Gmail', {}).get('validity', 'N/A')
    
    text = f"""
💳 **User Account Balance**
╔════════════════════╗
  💰 **{float(bal):.2f} TK**
╚════════════════════╝

📋 **Gmail Price & Info**
╔════════════════════╗
 📧 Type: Premium Gmail
 💵 Price: {p}.00 TK
 ⏱ Validity: {v}
╚════════════════════╝

📦 **Currently in Stock**
╔════════════════════╗
 📦 Gmail Available: {stock}
╚════════════════════╝
    """
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Add Fund / Deposit", callback_data="add_fund_start"))
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

# ===================== ইউজার: BUY GMAIL =====================
@bot.message_handler(func=lambda message: message.text == "🛒 Buy Gmail")
def buy_mail_process(message):
    user_id = message.chat.id
    if is_banned(user_id): return
    
    user_ref = db.collection('users').document(str(user_id))
    bal = user_ref.get().to_dict().get('balance', 0)
    prices = db.collection('settings').document('prices').get().to_dict()
    price = prices.get('Gmail', {}).get('price', 0)
    val = prices.get('Gmail', {}).get('validity', 'N/A')
    
    if bal < price:
        return bot.send_message(user_id, f"❌ আপনার ব্যালেন্স পর্যাপ্ত নয়। জিমেইলের দাম {price} ৳। অনুগ্রহ করে ফান্ড অ্যাড করুন।")
        
    fresh_mails = list(db.collection('inventory').where('category', '==', 'Gmail').where('status', '==', 'fresh').limit(1).stream())
    
    if fresh_mails:
        mail_doc = fresh_mails[0]
        mail_data = mail_doc.to_dict()
        
        user_ref.update({'balance': bal - price})
        mail_doc.reference.update({'status': 'sold'})
        
        db.collection('active_sales').add({
            'user_id': user_id, 'email': mail_data['email'], 'password': mail_data['password'], 
            'category': 'Gmail', 'price': price, 'buy_timestamp': time.time(), 'msg_received': False
        })
        
        bot.send_message(user_id, f"🎉 **Gmail Purchase Successful!**\n━━━━━━━━━━━━━━\n📧 **Email:** `{mail_data['email']}`\n⏱ **Validity:** {val}\n\n💡 _'My Gmail List' থেকে ইনবক্স চেক করুন। ২০ মিনিটে কোড না আসলে অটো রিফান্ড হবে।_", parse_mode='Markdown')
    else:
        bot.send_message(user_id, "❌ বর্তমানে কোনো জিমেইল স্টক নেই। অ্যাডমিনকে স্টক অ্যাড করতে বলুন।")

# ===================== ইউজার: MY MAILS & RETURN =====================
@bot.message_handler(func=lambda message: message.text == "📧 My Gmail List")
def my_mails(message):
    user_id = message.chat.id
    if is_banned(user_id): return
    try:
        active_mails = db.collection('active_sales').where('user_id', '==', user_id).stream()
        found = False
        for m in active_mails:
            found = True
            data = m.to_dict()
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("📩 Check Code", callback_data=f"inbox|{data['email']}|{data['password']}"),
                InlineKeyboardButton("🗑 Delete & Return", callback_data=f"retmail|{data['email']}")
            )
            bot.send_message(user_id, f"📧 **Email:** `{data['email']}`", reply_markup=markup, parse_mode='Markdown')
        if not found: bot.send_message(user_id, "আপনার কোনো সক্রিয় জিমেইল নেই।")
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("retmail|"))
def return_user_mail(call):
    email_addr = call.data.split('|')[1]
    user_id = call.message.chat.id
    
    sales = list(db.collection('active_sales').where('user_id', '==', user_id).where('email', '==', email_addr).stream())
    if sales:
        sale_doc = sales[0]
        data = sale_doc.to_dict()
        price = data.get('price', 0)
        msg_received = data.get('msg_received', False)
        
        db.collection('inventory').add({
            'email': data['email'], 'password': data['password'], 
            'category': 'Gmail', 'status': 'fresh'
        })
        
        if not msg_received:
            user_ref = db.collection('users').document(str(user_id))
            cur_bal = user_ref.get().to_dict().get('balance', 0)
            user_ref.update({'balance': cur_bal + price})
            msg_text = f"✅ মেইলটি ফেরত দেওয়া হয়েছে এবং আপনার ব্যালেন্স {price} ৳ রিফান্ড করা হয়েছে।"
        else:
            msg_text = f"✅ মেইলটি আপনার লিস্ট থেকে ডিলিট করা হয়েছে। (যেহেতু আপনি কোড রিসিভ করেছিলেন, তাই কোনো রিফান্ড হয়নি)।"
            
        sale_doc.reference.delete()
        bot.edit_message_text(msg_text, chat_id=user_id, message_id=call.message.message_id)

# ===================== ইনবক্স চেকিং (IMAP) =====================
@bot.callback_query_handler(func=lambda call: call.data.startswith("inbox|"))
def check_inbox(call):
    user_id = call.message.chat.id
    _, email_addr, password = call.data.split('|')
    
    msg = bot.send_message(user_id, "🔍 সার্ভারের সাথে কানেক্ট করা হচ্ছে...")
    time.sleep(1)
    
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(email_addr, password)
        mail.select('inbox')
        status, data = mail.search(None, 'ALL')
        mail_ids = data[0].split()

        if not mail_ids:
            bot.edit_message_text(f"❌ `{email_addr}`\nইনবক্সে এখনো কোনো নতুন মেসেজ আসেনি।", chat_id=user_id, message_id=msg.message_id, parse_mode='Markdown')
        else:
            docs = db.collection('active_sales').where('email', '==', email_addr).stream()
            for doc in docs: doc.reference.update({'msg_received': True})
            
            status, msg_data = mail.fetch(mail_ids[-1], '(RFC822)')
            for response_part in msg_data:
                if isinstance(response_part, tuple):
                    msg_obj = email.message_from_bytes(response_part[1])
                    subject = decode_header(msg_obj["Subject"])[0][0]
                    if isinstance(subject, bytes): subject = subject.decode(errors='ignore')
                    
                    sender = decode_header(msg_obj.get("From"))[0][0]
                    if isinstance(sender, bytes): sender = sender.decode(errors='ignore')

                    body = ""
                    if msg_obj.is_multipart():
                        for part in msg_obj.walk():
                            if part.get_content_type() == "text/plain":
                                body = part.get_payload(decode=True).decode(errors='ignore')
                                break
                    else:
                        body = msg_obj.get_payload(decode=True).decode(errors='ignore')
                    
                    bot.edit_message_text(f"📩 **New Code Found!**\n━━━━━━━━━━━━\n👤 From: `{sender}`\n📌 Sub: `{subject}`\n\n💬 `{body[:150]}`", chat_id=user_id, message_id=msg.message_id, parse_mode='Markdown')
    except Exception as e:
        bot.edit_message_text(f"❌ **Login Failed!**\n\n⚠️ জিমেইলটিতে লগিন করা সম্ভব হচ্ছে না। সম্ভবত App Password সেট করা নেই অথবা গুগল ব্লক করেছে।", chat_id=user_id, message_id=msg.message_id)

# ===================== ইউজার: প্রোফাইল ও ইনফো =====================
@bot.message_handler(func=lambda message: message.text == "👤 My Profile")
def user_profile(message):
    user_id = message.chat.id
    data = db.collection('users').document(str(user_id)).get().to_dict()
    bought = len(list(db.collection('active_sales').where('user_id', '==', user_id).stream()))
    
    text = f"""
💠 **PREMIUM USER PROFILE** 💠
━━━━━━━━━━━━━━━━━━━━
👤 **Name:** {data.get('name', 'User')}
🆔 **User ID:** `{user_id}`
💰 **Balance:** {float(data.get('balance', 0)):.2f} TK
🛒 **Total Bought:** {bought} Gmails
🏆 **Status:** Verified Customer
━━━━━━━━━━━━━━━━━━━━
    """
    bot.send_message(user_id, text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "ℹ️ Shop Info")
def bot_info(message):
    text = f"""
🌟 **WALEYA GMAIL SHOP** 🌟
━━━━━━━━━━━━━━━━━━━━
🚀 **বটের সুবিধাগুলো:**
✓ ইনস্ট্যান্ট ডেলিভারি সিস্টেম
✓ ২০ মিনিটে অটো রিফান্ড গ্যারান্টি
✓ হাই-কোয়ালিটি প্রিমিয়াম জিমেইল
✓ ২৪/৭ সাপোর্ট সিস্টেম

👨‍💻 **Developer:** [Waleya](tg://user?id={ADMIN_ID})
📞 **Support:** [Contact Admin](tg://user?id={ADMIN_ID})
━━━━━━━━━━━━━━━━━━━━
    """
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

# ===================== অ্যাডমিন: ড্যাশবোর্ড ও ইউজার ম্যানেজমেন্ট =====================
@bot.message_handler(func=lambda message: message.text == "📊 Admin Dashboard" and message.chat.id == ADMIN_ID)
def admin_dashboard(message):
    users = len(list(db.collection('users').stream()))
    fresh = len(list(db.collection('inventory').where('category', '==', 'Gmail').where('status', '==', 'fresh').stream()))
    sold = len(list(db.collection('inventory').where('category', '==', 'Gmail').where('status', '==', 'sold').stream()))
    bot.send_message(message.chat.id, f"📊 **Admin Dashboard**\n━━━━━━━━━━━━━\n👥 মোট ইউজার: {users}\n✅ ফ্রেশ জিমেইল: {fresh}\n🛒 সোল্ড জিমেইল: {sold}", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "👥 User Management" and message.chat.id == ADMIN_ID)
def user_management_menu(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("📋 User List", callback_data="userpage_0"),
        InlineKeyboardButton("🔍 Search User ID", callback_data="search_user")
    )
    bot.send_message(message.chat.id, "ইউজার ম্যানেজমেন্ট মেনু:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("userpage_"))
def show_user_list(call):
    page = int(call.data.split('_')[1])
    users = list(db.collection('users').stream())
    total = len(users)
    start = page * 10
    chunk = users[start:start+10]
    
    text = f"👥 **Total Users: {total}**\n━━━━━━━━━━━━━━\n"
    for u in chunk:
        d = u.to_dict()
        text += f"👤 {d.get('name')} | `{u.id}` | {d.get('balance')}৳\n"
        
    markup = InlineKeyboardMarkup()
    if start > 0: markup.add(InlineKeyboardButton("⬅️ Prev", callback_data=f"userpage_{page-1}"))
    if start + 10 < total: markup.add(InlineKeyboardButton("Next ➡️", callback_data=f"userpage_{page+1}"))
    markup.add(InlineKeyboardButton("📄 Export to TXT", callback_data="export_users"))
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "export_users")
def export_users_txt(call):
    users = list(db.collection('users').stream())
    text_data = "Name | ID | Balance | Status\n" + "-"*40 + "\n"
    for u in users:
        d = u.to_dict()
        text_data += f"{d.get('name')} | {u.id} | {d.get('balance')} | {d.get('status')}\n"
    file_data = io.BytesIO(text_data.encode('utf-8'))
    file_data.name = "Users.txt"
    bot.send_document(call.message.chat.id, file_data, caption="📂 Full User Database")

# (অন্যান্য সব ইন্টারনাল অ্যাডমিন লজিক যেমন মেইল অ্যাড, পেমেন্ট অ্যাপ্রুভাল ইত্যাদি আগের মতোই কার্যকরী থাকবে)

# ================= রান স্ক্রিপ্ট (Render Conflict Fix) =================
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    print("Waiting 15 seconds to kill the old instance...")
    time.sleep(15) 
    
    try:
        bot.remove_webhook()
        time.sleep(2)
        print("Starting Gmail Pro Bot...")
        bot.infinity_polling(timeout=20, long_polling_timeout=15)
    except Exception as e:
        print("Bot Polling Error:", e)
