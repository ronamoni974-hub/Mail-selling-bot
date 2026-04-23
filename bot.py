import os
import telebot
from telebot.types import ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardRemove
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
CATEGORIES = ['Gmail', 'Hotmail', 'Outlook', 'Temp Mail']

# ================= ফায়ারবেস সেটআপ =================
try:
    cred = credentials.Certificate("firebase-key.json")
    firebase_admin.initialize_app(cred)
    db = firestore.client()
    
    # ডিফল্ট সেটিংস ও প্রাইস তৈরি করা (যদি না থাকে)
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
        time.sleep(60) # প্রতি ১ মিনিট পরপর চেক করবে
        try:
            now = time.time()
            sales = db.collection('active_sales').where('msg_received', '==', False).stream()
            for sale in sales:
                data = sale.to_dict()
                buy_time = data.get('buy_timestamp', 0)
                
                # যদি ২০ মিনিট (১২০০ সেকেন্ড) পার হয়ে যায়
                if now - buy_time >= 1200:
                    # ইউজারকে রিফান্ড দেওয়া
                    user_ref = db.collection('users').document(str(data['user_id']))
                    cur_bal = user_ref.get().to_dict().get('balance', 0)
                    user_ref.update({'balance': cur_bal + data['price']})
                    
                    # মেইল স্টকে ফেরত পাঠানো
                    db.collection('inventory').add({
                        'email': data['email'], 'password': data['password'], 
                        'category': data['category'], 'status': 'fresh'
                    })
                    
                    # নোটিফিকেশন পাঠানো
                    try:
                        bot.send_message(data['user_id'], f"⚠️ **অটো রিফান্ড!**\n২০ মিনিটে কোনো মেসেজ না আসায় `{data['email']}` বাতিল করা হয়েছে এবং আপনার {data['price']} ৳ রিফান্ড করা হয়েছে।", parse_mode='Markdown')
                    except: pass
                    
                    # সেল ডিলিট করা
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

def cancel_markup():
    markup = ReplyKeyboardMarkup(resize_keyboard=True)
    markup.add(KeyboardButton("❌ Cancel"))
    return markup

# ================= হেল্পার =================
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
        bot.send_message(user_id, f"স্বাগতম অ্যাডমিন {name}!", reply_markup=admin_menu())
    else:
        bot.send_message(user_id, f"আমাদের শপে স্বাগতম, {name}!", reply_markup=user_menu())

@bot.message_handler(func=lambda message: message.text == "❌ Cancel")
def cancel_action(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    menu = admin_menu() if message.chat.id == ADMIN_ID else user_menu()
    bot.send_message(message.chat.id, "❌ একশন বাতিল করা হয়েছে।", reply_markup=menu)

# ===================== অ্যাডমিন: MANAGE MAILS =====================
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
def enter_mails_to_add(call):
    category = call.data.split('_')[1]
    msg = bot.send_message(call.message.chat.id, f"**{category}** এর মেইলগুলো নিচে দিন।\nফরম্যাট: `email|password`", parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, process_add_mails, category)

def process_add_mails(message, category):
    if message.text == "❌ Cancel": return cancel_action(message)
    lines = message.text.split('\n')
    added = 0
    for line in lines:
        if '|' in line:
            email_addr, password = line.split('|')
            db.collection('inventory').add({'email': email_addr.strip(), 'password': password.strip(), 'category': category, 'status': 'fresh'})
            added += 1
    bot.send_message(message.chat.id, f"✅ **{category}**-এ {added} টি মেইল যুক্ত হয়েছে!", reply_markup=admin_menu(), parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == "view_mails")
def view_mails(call):
    mails = list(db.collection('inventory').limit(10).stream())
    if not mails:
        return bot.send_message(call.message.chat.id, "স্টকে কোনো মেইল নেই।")
    
    text = "📋 **সর্বশেষ ১০টি মেইলের লিস্ট:**\n\n"
    markup = InlineKeyboardMarkup()
    for m in mails:
        data = m.to_dict()
        tag = "✅ Fresh" if data['status'] == 'fresh' else "🛒 Sold"
        text += f"📧 `{data['email']}` - {tag}\n"
        markup.add(InlineKeyboardButton(f"🗑 Delete {data['email']}", callback_data=f"delmail_{m.id}"))
        
    bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("delmail_"))
