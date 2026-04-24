import os
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
from flask import Flask
import threading
import time
from datetime import datetime, timezone
import firebase_admin
from firebase_admin import credentials, firestore
import imaplib
import email
from email.header import decode_header
from email.utils import parsedate_to_datetime
import io
import re

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
    return "Waleya Premium Mail Bot is Running!"

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

def back_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("🔙 Back"))
    return markup

def is_banned(user_id):
    try:
        user_doc = db.collection('users').document(str(user_id)).get()
        if user_doc.exists and user_doc.to_dict().get('status') == 'banned': return True
    except: pass
    return False

def go_back(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    menu = admin_menu() if message.chat.id == ADMIN_ID else user_menu()
    bot.send_message(message.chat.id, "🔙 মেইন মেনুতে ফিরে এসেছেন।", reply_markup=menu)

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

@bot.message_handler(func=lambda message: message.text == "🔙 Back")
def handle_back_button(message):
    go_back(message)

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
    msg = bot.send_message(call.message.chat.id, "সেন্ট্রাল জিমেইল এবং App Password দিন।\nফরম্যাট: `email|app_password`", parse_mode='Markdown', reply_markup=back_markup())
    bot.register_next_step_handler(msg, save_fwd_gmail)

def save_fwd_gmail(message):
    if message.text == "🔙 Back": return go_back(message)
    try:
        email_addr, app_pw = message.text.split('|')
        db.collection('forwarding_gmails').add({'email': email_addr.strip(), 'password': app_pw.strip()})
        bot.send_message(message.chat.id, "✅ ফরওয়ার্ডিং জিমেইল সফলভাবে যুক্ত হয়েছে!", reply_markup=admin_menu())
    except:
        bot.send_message(message.chat.id, "❌ ফরম্যাট ভুল।", reply_markup=admin_menu())

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
    db.collection('forwarding_gmails').document(call.data.split('_')[1]).delete()
    bot.answer_callback_query(call.id, "ডিলিট করা হয়েছে।")
    view_fwd_gmails(call)

# ===================== অ্যাডমিন: MANAGE MAILS =====================
@bot.message_handler(func=lambda message: message.text == "📧 Manage Mails" and message.chat.id == ADMIN_ID)
def manage_mails(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("➕ Add Mails", callback_data="add_mails"),
        InlineKeyboardButton("📋 Mail List", callback_data="view_mails")
    )
    markup.add(
        InlineKeyboardButton("🔍 Search Mail", callback_data="search_mail"),
        InlineKeyboardButton("📄 Export All to TXT", callback_data="export_all_mails")
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
    
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(InlineKeyboardButton("No Linking (Direct Login)", callback_data=f"linknone_{category}"))
    for g in gmails:
        d = g.to_dict()
        markup.add(InlineKeyboardButton(f"Link with {d['email']}", callback_data=f"link_{g.id}_{category}"))
            
    bot.edit_message_text(f"**{category}** এর জন্য ফরওয়ার্ডিং জিমেইল সিলেক্ট করুন:", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup, parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data.startswith("link_") or call.data.startswith("linknone_"))
def enter_mails_to_add(call):
    if call.data.startswith("linknone_"):
        category = call.data.split('_')[1]
        gmail_info = None
        instruction = f"**{category}** এর মেইলগুলো নিচে দিন।\nফরম্যাট: `email|password`"
    else:
        _, g_id, category = call.data.split('_')
        gmail_info = db.collection('forwarding_gmails').document(g_id).get().to_dict()
        instruction = f"**{category}** এর মেইলগুলো নিচে দিন।\nযেহেতু ফরোয়ার্ডিং সিলেক্ট করেছেন, শুধু মেইল দিলেই হবে!\nফরম্যাট: `email` (যেমন: abc@outlook.com)"
        
    msg = bot.send_message(call.message.chat.id, instruction, parse_mode='Markdown', reply_markup=back_markup())
    bot.register_next_step_handler(msg, process_add_mails, category, gmail_info)

def process_add_mails(message, category, gmail_info):
    if message.text == "🔙 Back": return go_back(message)
    lines = message.text.split('\n')
    added = 0
    for line in lines:
        if line.strip() == "": continue
        if '|' in line:
            email_addr, password = line.split('|', 1)
        else:
            email_addr = line.strip()
            password = "AutoForwarded" 
            
        data = {'email': email_addr.strip(), 'password': password.strip(), 'category': category, 'status': 'fresh'}
        if gmail_info:
            data['linked_gmail'] = gmail_info['email']
            data['linked_gmail_pw'] = gmail_info['password']
            
        db.collection('inventory').add(data)
        added += 1
    bot.send_message(message.chat.id, f"✅ **{category}**-এ {added} টি মেইল যুক্ত হয়েছে!", reply_markup=admin_menu(), parse_mode='Markdown')

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

@bot.callback_query_handler(func=lambda call: call.data == "export_all_mails")
def export_all_mails_txt(call):
    mails = list(db.collection('inventory').stream())
    text_data = "Email | Password | Category | Status\n" + "-"*50 + "\n"
    for m in mails:
        d = m.to_dict()
        text_data += f"{d.get('email')} | {d.get('password')} | {d.get('category')} | {d.get('status')}\n"
    
    file_data = io.BytesIO(text_data.encode('utf-8'))
    file_data.name = "Mail_Inventory.txt"
    bot.send_document(call.message.chat.id, file_data, caption="📂 All Mails Exported")

@bot.callback_query_handler(func=lambda call: call.data.startswith("delmail_"))
def delete_mail(call):
    db.collection('inventory').document(call.data.split('_')[1]).delete()
    bot.answer_callback_query(call.id, "✅ মেইল ডিলিট হয়েছে।", show_alert=True)
    
@bot.callback_query_handler(func=lambda call: call.data == "search_mail")
def ask_search_mail(call):
    msg = bot.send_message(call.message.chat.id, "🔎 যে মেইলটি খুঁজতে চান সেটি লিখে পাঠান:", reply_markup=back_markup())
    bot.register_next_step_handler(msg, process_search_mail)

def process_search_mail(message):
    if message.text == "🔙 Back": return go_back(message)
    target_email = message.text.strip()
    results = list(db.collection('inventory').where('email', '==', target_email).stream())
    if results:
        m = results[0]
        d = m.to_dict()
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🗑 Delete Mail", callback_data=f"delmail_{m.id}"))
        bot.send_message(message.chat.id, f"✅ **Mail Found!**\n📧 Email: `{d['email']}`\n📌 Category: {d['category']}\n🟢 Status: {d['status']}", parse_mode='Markdown', reply_markup=admin_menu())
        bot.send_message(message.chat.id, "অ্যাকশন:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "❌ এই মেইলটি স্টকে পাওয়া যায়নি।", reply_markup=admin_menu())

# ===================== অ্যাডমিন: SETTINGS & DASHBOARD =====================
@bot.message_handler(func=lambda message: message.text == "⚙️ Settings" and message.chat.id == ADMIN_ID)
def admin_settings(message):
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton("💳 Payment Setup", callback_data="setup_payments"),
        InlineKeyboardButton("🏷 Price & Time Setup", callback_data="setup_prices"),
        InlineKeyboardButton("⚙️ Forwarding Setup", callback_data="setup_forwarding")
    )
    bot.send_message(message.chat.id, "⚙️ **Settings Menu**\nনিচের অপশনগুলো থেকে সিলেক্ট করুন:", parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "setup_payments")
def payment_setup(call):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Bkash", callback_data="set_bkash"),
        InlineKeyboardButton("Nagad", callback_data="set_nagad"),
        InlineKeyboardButton("Binance", callback_data="set_binance")
    )
    settings = db.collection('settings').document('payment_methods').get().to_dict()
    text = f"⚙️ **Payment Gateways**\n━━━━━━━━━━━━\n🟣 bKash: `{settings.get('bkash')}`\n🟠 Nagad: `{settings.get('nagad')}`\n🟡 Binance: `{settings.get('binance')}`"
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_"))
def update_payment_method(call):
    method = call.data.split('_')[1]
    msg = bot.send_message(call.message.chat.id, f"নতুন {method.capitalize()} নম্বর/ID দিন:", reply_markup=back_markup())
    bot.register_next_step_handler(msg, save_payment_method, method)

def save_payment_method(message, method):
    if message.text == "🔙 Back": return go_back(message)
    db.collection('settings').document('payment_methods').update({method: message.text.strip()})
    bot.send_message(message.chat.id, f"✅ {method.capitalize()} আপডেট করা হয়েছে!", reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda call: call.data == "setup_prices")
def price_setup_categories(call):
    markup = InlineKeyboardMarkup(row_width=2)
    for cat in CATEGORIES:
        markup.add(InlineKeyboardButton(cat, callback_data=f"setprice_{cat}"))
    bot.edit_message_text("কোন ক্যাটাগরির প্রাইস আপডেট করবেন?", chat_id=call.message.chat.id, message_id=call.message.message_id, reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("setprice_"))
def ask_price(call):
    category = call.data.split('_')[1]
    msg = bot.send_message(call.message.chat.id, f"**{category}** এর জন্য নতুন প্রাইস এবং ভ্যালিডিটি দিন।\nফরম্যাট: `Price|Validity`\n(যেমন: `6|6-10 Hours`)", parse_mode='Markdown', reply_markup=back_markup())
    bot.register_next_step_handler(msg, save_price_validity, category)

def save_price_validity(message, category):
    if message.text == "🔙 Back": return go_back(message)
    try:
        price, validity = message.text.split('|')
        db.collection('settings').document('prices').update({
            category: {'price': int(price.strip()), 'validity': validity.strip()}
        })
        bot.send_message(message.chat.id, f"✅ **{category}** আপডেট হয়েছে!\nPrice: {price}৳\nValidity: {validity}", parse_mode='Markdown', reply_markup=admin_menu())
    except:
        bot.send_message(message.chat.id, "❌ ফরম্যাট ভুল।", reply_markup=admin_menu())

@bot.message_handler(func=lambda message: message.text == "📊 Dashboard" and message.chat.id == ADMIN_ID)
def admin_dashboard(message):
    users = len(list(db.collection('users').stream()))
    fresh = len(list(db.collection('inventory').where('status', '==', 'fresh').stream()))
    sold = len(list(db.collection('inventory').where('status', '==', 'sold').stream()))
    bot.send_message(message.chat.id, f"📊 **Admin Dashboard**\n━━━━━━━━━━━━━\n👥 মোট ইউজার: {users}\n✅ ফ্রেশ মেইল: {fresh}\n🛒 সোল্ড মেইল: {sold}", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "📢 Send Notice" and message.chat.id == ADMIN_ID)
def send_notice_start(message):
    msg = bot.send_message(message.chat.id, "সব ইউজারের কাছে যে নোটিশ পাঠাতে চান, তা লিখে পাঠান:", reply_markup=back_markup())
    bot.register_next_step_handler(msg, broadcast_notice)

def broadcast_notice(message):
    if message.text == "🔙 Back": return go_back(message)
    notice_text = f"📢 **Admin Notice:**\n\n{message.text}"
    try:
        users = db.collection('users').stream()
        count = 0
        for user in users:
            try:
                bot.send_message(user.id, notice_text, parse_mode='Markdown')
                count += 1
            except: pass
        bot.send_message(message.chat.id, f"✅ নোটিশ সফলভাবে {count} জন ইউজারকে পাঠানো হয়েছে।", reply_markup=admin_menu())
    except:
        bot.send_message(message.chat.id, "নোটিশ পাঠাতে এরর হয়েছে।", reply_markup=admin_menu())

# ===================== অ্যাডমিন: USER MANAGEMENT =====================
@bot.message_handler(func=lambda message: message.text == "👥 User Management" and message.chat.id == ADMIN_ID)
def user_management_menu(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("📋 User List", callback_data="userpage_0"),
        InlineKeyboardButton("🔍 Search User", callback_data="search_user")
    )
    bot.send_message(message.chat.id, "ইউজার ম্যানেজমেন্ট অপশন সিলেক্ট করুন:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("userpage_"))
def show_user_list(call):
    page = int(call.data.split('_')[1])
    users = list(db.collection('users').stream())
    total_users = len(users)
    start = page * 10
    end = start + 10
    chunk = users[start:end]
    
    text = f"👥 **Total Users: {total_users}**\n━━━━━━━━━━━━━━\n"
    for u in chunk:
        d = u.to_dict()
        text += f"👤 {d.get('name', 'User')} | `{u.id}` | {d.get('balance', 0)}৳\n"
        
    markup = InlineKeyboardMarkup()
    nav = []
    if start > 0: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"userpage_{page-1}"))
    if end < total_users: nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"userpage_{page+1}"))
    if nav: markup.add(*nav)
    markup.add(InlineKeyboardButton("📄 Export to TXT", callback_data="export_users"))
    
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "export_users")
def export_users_txt(call):
    users = list(db.collection('users').stream())
    text_data = "Name | User ID | Balance | Status\n" + "-"*40 + "\n"
    for u in users:
        d = u.to_dict()
        text_data += f"{d.get('name', 'Unknown')} | {u.id} | {d.get('balance', 0)} | {d.get('status', 'active')}\n"
    
    file_data = io.BytesIO(text_data.encode('utf-8'))
    file_data.name = "User_List.txt"
    bot.send_document(call.message.chat.id, file_data, caption="📂 All Users Exported")

