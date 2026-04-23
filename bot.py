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
        for m in bought_mails[:5]: # Top 5 দেখাবে
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

# (ব্যান এবং এডিট ব্যালেন্সের লজিক আগের মতই থাকবে, স্পেস কমানোর জন্য হাইড করছি না)
@bot.callback_query_handler(func=lambda call: call.data.startswith("ban_") or call.data.startswith("unban_"))
def toggle_ban(call):
    action, target_id = call.data.split('_')
    new_status = 'banned' if action == 'ban' else 'active'
    db.collection('users').document(target_id).update({'status': new_status})
    bot.edit_message_text(f"✅ ইউজারকে {action} করা হয়েছে!", chat_id=call.message.chat.id, message_id=call.message.message_id)

# ===================== অ্যাডমিন: SETTINGS & PRICES =====================
@bot.message_handler(func=lambda message: message.text == "⚙️ Settings" and message.chat.id == ADMIN_ID)
def admin_settings(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("💳 Payment Setup", callback_data="setup_payments"),
        InlineKeyboardButton("🏷 Price & Time Setup", callback_data="setup_prices")
    )
    bot.send_message(message.chat.id, "⚙️ **Settings Menu**", parse_mode='Markdown', reply_markup=markup)

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
    
    # স্টক ক্যালকুলেশন
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
        
        # 20 min রিফান্ডের জন্য time.time() সেভ করা হচ্ছে 
        db.collection('active_sales').add({
            'user_id': user_id, 'email': mail_data['email'], 'password': mail_data['password'], 
            'category': category, 'price': price, 'buy_timestamp': time.time(), 'msg_received': False
        })
        
        bot.edit_message_text(f"🎉 **Purchase Successful!**\n━━━━━━━━━━━━━━\n📧 **Email:** `{mail_data['email']}`\n📌 **Category:** {category}\n\n💡 _'My Mail'-এ গিয়ে ইনবক্স চেক করুন। ২০ মিনিটে কোড না আসলে অটো রিফান্ড হবে।_", chat_id=user_id, message_id=call.message.message_id, parse_mode='Markdown')
    else:
        bot.answer_callback_query(call.id, "❌ Stock Out!", show_alert=True)

# (Add Fund, Inbox Check এবং Run Server-এর আগের সব কোড অপরিবর্তিত থাকবে)

# ================= রান স্ক্রিপ্ট =================
if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1) 
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