def delete_mail(call):
    doc_id = call.data.split('_')[1]
    db.collection('inventory').document(doc_id).delete()
    bot.edit_message_text("✅ মেইলটি ডাটাবেস থেকে ডিলিট করা হয়েছে।", chat_id=call.message.chat.id, message_id=call.message.message_id)

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
    markup.add(InlineKeyboardButton("📄 Export to TXT File", callback_data="export_users"))
    
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
    msg = bot.send_message(call.message.chat.id, "🔎 User ID লিখে পাঠান:", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, search_user_details)

def search_user_details(message):
    if message.text == "❌ Cancel": return cancel_action(message)
    target_id = message.text.strip()
    user_ref = db.collection('users').document(target_id).get()
    
    if user_ref.exists:
        data = user_ref.to_dict()
        bought_mails = list(db.collection('active_sales').where('user_id', '==', int(target_id)).stream())
        bought_count = len(bought_mails)
        
        status_icon = "✅ Active" if data.get('status') != 'banned' else "🚫 Banned"
        text = f"👤 **User Details**\n━━━━━━━━━━━━\n🆔 ID: `{target_id}`\n👤 Name: {data.get('name', 'User')}\n💰 Balance: {data.get('balance', 0)} ৳\n🛒 Total Bought: {bought_count}\n📌 Status: {status_icon}\n\n**Purchased Mails:**\n"
        for m in bought_mails[:5]:
            text += f"📧 `{m.to_dict().get('email')}`\n"
            
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
    msg = bot.send_message(call.message.chat.id, f"`{target_id}` এর জন্য নতুন ব্যালেন্স অ্যামাউন্ট লিখুন (যেমন: 500):", parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, save_new_balance, target_id)

def save_new_balance(message, target_id):
    if message.text == "❌ Cancel": return cancel_action(message)
    try:
        new_bal = int(message.text)
        db.collection('users').document(target_id).update({'balance': new_bal})
        bot.send_message(message.chat.id, f"✅ ব্যালেন্স আপডেট করে {new_bal} ৳ করা হয়েছে!", reply_markup=admin_menu())
        bot.send_message(target_id, f"🎉 অ্যাডমিন আপনার ব্যালেন্স আপডেট করে {new_bal} ৳ করেছেন!")
    except:
        bot.send_message(message.chat.id, "❌ শুধু সংখ্যা দিন।", reply_markup=admin_menu())

# ===================== অ্যাডমিন: SETTINGS & DASHBOARD =====================
@bot.message_handler(func=lambda message: message.text == "⚙️ Settings" and message.chat.id == ADMIN_ID)
def admin_settings(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("💳 Payment Setup", callback_data="setup_payments"),
        InlineKeyboardButton("🏷 Price & Time Setup", callback_data="setup_prices")
    )
    bot.send_message(message.chat.id, "⚙️ **Settings Menu**", parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "setup_payments")
def payment_setup(call):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("Bkash Setup", callback_data="set_bkash"),
        InlineKeyboardButton("Nagad Setup", callback_data="set_nagad"),
        InlineKeyboardButton("Binance Setup", callback_data="set_binance")
    )
    settings = db.collection('settings').document('payment_methods').get().to_dict()
    text = f"⚙️ **Payment Gateways**\n━━━━━━━━━━━━\n🟣 bKash: `{settings.get('bkash')}`\n🟠 Nagad: `{settings.get('nagad')}`\n🟡 Binance: `{settings.get('binance')}`"
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("set_"))
def update_payment_method(call):
    method = call.data.split('_')[1]
    msg = bot.send_message(call.message.chat.id, f"নতুন {method.capitalize()} নম্বর/ID দিন:", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, save_payment_method, method)

def save_payment_method(message, method):
    if message.text == "❌ Cancel": return cancel_action(message)
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
    msg = bot.send_message(call.message.chat.id, f"**{category}** এর জন্য নতুন প্রাইস এবং ভ্যালিডিটি দিন।\nফরম্যাট: `Price|Validity`\n(যেমন: `6|6-10 Hours`)", parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, save_price_validity, category)