@bot.callback_query_handler(func=lambda call: call.data == "search_user")
def ask_user_search(call):
    msg = bot.send_message(call.message.chat.id, "🔎 User ID লিখে পাঠান:", reply_markup=back_markup())
    bot.register_next_step_handler(msg, search_user_details)

def search_user_details(message):
    if message.text == "🔙 Back": return go_back(message)
    target_id = message.text.strip()
    user_ref = db.collection('users').document(target_id).get()
    
    if user_ref.exists:
        data = user_ref.to_dict()
        status_icon = "✅ Active" if data.get('status') != 'banned' else "🚫 Banned"
        text = f"👤 **User Details**\n━━━━━━━━━━━━\n🆔 ID: `{target_id}`\n👤 Name: {data.get('name', 'User')}\n💰 Balance: {data.get('balance', 0)} ৳\n📌 Status: {status_icon}\n"
        markup = InlineKeyboardMarkup(row_width=2)
        markup.add(
            InlineKeyboardButton("✏️ Edit Balance", callback_data=f"editbal_{target_id}"),
            InlineKeyboardButton("🚫 Ban", callback_data=f"ban_{target_id}") if data.get('status') != 'banned' else InlineKeyboardButton("✅ Unban", callback_data=f"unban_{target_id}")
        )
        bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=admin_menu())
        bot.send_message(message.chat.id, "অ্যাকশন সিলেক্ট করুন:", reply_markup=markup)
    else:
        bot.send_message(message.chat.id, "❌ এই ID ডাটাবেসে নেই।", reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda call: call.data.startswith("ban_") or call.data.startswith("unban_"))
