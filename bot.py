import os
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
import threading
import time
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
CATEGORIES = ['Gmail', 'Hotmail', 'Outlook', 'Temp Mail']

# ================= ফায়ারবেস সেটআপ =================
try:
    cred = credentials.Certificate("firebase-key.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    
    # প্রাথমিক সেটিংস চেক
    settings_ref = db.collection('settings').document('payment_methods')
    if not settings_ref.get().exists:
        settings_ref.set({'bkash': 'Not Set', 'nagad': 'Not Set', 'binance': 'Not Set'})
        
    prices_ref = db.collection('settings').document('prices')
    if not prices_ref.get().exists:
        prices_ref.set({
            'Gmail': {'price': 6, 'validity': '6-10 Hours'},
            'Hotmail': {'price': 1, 'validity': '6-12 Month'},
            'Outlook': {'price': 1, 'validity': '6-12 Month'},
            'Temp Mail': {'price': 2, 'validity': '1 Hour'}
        })
except Exception as e:
    print("Firebase Error:", e)

# ================= ২০ মিনিট রিফান্ড চেকার =================
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
                    user_data = user_ref.get().to_dict()
                    cur_bal = user_data.get('balance', 0)
                    user_ref.update({'balance': cur_bal + data['price']})
                    
                    db.collection('inventory').add({
                        'email': data['email'], 'password': data['password'], 
                        'category': data.get('category', 'Unknown'), 'status': 'fresh',
                        'linked_gmail': data.get('linked_gmail'),
                        'linked_gmail_pw': data.get('linked_gmail_pw')
                    })
                    
                    try:
                        bot.send_message(data['user_id'], f"⚠️ **অটো রিফান্ড!**\n২০ মিনিটে কোনো মেসেজ না আসায় `{data['email']}` বাতিল করা হয়েছে এবং আপনার {data['price']} ৳ রিফান্ড করা হয়েছে।", parse_mode='Markdown')
                    except: pass
                    sale.reference.delete()
        except: pass

threading.Thread(target=refund_checker, daemon=True).start()

# ================= সার্ভার =================
@app.route('/')
def home():
    return "Waleya Premium Mail Bot is Running with Forwarding System!"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ================= কীবোর্ড মেনু =================
def user_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("🛒 Buy Mail"), KeyboardButton("📧 My Mail"),
        KeyboardButton("💳 Balance"), KeyboardButton("👤 Profile"),
        KeyboardButton("ℹ️ Bot Info")
    )
    return markup

def admin_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("📊 Dashboard"), KeyboardButton("👥 User Management"),
        KeyboardButton("📧 Manage Mails"), KeyboardButton("⚙️ Settings"),
        KeyboardButton("📢 Send Notice")
    )
    return markup

def cancel_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("❌ Cancel"))
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
        
    user_ref = db.collection('users').document(str(user_id))
    if not user_ref.get().exists:
        user_ref.set({'name': name, 'balance': 0, 'joined': time.time(), 'status': 'active'})
        
    if user_id == ADMIN_ID:
        bot.send_message(user_id, f"স্বাগতম অ্যাডমিন {name}!", reply_markup=admin_menu())
    else:
        bot.send_message(user_id, f"আমাদের শপে স্বাগতম, {name}!", reply_markup=user_menu())

@bot.message_handler(func=lambda message: message.text == "❌ Cancel")
def cancel_action(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    menu = admin_menu() if message.chat.id == ADMIN_ID else user_menu()
    bot.send_message(message.chat.id, "❌ একশন বাতিল করা হয়েছে।", reply_markup=menu)

# ===================== অ্যাডমিন: FORWARDING SETUP =====================
@bot.callback_query_handler(func=lambda call: call.data == "setup_forwarding")
def forwarding_setup_menu(call):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("➕ Add Forwarding Gmail", callback_data="add_fwd_gmail"),
        InlineKeyboardButton("📋 View Gmails", callback_data="view_fwd_gmails")
    )
    bot.edit_message_text("⚙️ **Forwarding Settings**\nআউটলুক কোড রিসিভ করার জন্য জিমেইল সেটআপ করুন।", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == "add_fwd_gmail")
def ask_fwd_gmail(call):
    msg = bot.send_message(call.message.chat.id, "সেন্ট্রাল জিমেইল এবং App Password দিন।\nফরম্যাট: `email|app_password`", parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, save_fwd_gmail)