def save_price_validity(message, category):
    if message.text == "❌ Cancel": return cancel_action(message)
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
    bot.send_message(message.chat.id, f"📊 **Dashboard**\n━━━━━━━━━━━━━\n👥 মোট ইউজার: {users}\n✅ ফ্রেশ মেইল: {fresh}\n🛒 সোল্ড মেইল: {sold}", parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "📢 Send Notice" and message.chat.id == ADMIN_ID)
def send_notice_start(message):
    msg = bot.send_message(message.chat.id, "সব ইউজারের কাছে যে নোটিশ পাঠাতে চান, তা লিখে পাঠান:", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, broadcast_notice)

def broadcast_notice(message):
    if message.text == "❌ Cancel": return cancel_action(message)
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

# ===================== ইউজার: BEAUTIFUL PROFILE & INFO =====================
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

# ===================== ইউজার: BEAUTIFUL BALANCE =====================
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
    msg = bot.send_message(call.message.chat.id, "আপনি কত টাকা অ্যাড করতে চান? (যেমন: 100)", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, ask_payment_gateway)

def ask_payment_gateway(message):
    if message.text == "❌ Cancel": return cancel_action(message)
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
        bot.send_message(message.chat.id, "পেমেন্ট ফ্লো ক্যানসেল করতে চাইলে /start দিন।", reply_markup=user_menu())
    except:
        bot.send_message(message.chat.id, "❌ সঠিক টাকার পরিমাণ দিন।", reply_markup=user_menu())

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def show_payment_details(call):
    method = call.data.split('_')[1]
    amount = user_states.get(call.message.chat.id, {}).get('amount', 0)
    
    settings = db.collection('settings').document('payment_methods').get().to_dict()
    account_info = settings.get(method, "Not Setup Yet")
    
    user_states[call.message.chat.id]['method'] = method
    
    text = f"💳 **Payment details for {method.capitalize()}**\n━━━━━━━━━━━━━━\nপরিমাণ: {amount} ৳\nনম্বর/ID: `{account_info}` (কপি করতে ট্যাপ করুন)\n\nটাকা পাঠানোর পর আপনার Transaction ID নিচে লিখে দিন:"
    msg = bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, process_trx_id)

def process_trx_id(message):
    if message.text == "❌ Cancel": return cancel_action(message)
        
    user_id = message.chat.id
    trx_id = message.text.strip()
    data = user_states.get(user_id, {})
    
    if not data: return bot.send_message(user_id, "সেশন এক্সপায়ার হয়েছে। আবার চেষ্টা করুন।", reply_markup=user_menu())
    
    request_id = f"req_{int(time.time())}"
    db.collection('payment_requests').document(request_id).set({
        'user_id': user_id, 'amount': data['amount'], 'method': data['method'], 'trx_id': trx_id, 'status': 'pending'
    })
    
    admin_text = f"🔔 **New Deposit Request**\n━━━━━━━━━━━━━━\n👤 User ID: `{user_id}`\n💰 Amount: {data['amount']} ৳\n🏦 Method: {data['method'].capitalize()}\n🏷 TrxID: `{trx_id}`"
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
        try: bot.send_message(user_id, f"❌ **Payment Declined!**\nআপনার {amount} ৳ এর পেমেন্ট রিকোয়েস্টটি বাতিল করা হয়েছে। সঠিক TrxID দিয়ে আবার চেষ্টা করুন।")
        except: pass

# ===================== ইউজার: BUY MAIL MENU =====================
@bot.message_handler(func=lambda message: message.text == "🛒 Buy Mail")
def buy_mail_menu(message):
    user_id = message.chat.id
    if is_banned(user_id): return
    
    prices = db.collection('settings').document('prices').get().to_dict()
    markup = InlineKeyboardMarkup(row_width=1)
    
    for cat in CATEGORIES:
        stock = len(list(db.collection('inventory').where('category', '==', cat).where('status', '==', 'fresh').stream()))
        val = prices.get(cat, {}).get('validity', 'N/A')
        btn_text = f"{cat} ({val}) ({stock})"
        markup.add(InlineKeyboardButton(btn_text, callback_data=f"purchase_{cat}"))
    
    markup.add(InlineKeyboardButton("🔢 Multiple Mail Purchase", callback_data="multi_purchase_coming_soon"))
    bot.send_message(user_id, "📧 **Please select the type of mail you want to buy:**", parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("purchase_"))