def toggle_ban(call):
    action, target_id = call.data.split('_')
    new_status = 'banned' if action == 'ban' else 'active'
    db.collection('users').document(target_id).update({'status': new_status})
    bot.edit_message_text(f"✅ ইউজারকে {action} করা হয়েছে!", chat_id=call.message.chat.id, message_id=call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("editbal_"))
def ask_new_balance(call):
    target_id = call.data.split('_')[1]
    msg = bot.send_message(call.message.chat.id, f"`{target_id}` এর জন্য নতুন ব্যালেন্স অ্যামাউন্ট লিখুন:", parse_mode='Markdown', reply_markup=back_markup())
    bot.register_next_step_handler(msg, save_new_balance, target_id)

def save_new_balance(message, target_id):
    if message.text == "🔙 Back": return go_back(message)
    try:
        new_bal = int(message.text)
        db.collection('users').document(target_id).update({'balance': new_bal})
        bot.send_message(message.chat.id, f"✅ ব্যালেন্স আপডেট করে {new_bal} ৳ করা হয়েছে!", reply_markup=admin_menu())
    except:
        bot.send_message(message.chat.id, "❌ শুধু সংখ্যা দিন।", reply_markup=admin_menu())

# ===================== ইউজার: BEAUTIFUL PROFILE, INFO & BALANCE =====================
@bot.message_handler(func=lambda message: message.text == "👤 Profile")
def user_profile(message):
    user_id = message.chat.id
    if is_banned(user_id): return
    data = db.collection('users').document(str(user_id)).get().to_dict()
    bought = len(list(db.collection('active_sales').where('user_id', '==', user_id).stream()))
    
    text = f"""
💠 **USER PROFILE** 💠
━━━━━━━━━━━━━━━━━━
👤 **Name:** {data.get('name', 'User')}
🆔 **User ID:** `{user_id}`
💰 **Balance:** {data.get('balance', 0)} TK
🛒 **Total Purchase:** {bought} Mails
🕰 **Status:** Active User
━━━━━━━━━━━━━━━━━━
    """
    bot.send_message(user_id, text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "ℹ️ Bot Info")