def save_fwd_gmail(message):
    if message.text == "❌ Cancel": return cancel_action(message)
    try:
        email_addr, app_pw = message.text.split('|')
        db.collection('forwarding_gmails').add({'email': email_addr.strip(), 'password': app_pw.strip()})
        bot.send_message(message.chat.id, "✅ ফরওয়ার্ডিং জিমেইল সফলভাবে যুক্ত হয়েছে!", reply_markup=admin_menu())
    except:
        bot.send_message(message.chat.id, "❌ ফরম্যাট ভুল। আবার চেষ্টা করুন।", reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda call: call.data == "view_fwd_gmails")
def view_fwd_gmails(call):
    gmails = db.collection('forwarding_gmails').stream()
    text = "📋 **Forwarding Gmail List:**\n\n"
    markup = InlineKeyboardMarkup()
    found = False
    for g in gmails:
        found = True
        d = g.to_dict()
        text += f"📧 `{d['email']}`\n"
        markup.add(InlineKeyboardButton(f"🗑 Delete {d['email'][:15]}...", callback_data=f"delfwd_{g.id}"))
    
    if not found: text = "কোনো ফরওয়ার্ডিং জিমেইল সেট করা নেই।"
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("delfwd_"))
def delete_fwd_gmail(call):
    doc_id = call.data.split('_')[1]
    db.collection('forwarding_gmails').document(doc_id).delete()
    bot.answer_callback_query(call.id, "ডিলিট করা হয়েছে।")
    view_fwd_gmails(call)