def process_purchase(call):
    user_id = call.message.chat.id
    category = call.data.split('_')[1]
    
    user_ref = db.collection('users').document(str(user_id))
    bal = user_ref.get().to_dict().get('balance', 0)
    prices = db.collection('settings').document('prices').get().to_dict()
    price = prices.get(category, {}).get('price', 0)
    
    if bal < price:
        return bot.answer_callback_query(call.id, "❌ Balance কম। অনুগ্রহ করে প্রথমে ডিপোজিট করুন।", show_alert=True)
        
    fresh_mails = list(db.collection('inventory').where('category', '==', category).where('status', '==', 'fresh').limit(1).stream())
    
    if fresh_mails:
        mail_doc = fresh_mails[0]
        mail_data = mail_doc.to_dict()
        
        user_ref.update({'balance': bal - price})
        mail_doc.reference.update({'status': 'sold'})
        
        db.collection('active_sales').add({
            'user_id': user_id, 'email': mail_data['email'], 'password': mail_data['password'], 
            'category': category, 'price': price, 'buy_timestamp': time.time(), 'msg_received': False
        })
        
        bot.edit_message_text(f"🎉 **Purchase Successful!**\n━━━━━━━━━━━━━━\n📧 **Email:** `{mail_data['email']}`\n📌 **Category:** {category}\n\n💡 _'My Mail'-এ গিয়ে ইনবক্স চেক করুন। ২০ মিনিটে কোড না আসলে অটো রিফান্ড হবে।_", chat_id=user_id, message_id=call.message.message_id, parse_mode='Markdown')
    else:
        bot.answer_callback_query(call.id, "❌ Stock Out!", show_alert=True)

@bot.message_handler(func=lambda message: message.text == "📧 My Mail")
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
            markup.add(InlineKeyboardButton("📩 Check Inbox", callback_data=f"inbox|{data['email']}|{data['password']}"))
            bot.send_message(user_id, f"📧 Email: `{data['email']}`", reply_markup=markup, parse_mode='Markdown')
        if not found: bot.send_message(user_id, "আপনার কোনো সক্রিয় মেইল নেই।")
    except: pass

@bot.callback_query_handler(func=lambda call: call.data.startswith("inbox|"))
def check_inbox(call):
    user_id = call.message.chat.id
    _, email_addr, password = call.data.split('|')
    
    msg = bot.send_message(user_id, "🚀 ইনবক্স চেক করা হচ্ছে...")
    time.sleep(1.5)
    
    try:
        mail = imaplib.IMAP4_SSL('imap-mail.outlook.com')
        mail.login(email_addr, password)
        mail.select('inbox')
        status, data = mail.search(None, 'ALL')
        mail_ids = data[0].split()

        if not mail_ids:
            bot.edit_message_text(f"❌ `{email_addr}`\nনতুন কোনো মেসেজ আসেনি।", chat_id=user_id, message_id=msg.message_id, parse_mode='Markdown')
        else:
            # মেসেজ পাওয়া গেলে রিফান্ড ট্র্যাকার আপডেট করা
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
                    
                    bot.edit_message_text(f"✅ **New Message!**\n━━━━━━━━━━━━\n👤 From: `{sender}`\n📌 Sub: `{subject}`\n\n💬 `{body[:150]}`", chat_id=user_id, message_id=msg.message_id, parse_mode='Markdown')
    except:
        bot.edit_message_text("❌ লগিন এরর।", chat_id=user_id, message_id=msg.message_id)

# ================= রান স্ক্রিপ্ট (Conflict Fix) =================
if __name__ == "__main__":
    # ১. ফ্লাস্ক সার্ভার চালু করা (যাতে Render সার্ভারকে লাইভ পায়)
    threading.Thread(target=run_server, daemon=True).start()
    
    # ২. পুরনো ইনস্ট্যান্সটি বন্ধ হওয়ার জন্য ১৫ সেকেন্ড অপেক্ষা করা
    print("Waiting 15 seconds to kill the old instance...")
    time.sleep(15) 
    
    # ৩. ওয়েবহুক ক্লিয়ার করে বট চালু করা
    try:
        bot.remove_webhook()
        time.sleep(2)
        print("Starting Bot Polling...")
        bot.infinity_polling(timeout=20, long_polling_timeout=15)
    except Exception as e:
        print("Bot Polling Error:", e)