def bot_info(message):
    text = f"""
🌟 **TRUSTED MAIL SHOP** 🌟
━━━━━━━━━━━━━━━━━━
🛡 **Features:**
✓ Auto Instant Delivery
✓ 20 Mins Auto Refund System
✓ Premium Fresh Mails
✓ Instant Deposit System

👨‍💻 **Developer:** [Waleya](tg://user?id={ADMIN_ID})
📞 **Support:** [Admin Contact](tg://user?id={ADMIN_ID})
━━━━━━━━━━━━━━━━━━
    """
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "💳 Balance")
def balance_menu(message):
    if is_banned(message.chat.id): return
    bal = db.collection('users').document(str(message.chat.id)).get().to_dict().get('balance', 0)
    prices = db.collection('settings').document('prices').get().to_dict()
    
    stocks = {}
    for cat in CATEGORIES:
        stocks[cat] = len(list(db.collection('inventory').where('category', '==', cat).where('status', '==', 'fresh').stream()))
    
    text = f"""
💳 **Your Balance**
╔═════════════════╗
  💰 **{float(bal):.2f} TK**
╚═════════════════╝

📋 **Email Price List**
╔═════════════════╗
"""
    for cat in CATEGORIES:
        p = prices.get(cat, {}).get('price', 0)
        text += f" 📧 {cat} ➔ {p}.00 TK\n"
        
    text += f"""╚═════════════════╝

📦 **Current Stock**
╔═════════════════╗
"""
    for cat in CATEGORIES:
        text += f" 📦 {cat} ➔ {stocks[cat]}\n"
    text += "╚═════════════════╝"

    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Add Fund", callback_data="add_fund_start"))
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