# ===================== অ্যাডমিন: MANAGE MAILS (Updated) =====================
@bot.message_handler(func=lambda message: message.text == "📧 Manage Mails" and message.chat.id == ADMIN_ID)
def manage_mails(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("➕ Add Mails", callback_data="add_mails"),
        InlineKeyboardButton("📋 Mail List", callback_data="view_mails")
    )
    bot.send_message(message.chat.id, "মেইল ম্যানেজমেন্ট মেনু:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "add_mails")
def select_category_for_add(call):
    markup = InlineKeyboardMarkup(row_width=2)
    for cat in CATEGORIES:
        markup.add(InlineKeyboardButton(cat, callback_data=f"addmailcat_{cat}"))
    bot.edit_message_text("কোন ক্যাটাগরিতে মেইল অ্যাড করবেন?", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("addmailcat_"))
def ask_link_gmail(call):
    category = call.data.split('_')[1]
    gmails = list(db.collection('forwarding_gmails').stream())
    
    if not gmails and category != 'Gmail':
        return bot.send_message(call.message.chat.id, "⚠️ আগে একটি ফরওয়ার্ডিং জিমেইল সেটআপ করুন (Settings > Forwarding Setup)।")
        
    markup = InlineKeyboardMarkup(row_width=1)
    if category == 'Gmail':
        markup.add(InlineKeyboardButton("No Linking (Direct Login)", callback_data=f"linknone_{category}"))
    else:
        for g in gmails:
            d = g.to_dict()
            markup.add(InlineKeyboardButton(f"Link with {d['email']}", callback_data=f"link_{g.id}_{category}"))
            
    bot.edit_message_text(f"**{category}** এর জন্য ফরওয়ার্ডিং জিমেইল সিলেক্ট করুন:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith("link_") or call.data.startswith("linknone_"))
def enter_mails_to_add(call):
    if call.data.startswith("linknone_"):
        category = call.data.split('_')[1]
        gmail_info = None
    else:
        _, g_id, category = call.data.split('_')
        gmail_info = db.collection('forwarding_gmails').document(g_id).get().to_dict()
        
    msg = bot.send_message(call.message.chat.id, f"**{category}** এর মেইলগুলো নিচে দিন।\nফরম্যাট: `email|password`", parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, process_add_mails, category, gmail_info)

def process_add_mails(message, category, gmail_info):
    if message.text == "❌ Cancel": return cancel_action(message)
    lines = message.text.split('\n')
    added = 0
    for line in lines:
        if '|' in line:
            email_addr, password = line.split('|')
            data = {
                'email': email_addr.strip(), 
                'password': password.strip(), 
                'category': category, 
                'status': 'fresh'
            }
            if gmail_info:
                data['linked_gmail'] = gmail_info['email']
                data['linked_gmail_pw'] = gmail_info['password']
                
            db.collection('inventory').add(data)
            added += 1
    bot.send_message(message.chat.id, f"✅ **{category}**-এ {added} টি মেইল যুক্ত হয়েছে!", reply_markup=admin_menu(), parse_mode='Markdown')

# [Mail List, Search User, Dashboard, Payments Logic remain same as previous code...]
# নিচের ফাংশনগুলো আগের কোড থেকে কপি করা হয়েছে কিন্তু লজিক ঠিক রাখা হয়েছে:

@bot.callback_query_handler(func=lambda call: call.data == "view_mails")
def view_mails(call):
    mails = list(db.collection('inventory').limit(10).stream())
    if not mails: return bot.send_message(call.message.chat.id, "স্টকে কোনো মেইল নেই।")
    text = "📋 **সর্বশেষ ১০টি মেইল:**\n"
    markup = InlineKeyboardMarkup()
    for m in mails:
        d = m.to_dict()
        text += f"📧 `{d['email']}` - {'🟢 Fresh' if d['status'] == 'fresh' else '🔴 Sold'}\n"
        markup.add(InlineKeyboardButton(f"🗑 Delete {d['email'][:15]}", callback_data=f"delmail_{m.id}"))
    bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("delmail_"))
def delete_mail(call):
    db.collection('inventory').document(call.data.split('_')[1]).delete()
    bot.answer_callback_query(call.id, "ডিলিট হয়েছে।")

@bot.message_handler(func=lambda message: message.text == "⚙️ Settings" and message.chat.id == ADMIN_ID)
def admin_settings(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("💳 Payment Setup", callback_data="setup_payments"),
        InlineKeyboardButton("🏷 Price & Time Setup", callback_data="setup_prices"),
        InlineKeyboardButton("⚙️ Forwarding Setup", callback_data="setup_forwarding")
    )
    bot.send_message(message.chat.id, "⚙️ **Settings Menu**", parse_mode='Markdown', reply_markup=markup)

# ===================== ইউজার ফাংশনসমূহ (Buy Mail, My Mail) =====================

@bot.message_handler(func=lambda message: message.text == "🛒 Buy Mail")
def buy_mail_menu(message):
    if is_banned(message.chat.id): return
    prices = db.collection('settings').document('prices').get().to_dict()
    markup = InlineKeyboardMarkup(row_width=1)
    for cat in CATEGORIES:
        stock = len(list(db.collection('inventory').where('category', '==', cat).where('status', '==', 'fresh').stream()))
        val = prices.get(cat, {}).get('validity', 'N/A')
        markup.add(InlineKeyboardButton(f"{cat} ({val}) ({stock})", callback_data=f"purchase_{cat}"))
    bot.send_message(message.chat.id, "📧 **মেইল ক্যাটাগরি সিলেক্ট করুন:**", parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("purchase_"))
def process_purchase(call):
    user_id = call.message.chat.id
    category = call.data.split('_')[1]
    user_ref = db.collection('users').document(str(user_id))
    bal = user_ref.get().to_dict().get('balance', 0)
    price = db.collection('settings').document('prices').get().to_dict().get(category, {}).get('price', 0)
    
    if bal < price: return bot.answer_callback_query(call.id, "❌ ব্যালেন্স কম!", show_alert=True)
        
    fresh = list(db.collection('inventory').where('category', '==', category).where('status', '==', 'fresh').limit(1).stream())
    if fresh:
        m_doc = fresh[0]
        m_data = m_doc.to_dict()
        user_ref.update({'balance': bal - price})
        m_doc.reference.update({'status': 'sold'})
        
        db.collection('active_sales').add({
            'user_id': user_id, 'email': m_data['email'], 'password': m_data['password'], 
            'category': category, 'price': price, 'buy_timestamp': time.time(), 'msg_received': False,
            'linked_gmail': m_data.get('linked_gmail'),
            'linked_gmail_pw': m_data.get('linked_gmail_pw')
        })
        bot.edit_message_text(f"🎉 **Purchase Successful!**\n📧 `{m_data['email']}`\n📌 {category}\n\n💡 মেইলটি ফরওয়ার্ডিং সেট করা। ইনবক্স চেক করলে সেন্ট্রাল জিমেইল থেকে কোড আনা হবে।", chat_id=user_id, message_id=call.message.message_id, parse_mode='Markdown')
    else:
        bot.answer_callback_query(call.id, "❌ স্টক নেই!", show_alert=True)

@bot.message_handler(func=lambda message: message.text == "📧 My Mail")
def my_mails(message):
    active = db.collection('active_sales').where('user_id', '==', message.chat.id).stream()
    found = False
    for m in active:
        found = True
        d = m.to_dict()
        markup = InlineKeyboardMarkup()
        markup.add(
            InlineKeyboardButton("📩 Check Inbox", callback_data=f"chk_{m.id}"),
            InlineKeyboardButton("🗑 Return", callback_data=f"retmail|{d['email']}")
        )
        bot.send_message(message.chat.id, f"📧 Email: `{d['email']}`", reply_markup=markup, parse_mode='Markdown')
    if not found: bot.send_message(message.chat.id, "সক্রিয় মেইল নেই।")

# ===================== ইনবক্স চেকিং (Updated for Forwarding) =====================
@bot.callback_query_handler(func=lambda call: call.data.startswith("chk_"))
def check_forwarded_inbox(call):
    sale_id = call.data.split('_')[1]
    sale_doc = db.collection('active_sales').document(sale_id).get()
    if not sale_doc.exists: return bot.answer_callback_query(call.id, "তথ্য পাওয়া যায়নি।")
    
    data = sale_doc.to_dict()
    target_email = data['email']
    
    # ফরওয়ার্ডিং জিমেইল চেক
    linked_gmail = data.get('linked_gmail')
    linked_pw = data.get('linked_gmail_pw')
    
    if not linked_gmail:
        # যদি ডিরেক্ট লগইন মেইল হয় (যেমন জিমেইল ক্যাটাগরি)
        login_email, login_pw = target_email, data['password']
        srv = 'imap.gmail.com'
    else:
        # ফরওয়ার্ডিং মেথড
        login_email, login_pw = linked_gmail, linked_pw
        srv = 'imap.gmail.com'

    msg = bot.send_message(call.message.chat.id, "🚀 ফরওয়ার্ডিং ইনবক্স চেক করা হচ্ছে...")
    
    try:
        mail = imaplib.IMAP4_SSL(srv)
        mail.login(login_email, login_pw)
        mail.select('inbox')
        
        # জিমেইলে ওই নির্দিষ্ট আউটলুকের মেইল ফিল্টার করা
        # Forwarded মেইল সাধারণত TO বা TEXT এ থাকে
        search_query = f'OR (TO "{target_email}") (TEXT "{target_email}")'
        status, search_data = mail.search(None, search_query)
        ids = search_data[0].split()

        if not ids:
            bot.edit_message_text(f"❌ `{target_email}`\nকোনো কোড বা মেসেজ আসেনি।", chat_id=call.message.chat.id, message_id=msg.message_id, parse_mode='Markdown')
            return

        status, m_data = mail.fetch(ids[-1], '(RFC822)')
        msg_obj = email.message_from_bytes(m_data[0][1])
        
        db.collection('active_sales').document(sale_id).update({'msg_received': True})
        
        subject = decode_header(msg_obj["Subject"])[0][0]
        if isinstance(subject, bytes): subject = subject.decode(errors='ignore')
        
        body = ""
        if msg_obj.is_multipart():
            for part in msg_obj.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode(errors='ignore')
                    break
        else:
            body = msg_obj.get_payload(decode=True).decode(errors='ignore')

        bot.edit_message_text(f"✅ **New Forwarded Message!**\n━━━━━━━━━━━━\n📌 Sub: `{subject}`\n\n💬 `{body[:150]}`", chat_id=call.message.chat.id, message_id=msg.message_id, parse_mode='Markdown')
        mail.logout()
    except Exception as e:
        bot.edit_message_text(f"❌ ইনবক্স অ্যাক্সেস এরর!\nজিমেইলে App Password ঠিক আছে কি না চেক করুন।", chat_id=call.message.chat.id, message_id=msg.message_id)

# [Remaining User Dashboard & Broadcast logic remains same...]

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    time.sleep(10)
    print("Bot is Running...")
    bot.infinity_polling()