# ===================== ইউজার: ADD FUND & PAYMENT =====================
@bot.callback_query_handler(func=lambda call: call.data == "add_fund_start")
def ask_fund_amount(call):
    msg = bot.send_message(call.message.chat.id, "আপনি কত টাকা অ্যাড করতে চান? (যেমন: 100)", reply_markup=back_markup())
    bot.register_next_step_handler(msg, ask_payment_gateway)

def ask_payment_gateway(message):
    if message.text == "🔙 Back": return go_back(message)
    try:
        amount = int(message.text)
        user_states[message.chat.id] = {'amount': amount}
        
        markup = InlineKeyboardMarkup(row_width=1)
        markup.add(
            InlineKeyboardButton("🟣 bKash", callback_data="pay_bkash"),
            InlineKeyboardButton("🟠 Nagad", callback_data="pay_nagad"),
            InlineKeyboardButton("🟡 Binance", callback_data="pay_binance")
        )
        bot.send_message(message.chat.id, f"আপনি {amount} ৳ অ্যাড করতে চাচ্ছেন।\nদয়া করে পেমেন্ট মেথড সিলেক্ট করুন:", reply_markup=markup)
        bot.send_message(message.chat.id, "অন্যথায় ফিরে যেতে 'Back' এ ক্লিক করুন।", reply_markup=back_markup())
    except:
        bot.send_message(message.chat.id, "❌ সঠিক টাকার পরিমাণ দিন।", reply_markup=user_menu())

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def show_payment_details(call):
    method = call.data.split('_')[1]
    amount = user_states.get(call.message.chat.id, {}).get('amount', 0)
    
    settings = db.collection('settings').document('payment_methods').get().to_dict()
    account_info = settings.get(method, "Not Setup Yet")
    
    user_states[call.message.chat.id]['method'] = method
    
    text = f"💳 **Payment details for {method.capitalize()}**\n━━━━━━━━━━━━━━\nপরিমাণ: {amount} ৳\nনম্বর/ID: `{account_info}` (কপি করতে ট্যাপ করুন)\n\nটাকা পাঠানোর পর আপনার Transaction ID বা Payment Number নিচে লিখে দিন:"
    msg = bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=back_markup())
    bot.register_next_step_handler(msg, process_trx_id)

def process_trx_id(message):
    if message.text == "🔙 Back": return go_back(message)
        
    user_id = message.chat.id
    trx_id = message.text.strip()
    data = user_states.get(user_id, {})
    
    if not data: return bot.send_message(user_id, "সেশন এক্সপায়ার হয়েছে। আবার চেষ্টা করুন।", reply_markup=user_menu())
    
    request_id = f"req_{int(time.time())}"
    db.collection('payment_requests').document(request_id).set({
        'user_id': user_id, 'amount': data['amount'], 'method': data['method'], 'trx_id': trx_id, 'status': 'pending'
    })
    
    admin_text = f"🔔 **New Deposit Request**\n━━━━━━━━━━━━━━\n👤 User ID: `{user_id}`\n💰 Amount: {data['amount']} ৳\n🏦 Method: {data['method'].capitalize()}\n🏷 TrxID/Info: `{trx_id}`"
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("✅ Approve", callback_data=f"approve_{request_id}"),
        InlineKeyboardButton("❌ Decline", callback_data=f"decline_{request_id}")
    )
    bot.send_message(ADMIN_ID, admin_text, parse_mode='Markdown', reply_markup=markup)
    
    bot.send_message(user_id, "✅ আপনার পেমেন্ট রিকোয়েস্ট অ্যাডমিনের কাছে পাঠানো হয়েছে। অ্যাপ্রুভ হওয়া পর্যন্ত অপেক্ষা করুন।", reply_markup=user_menu())
    user_states.pop(user_id, None)

@bot.callback_query_handler(func=lambda call: call.data.startswith("approve_") or call.data.startswith("decline_"))
def handle_payment_request(call):
    action, req_id = call.data.split('_', 1)
    req_doc = db.collection('payment_requests').document(req_id)
    req_data = req_doc.get().to_dict()
    
    if req_data['status'] != 'pending':
        return bot.answer_callback_query(call.id, "এই রিকোয়েস্টটি আগেই প্রসেস করা হয়েছে।")
    
    user_id = req_data['user_id']
    amount = req_data['amount']
    
    if action == "approve":
        user_ref = db.collection('users').document(str(user_id))
        cur_bal = user_ref.get().to_dict().get('balance', 0)
        user_ref.update({'balance': cur_bal + amount})
        req_doc.update({'status': 'approved'})
        
        bot.edit_message_text(f"✅ Approved: {amount} ৳ added to `{user_id}`", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
        try: bot.send_message(user_id, f"🎉 **Payment Approved!**\nআপনার অ্যাকাউন্টে {amount} ৳ অ্যাড হয়েছে।")
        except: pass
    else:
        req_doc.update({'status': 'declined'})
        bot.edit_message_text(f"❌ Declined Request of `{user_id}`", chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown')
        try: bot.send_message(user_id, f"❌ **Payment Declined!**\nআপনার {amount} ৳ এর পেমেন্ট রিকোয়েস্টটি বাতিল করা হয়েছে।")
        except: pass

# ===================== ইউজার: BUY MAIL MENU =====================
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
        bot.edit_message_text(f"🎉 **Purchase Successful!**\n📧 `{m_data['email']}`\n📌 {category}\n\n💡 'My Mail'-এ গিয়ে ইনবক্স চেক করুন। ২০ মিনিটে কোড না আসলে অটো রিফান্ড হবে।", chat_id=user_id, message_id=call.message.message_id, parse_mode='Markdown')
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
    if not found: bot.send_message(message.chat.id, "আপনার কোনো সক্রিয় মেইল নেই।")

@bot.callback_query_handler(func=lambda call: call.data.startswith("retmail|"))
def return_user_mail(call):
    email_addr = call.data.split('|')[1]
    user_id = call.message.chat.id
    sales = list(db.collection('active_sales').where('user_id', '==', user_id).where('email', '==', email_addr).stream())
    if sales:
        sale_doc = sales[0]
        data = sale_doc.to_dict()
        price = data.get('price', 0)
        db.collection('inventory').add({
            'email': data['email'], 'password': data['password'], 
            'category': data.get('category', 'Unknown'), 'status': 'fresh',
            'linked_gmail': data.get('linked_gmail'), 'linked_gmail_pw': data.get('linked_gmail_pw')
        })
        user_ref = db.collection('users').document(str(user_id))
        cur_bal = user_ref.get().to_dict().get('balance', 0)
        
        if data.get('msg_received', False):
            msg_text = f"✅ মেইলটি ডিলিট করে স্টকে পাঠানো হয়েছে।\n⚠️ (আপনি কোড রিসিভ করেছিলেন, তাই রিফান্ড করা হয়নি)।"
        else:
            user_ref.update({'balance': cur_bal + price})
            msg_text = f"✅ মেইলটি ডিলিট করে স্টকে পাঠানো হয়েছে।\n💰 আপনার ব্যালেন্সে {price} ৳ রিফান্ড করা হয়েছে।"
            
        sale_doc.reference.delete()
        bot.edit_message_text(msg_text, chat_id=user_id, message_id=call.message.message_id, parse_mode='Markdown')
    else:
        bot.answer_callback_query(call.id, "মেইলটি পাওয়া যায়নি।", show_alert=True)

# ===================== ইনবক্স চেকিং (Smart Search + OTP Extract) =====================
@bot.callback_query_handler(func=lambda call: call.data.startswith("chk_"))
def check_smart_inbox(call):
    sale_id = call.data.split('_')[1]
    sale_doc = db.collection('active_sales').document(sale_id).get()
    if not sale_doc.exists: return bot.answer_callback_query(call.id, "তথ্য পাওয়া যায়নি।")
    
    data = sale_doc.to_dict()
    target_email = data['email']
    linked_gmail = data.get('linked_gmail')
    linked_pw = data.get('linked_gmail_pw')
    
    login_email = linked_gmail if linked_gmail else target_email
    login_pw = linked_pw if linked_gmail else data['password']
    
    msg = bot.send_message(call.message.chat.id, "⏳ সার্ভারের সাথে কানেক্ট করা হচ্ছে...")
    
    # সুন্দর ক্লিন অ্যানিমেশন (No mention of Spam/Forwarding)
    anim_steps = ["📡 সার্ভারের সাথে কানেক্ট করা হচ্ছে...", "🔎 নতুন মেসেজ খোঁজা হচ্ছে...", "📥 ইনবক্স সিঙ্ক করা হচ্ছে..."]
    for step in anim_steps:
        bot.edit_message_text(step, chat_id=call.message.chat.id, message_id=msg.message_id)
        time.sleep(1.2)
        
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(login_email, login_pw)
        
        folders_to_check = ['"INBOX"', '"[Gmail]/Spam"']
        best_msg = None
        best_time = None
        
        for folder in folders_to_check:
            try:
                mail.select(folder)
                
                # Fetching the latest 15 emails to search manually (Bypasses IMAP Search bugs for forwarded headers)
                status, search_data = mail.search(None, 'ALL')
                ids = search_data[0].split()
                recent_ids = ids[-15:] 
                
                for num in reversed(recent_ids):
                    typ, m_data = mail.fetch(num, '(RFC822)')
                    raw_email = m_data[0][1].decode(errors='ignore')
                    
                    # Checking if the target email is mentioned anywhere in the email data
                    if target_email.lower() in raw_email.lower():
                        msg_obj = email.message_from_bytes(m_data[0][1])
                        date_str = msg_obj.get('Date')
                        
                        if date_str:
                            msg_date = parsedate_to_datetime(date_str)
                            now_utc = datetime.now(timezone.utc)
                            diff_seconds = (now_utc - msg_date).total_seconds()
                            
                            # Valid only if received within last 20 mins
                            if diff_seconds <= 1200:
                                if not best_time or msg_date > best_time:
                                    best_time = msg_date
                                    best_msg = msg_obj
            except:
                continue
                
        if not best_msg:
            bot.edit_message_text(f"❌ `{target_email}`\nনতুন কোনো কোড আসেনি। (বিঃদ্রঃ শুধু গত ২০ মিনিটের মেসেজ দেখানো হয়)", chat_id=call.message.chat.id, message_id=msg.message_id, parse_mode='Markdown')
            mail.logout()
            return

        db.collection('active_sales').document(sale_id).update({'msg_received': True})
        
        subject = decode_header(best_msg["Subject"])[0][0]
        if isinstance(subject, bytes): subject = subject.decode(errors='ignore')
        
        body = ""
        if best_msg.is_multipart():
            for part in best_msg.walk():
                if part.get_content_type() == "text/plain":
                    body = part.get_payload(decode=True).decode(errors='ignore')
                    break
        else:
            body = best_msg.get_payload(decode=True).decode(errors='ignore')

        # ভেরিফিকেশন কোড বের করা (6 থেকে 8 সংখ্যার কোড)
        code_match = re.search(r'\b\d{6,8}\b', body)
        extract_code = f"`{code_match.group(0)}` (Tap to Copy)" if code_match else "কোড মেসেজের ভেতর আছে, নিচে পড়ুন।"

        final_text = f"""
✅ **New Message Found!**
━━━━━━━━━━━━━━
📧 **To:** `{target_email}`
📌 **Subject:** `{subject}`

🔑 **Verification Code:**
{extract_code}

💬 **Message Text:** `{body[:200]}...`
━━━━━━━━━━━━━━
"""
        bot.edit_message_text(final_text, chat_id=call.message.chat.id, message_id=msg.message_id, parse_mode='Markdown')
        mail.logout()
    except Exception as e:
        bot.edit_message_text(f"❌ ইনবক্স অ্যাক্সেস এরর! সার্ভার কানেকশন ফেইল।", chat_id=call.message.chat.id, message_id=msg.message_id)

if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    time.sleep(5)
    print("Bot is Running Smoothly with Smart Search...")
    bot.infinity_polling()
