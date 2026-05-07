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
import re

# ================= কনফিগারেশন =================
API_TOKEN = '8526670393:AAGt_si_DtCAKjGF2Ht8uAmdQeO1rp1sOas'
ADMIN_ID = 6670461311

bot = telebot.TeleBot(API_TOKEN)
app = Flask(__name__)

user_states = {} 
SERVICES = ['Instagram', 'Facebook', 'YouTube', 'TikTok', 'Twitter', 'Other']

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
        prices_ref.set({'Gmail': {'price': 6, 'validity': '6 Hours'}})
except Exception as e:
    print("Firebase Error:", e)

# ================= ব্যাকগ্রাউন্ড চেকার (রিফান্ড এবং ৬ ঘণ্টা রিটার্ন) =================
def auto_inventory_manager():
    while True:
        time.sleep(60) 
        try:
            now = time.time()
            sales = db.collection('active_sales').stream()
            for sale in sales:
                data = sale.to_dict()
                buy_time = data.get('buy_timestamp', 0)
                msg_received = data.get('msg_received', False)
                elapsed = now - buy_time
                
                service = data.get('service', 'Other')
                cooldowns = data.get('cooldowns', {})
                
                # রুল ১: ২০ মিনিট ওভার এবং কোনো মেসেজ আসেনি (অটো রিফান্ড)
                if elapsed >= 1200 and not msg_received:
                    user_ref = db.collection('users').document(str(data['user_id']))
                    cur_bal = user_ref.get().to_dict().get('balance', 0)
                    user_ref.update({'balance': cur_bal + data['price']})
                    
                    db.collection('inventory').add({
                        'email': data['email'], 'password': data['password'], 
                        'category': 'Gmail', 'status': 'fresh', 'cooldowns': cooldowns
                    })
                    
                    try:
                        bot.send_message(data['user_id'], f"⚠️ **অটো রিফান্ড!**\n২০ মিনিটে `{service}` এর কোনো কোড না আসায় `{data['email']}` বাতিল করে আপনার {data['price']} ৳ রিফান্ড করা হয়েছে।", parse_mode='Markdown')
                    except: pass
                    sale.reference.delete()
                    
                # রুল ২: ৬ ঘণ্টা (২১৬০০ সেকেন্ড) ওভার (অটো রিটার্ন টু স্টক, নো রিফান্ড)
                elif elapsed >= 21600:
                    if msg_received:
                        cooldowns[service] = now # ৫ দিনের কুলডাউন শুরু
                        
                    db.collection('inventory').add({
                        'email': data['email'], 'password': data['password'], 
                        'category': 'Gmail', 'status': 'fresh', 'cooldowns': cooldowns
                    })
                    
                    try:
                        bot.send_message(data['user_id'], f"⏳ **সময় শেষ!**\n৬ ঘণ্টা পার হয়ে যাওয়ায় `{data['email']}` মেইলটির মেয়াদ শেষ হয়েছে।", parse_mode='Markdown')
                    except: pass
                    sale.reference.delete()
        except: pass

threading.Thread(target=auto_inventory_manager, daemon=True).start()

# ================= সার্ভার =================
@app.route('/')
def home():
    return "Waleya OTP Verification Bot is Running!"

def run_server():
    port = int(os.environ.get("PORT", 8080))
    app.run(host="0.0.0.0", port=port)

# ================= কীবোর্ড মেনু =================
def user_menu():
    markup = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        KeyboardButton("🛒 Purchase Mail"), KeyboardButton("📧 My Codes"),
        KeyboardButton("💳 Balance & Stock"), KeyboardButton("👤 My Profile"),
        KeyboardButton("ℹ️ Support")
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
        bot.send_message(user_id, f"স্বাগতম অ্যাডমিন {name}!", reply_markup=admin_menu())
    else:
        bot.send_message(user_id, f"স্বাগতম {name}! OTP Verification সিস্টেমে আপনাকে স্বাগতম।", reply_markup=user_menu())

@bot.message_handler(func=lambda message: message.text == "❌ Cancel Action")
def cancel_action(message):
    bot.clear_step_handler_by_chat_id(message.chat.id)
    menu = admin_menu() if message.chat.id == ADMIN_ID else user_menu()
    bot.send_message(message.chat.id, "❌ একশন বাতিল করা হয়েছে।", reply_markup=menu)

# ===================== ইউজার: BEAUTIFUL BALANCE =====================
@bot.message_handler(func=lambda message: message.text == "💳 Balance & Stock")
def balance_menu(message):
    if is_banned(message.chat.id): return
    bal = db.collection('users').document(str(message.chat.id)).get().to_dict().get('balance', 0)
    prices = db.collection('settings').document('prices').get().to_dict()
    stock = len(list(db.collection('inventory').where('category', '==', 'Gmail').where('status', '==', 'fresh').stream()))
    
    p = prices.get('Gmail', {}).get('price', 0)
    
    text = f"""
💳 **User Account Balance**
╔════════════════════╗
  💰 **{float(bal):.2f} TK**
╚════════════════════╝

📋 **Service Price List**
╔════════════════════╗
 📧 Any Service OTP ➔ {p}.00 TK
 ⏱ Validity: 6 Hours
╚════════════════════╝

📦 **Current Stock**
╔════════════════════╗
 📦 Total Fresh Mails: {stock}
╚════════════════════╝
    """
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("➕ Add Fund / Deposit", callback_data="add_fund_start"))
    bot.send_message(message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

# ===================== ইউজার: PURCHASE & SERVICE SELECTION =====================
@bot.message_handler(func=lambda message: message.text == "🛒 Purchase Mail")
def purchase_service_selection(message):
    user_id = message.chat.id
    if is_banned(user_id): return
    
    markup = InlineKeyboardMarkup(row_width=2)
    for srv in SERVICES:
        markup.add(InlineKeyboardButton(f"📌 {srv}", callback_data=f"buy_srv_{srv}"))
    
    bot.send_message(user_id, "📧 **কোন সার্ভিসের জন্য মেইল বা OTP নিতে চান?**\n_নিচের লিস্ট থেকে সিলেক্ট করুন:_ ", parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_srv_"))
def process_purchase(call):
    bot.answer_callback_query(call.id)
    user_id = call.message.chat.id
    service = call.data.split('_')[2]
    
    user_ref = db.collection('users').document(str(user_id))
    bal = user_ref.get().to_dict().get('balance', 0)
    prices = db.collection('settings').document('prices').get().to_dict()
    price = prices.get('Gmail', {}).get('price', 0)
    
    if bal < price:
        return bot.send_message(user_id, f"❌ আপনার ব্যালেন্স পর্যাপ্ত নয়। দাম {price} ৳।")
        
    # ফ্রেশ মেইল খোঁজা এবং ৫ দিনের কুলডাউন চেক করা
    fresh_mails = db.collection('inventory').where('category', '==', 'Gmail').where('status', '==', 'fresh').stream()
    selected_mail_doc = None
    selected_data = None
    
    now = time.time()
    for m in fresh_mails:
        data = m.to_dict()
        cooldowns = data.get('cooldowns', {})
        last_used = cooldowns.get(service, 0)
        
        # যদি ৫ দিন (৪৩২০০০ সেকেন্ড) পার হয়ে যায়, তবেই ওই সার্ভিসের জন্য মেইলটি দেওয়া হবে
        if now - last_used > 432000:
            selected_mail_doc = m
            selected_data = data
            break
            
    if selected_mail_doc:
        user_ref.update({'balance': bal - price})
        selected_mail_doc.reference.update({'status': 'sold'})
        
        db.collection('active_sales').add({
            'user_id': user_id, 'email': selected_data['email'], 'password': selected_data['password'], 
            'category': 'Gmail', 'price': price, 'buy_timestamp': now, 
            'msg_received': False, 'service': service, 'cooldowns': selected_data.get('cooldowns', {})
        })
        
        text = f"""
✅ **Number / Mail Assigned Successfully!**
━━━━━━━━━━━━━━━━━━━━
📌 **Service:** {service}
📧 **Email:** `{selected_data['email']}`

_• If you need codes, click 'Refresh Code' below ⬇️_
        """
        bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, parse_mode='Markdown')
    else:
        bot.send_message(user_id, f"❌ এই মুহূর্তে **{service}** এর জন্য কোনো ফ্রেশ মেইল স্টকে নেই। একটু পর চেষ্টা করুন।")

# ===================== ইউজার: MY CODES & RETURN =====================
@bot.message_handler(func=lambda message: message.text == "📧 My Codes")
def my_mails(message):
    user_id = message.chat.id
    if is_banned(user_id): return
    try:
        active_sales = db.collection('active_sales').where('user_id', '==', user_id).stream()
        found = False
        for sale in active_sales:
            found = True
            data = sale.to_dict()
            markup = InlineKeyboardMarkup()
            markup.add(
                InlineKeyboardButton("🔄 Refresh Code", callback_data=f"inbox_{sale.id}"),
                InlineKeyboardButton("🗑 Delete & Return", callback_data=f"retmail_{sale.id}")
            )
            bot.send_message(user_id, f"📌 **Service:** {data.get('service', 'Other')}\n📧 **Email:** `{data['email']}`", reply_markup=markup, parse_mode='Markdown')
        if not found: bot.send_message(user_id, "আপনার কোনো সক্রিয় মেইল নেই।")
    except Exception as e:
        print(e)

@bot.callback_query_handler(func=lambda call: call.data.startswith("retmail_"))
def return_user_mail(call):
    bot.answer_callback_query(call.id)
    sale_id = call.data.split('_')[1]
    user_id = call.message.chat.id
    
    sale_ref = db.collection('active_sales').document(sale_id)
    sale_doc = sale_ref.get()
    
    if sale_doc.exists:
        data = sale_doc.to_dict()
        price = data.get('price', 0)
        msg_received = data.get('msg_received', False)
        service = data.get('service', 'Other')
        cooldowns = data.get('cooldowns', {})
        
        if msg_received:
            cooldowns[service] = time.time() # ৫ দিনের জন্য ব্লক করা হলো
            
        db.collection('inventory').add({
            'email': data['email'], 'password': data['password'], 
            'category': 'Gmail', 'status': 'fresh', 'cooldowns': cooldowns
        })
        
        if not msg_received:
            user_ref = db.collection('users').document(str(user_id))
            cur_bal = user_ref.get().to_dict().get('balance', 0)
            user_ref.update({'balance': cur_bal + price})
            msg_text = f"✅ মেইলটি ফেরত দেওয়া হয়েছে এবং আপনার ব্যালেন্স {price} ৳ রিফান্ড করা হয়েছে।"
        else:
            msg_text = f"✅ মেইলটি আপনার লিস্ট থেকে ডিলিট করা হয়েছে। (যেহেতু আপনি কোড রিসিভ করেছিলেন, তাই কোনো রিফান্ড হয়নি)।"
            
        sale_ref.delete()
        bot.edit_message_text(msg_text, chat_id=user_id, message_id=call.message.message_id)
    else:
        bot.send_message(user_id, "❌ মেইলটি ডাটাবেসে পাওয়া যায়নি।")

# ===================== ইনবক্স চেকিং ও OTP এক্সট্রাক্টর (Smart Parse) =====================
def extract_otp(text):
    # HTML ট্যাগ রিমুভ করা
    clean_text = re.sub(r'<[^>]+>', ' ', text)
    
    # 6-8 ডিজিটের কোড (মাঝে স্পেস থাকলেও ধরবে, যেমন: 123 456)
    match = re.search(r'\b\d{3}\s?\d{3,5}\b', clean_text)
    if match: return match.group(0).strip()
    
    # আলফানিউমেরিক কোড (যেমন: HasjYsb) 
    match = re.search(r'(?i)(?:code|otp|password|pin).*?\b([A-Za-z0-9]{6,8})\b', clean_text.replace(" ", ""))
    if match: return match.group(1).strip()
    
    return None

@bot.callback_query_handler(func=lambda call: call.data.startswith("inbox_"))
def check_inbox(call):
    bot.answer_callback_query(call.id)
    sale_id = call.data.split('_')[1]
    user_id = call.message.chat.id
    
    sale_ref = db.collection('active_sales').document(sale_id)
    sale_doc = sale_ref.get()
    
    if not sale_doc.exists:
        return bot.edit_message_text("❌ এই মেইলটি আর ডাটাবেসে নেই বা মেয়াদ শেষ।", chat_id=user_id, message_id=call.message.message_id)
        
    data = sale_doc.to_dict()
    email_addr = data['email']
    password = data['password']
    service_keyword = data.get('service', 'Other').lower()
    
    bot.edit_message_text("🔍 Searching for email, please wait...", chat_id=user_id, message_id=call.message.message_id)
    
    try:
        mail = imaplib.IMAP4_SSL('imap.gmail.com')
        mail.login(email_addr, password)
        mail.select('inbox')
        status, search_data = mail.search(None, 'ALL')
        mail_ids = search_data[0].split()

        if not mail_ids:
            bot.edit_message_text(f"❌ `{email_addr}`\nইনবক্সে এখনো কোনো মেসেজ আসেনি।", chat_id=user_id, message_id=call.message.message_id, parse_mode='Markdown')
            return

        # শুধুমাত্র কাঙ্ক্ষিত সার্ভিসের মেইল খোঁজা (সর্বশেষ ১০টি মেইল চেক করবে)
        found_msg = None
        for m_id in reversed(mail_ids[-10:]):
            status, msg_data = mail.fetch(m_id, '(RFC822)')
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
                    
                    # যদি সার্ভিস 'Other' হয় অথবা সেন্ডার/সাবজেক্টে সার্ভিসের নাম থাকে
                    if service_keyword == 'other' or service_keyword in sender.lower() or service_keyword in subject.lower():
                        found_msg = (sender, subject, body)
                        break
            if found_msg: break

        if not found_msg:
            bot.edit_message_text(f"❌ **{data.get('service')}** থেকে এখনো কোনো নতুন কোড আসেনি। একটু পর আবার রিফ্রেশ করুন।", chat_id=user_id, message_id=call.message.message_id, parse_mode='Markdown')
        else:
            sender, subject, body = found_msg
            sale_ref.update({'msg_received': True})
            
            # স্মার্ট কোড এক্সট্রাকশন
            otp_code = extract_otp(subject + " " + body)
            
            text = f"**SUPPORT WALEYA OTP**\nEmail: `{email_addr}`\n\n"
            if otp_code:
                text += f"🔑 **Latest Code:** `{otp_code}`\n\n"
            
            # মেসেজের স্নাইপেট
            text += f"❝ {body[:120].strip()}... ❞"
            
            bot.edit_message_text(text, chat_id=user_id, message_id=call.message.message_id, parse_mode='Markdown')
            
    except Exception as e:
        bot.edit_message_text(f"❌ **Login Failed!** App Password চেক করুন।", chat_id=user_id, message_id=call.message.message_id)

# ===================== ইউজার: ADD FUND & PAYMENT =====================
@bot.callback_query_handler(func=lambda call: call.data == "add_fund_start")
def ask_fund_amount(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "আপনি কত টাকা অ্যাড করতে চান? (যেমন: 100)", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, ask_payment_gateway)

def ask_payment_gateway(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
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
        bot.send_message(message.chat.id, "ক্যানসেল করতে চাইলে নিচের মেনু থেকে Cancel চাপুন।", reply_markup=cancel_markup())
    except:
        bot.send_message(message.chat.id, "❌ সঠিক টাকার পরিমাণ দিন।", reply_markup=user_menu())

@bot.callback_query_handler(func=lambda call: call.data.startswith("pay_"))
def show_payment_details(call):
    bot.answer_callback_query(call.id)
    method = call.data.split('_')[1]
    amount = user_states.get(call.message.chat.id, {}).get('amount', 0)
    
    settings = db.collection('settings').document('payment_methods').get().to_dict()
    account_info = settings.get(method, "Not Setup Yet")
    
    user_states[call.message.chat.id]['method'] = method
    
    text = f"💳 **Payment details for {method.capitalize()}**\n━━━━━━━━━━━━━━\nপরিমাণ: {amount} ৳\nনম্বর/ID: `{account_info}` (কপি করতে ট্যাপ করুন)\n\nটাকা পাঠানোর পর আপনার Transaction ID নিচে লিখে দিন:"
    msg = bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, process_trx_id)

def process_trx_id(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
        
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
    bot.answer_callback_query(call.id)
    action, req_id = call.data.split('_', 1)
    req_doc = db.collection('payment_requests').document(req_id)
    req_data = req_doc.get().to_dict()
    
    if req_data['status'] != 'pending':
        return bot.send_message(call.message.chat.id, "এই রিকোয়েস্টটি আগেই প্রসেস করা হয়েছে।")
    
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

# ===================== ইউজার: প্রোফাইল ও ইনফো =====================
@bot.message_handler(func=lambda message: message.text == "👤 My Profile")
def user_profile(message):
    user_id = message.chat.id
    data = db.collection('users').document(str(user_id)).get().to_dict()
    bought = len(list(db.collection('active_sales').where('user_id', '==', user_id).stream()))
    
    text = f"""
💠 **PREMIUM USER PROFILE** 💠
━━━━━━━━━━━━━━━━━━━━
👤 **Name:** {data.get('name') or 'User'}
🆔 **User ID:** `{user_id}`
💰 **Balance:** {float(data.get('balance', 0)):.2f} TK
🛒 **Total Bought:** {bought} Services
🏆 **Status:** Verified Customer
━━━━━━━━━━━━━━━━━━━━
    """
    bot.send_message(user_id, text, parse_mode='Markdown')

@bot.message_handler(func=lambda message: message.text == "ℹ️ Support")
def bot_info(message):
    text = f"""
🌟 **WALEYA VERIFICATION SHOP** 🌟
━━━━━━━━━━━━━━━━━━━━
🚀 **বটের সুবিধাগুলো:**
✓ ইনস্ট্যান্ট OTP ডেলিভারি
✓ ৬ ঘণ্টার ভ্যালিডিটি এবং ৫ দিনের কুলডাউন
✓ স্মার্ট অটো-রিফান্ড সিস্টেম
✓ হাই-কোয়ালিটি প্রিমিয়াম সার্ভিস

👨‍💻 **Developer:** [Waleya](tg://user?id={ADMIN_ID})
📞 **Support:** [Contact Admin](tg://user?id={ADMIN_ID})
━━━━━━━━━━━━━━━━━━━━
    """
    bot.send_message(message.chat.id, text, parse_mode='Markdown')

# ===================== অ্যাডমিন: ড্যাশবোর্ড ও সেটিংস =====================
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
    bot.answer_callback_query(call.id)
    page = int(call.data.split('_')[1])
    users = list(db.collection('users').stream())
    total = len(users)
    start = page * 10
    chunk = users[start:start+10]
    
    text = f"👥 **Total Users: {total}**\n━━━━━━━━━━━━━━\n"
    for u in chunk:
        d = u.to_dict()
        name = d.get('name') or 'User'
        text += f"👤 {name} | `{u.id}` | {d.get('balance', 0)}৳\n"
        
    markup = InlineKeyboardMarkup()
    nav = []
    if start > 0: nav.append(InlineKeyboardButton("⬅️ Prev", callback_data=f"userpage_{page-1}"))
    if start + 10 < total: nav.append(InlineKeyboardButton("Next ➡️", callback_data=f"userpage_{page+1}"))
    if nav: markup.add(*nav)
    markup.add(InlineKeyboardButton("📄 Export to TXT", callback_data="export_users"))
    bot.edit_message_text(text, chat_id=call.message.chat.id, message_id=call.message.message_id, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "export_users")
def export_users_txt(call):
    bot.answer_callback_query(call.id)
    users = list(db.collection('users').stream())
    text_data = "Name | ID | Balance | Status\n" + "-"*40 + "\n"
    for u in users:
        d = u.to_dict()
        name = d.get('name') or 'User'
        text_data += f"{name} | {u.id} | {d.get('balance', 0)} | {d.get('status', 'active')}\n"
    file_data = io.BytesIO(text_data.encode('utf-8'))
    file_data.name = "Users.txt"
    bot.send_document(call.message.chat.id, file_data, caption="📂 Full User Database")

@bot.callback_query_handler(func=lambda call: call.data == "search_user")
def ask_user_search(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, "🔎 User ID লিখে পাঠান:", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, search_user_details)

def search_user_details(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    target_id = message.text.strip()
    user_ref = db.collection('users').document(target_id).get()
    
    if user_ref.exists:
        data = user_ref.to_dict()
        bought_mails = list(db.collection('active_sales').where('user_id', '==', int(target_id)).stream())
        
        status_icon = "✅ Active" if data.get('status') != 'banned' else "🚫 Banned"
        name = data.get('name') or 'User'
        text = f"👤 **User Details**\n━━━━━━━━━━━━\n🆔 ID: `{target_id}`\n👤 Name: {name}\n💰 Balance: {data.get('balance', 0)} ৳\n🛒 Total Bought: {len(bought_mails)}\n📌 Status: {status_icon}\n"
            
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
    bot.answer_callback_query(call.id)
    action, target_id = call.data.split('_')
    new_status = 'banned' if action == 'ban' else 'active'
    db.collection('users').document(target_id).update({'status': new_status})
    bot.edit_message_text(f"✅ ইউজারকে {action} করা হয়েছে!", chat_id=call.message.chat.id, message_id=call.message.message_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith("editbal_"))
def ask_new_balance(call):
    bot.answer_callback_query(call.id)
    target_id = call.data.split('_')[1]
    msg = bot.send_message(call.message.chat.id, f"`{target_id}` এর জন্য নতুন ব্যালেন্স অ্যামাউন্ট লিখুন (যেমন: 500):", parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, save_new_balance, target_id)

def save_new_balance(message, target_id):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    try:
        new_bal = int(message.text)
        db.collection('users').document(target_id).update({'balance': new_bal})
        bot.send_message(message.chat.id, f"✅ ব্যালেন্স আপডেট করে {new_bal} ৳ করা হয়েছে!", reply_markup=admin_menu())
        bot.send_message(target_id, f"🎉 অ্যাডমিন আপনার ব্যালেন্স আপডেট করে {new_bal} ৳ করেছেন!")
    except:
        bot.send_message(message.chat.id, "❌ শুধু সংখ্যা দিন।", reply_markup=admin_menu())

# ===================== অ্যাডমিন: MANAGE INVENTORY =====================
@bot.message_handler(func=lambda message: message.text == "📧 Manage Inventory" and message.chat.id == ADMIN_ID)
def manage_mails(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("➕ Add Gmails", callback_data="add_mails"),
        InlineKeyboardButton("📋 Mail List & Delete", callback_data="view_mails")
    )
    bot.send_message(message.chat.id, "মেইল ম্যানেজমেন্ট মেনু:", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "add_mails")
def enter_mails_to_add(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"নতুন জিমেইলগুলো নিচে দিন।\nফরম্যাট: `email|password` (এখানে App Password দিবেন)", parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, process_add_mails)

def process_add_mails(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    lines = message.text.split('\n')
    added = 0
    for line in lines:
        if '|' in line:
            email_addr, password = line.split('|')
            db.collection('inventory').add({
                'email': email_addr.strip(), 'password': password.strip(), 
                'category': 'Gmail', 'status': 'fresh', 'cooldowns': {}
            })
            added += 1
    bot.send_message(message.chat.id, f"✅ ডাটাবেসে {added} টি জিমেইল যুক্ত হয়েছে!", reply_markup=admin_menu(), parse_mode='Markdown')

@bot.callback_query_handler(func=lambda call: call.data == "view_mails")
def view_mails(call):
    bot.answer_callback_query(call.id)
    mails = list(db.collection('inventory').limit(10).stream())
    if not mails:
        return bot.send_message(call.message.chat.id, "স্টকে কোনো মেইল নেই।")
    
    text = "📋 **সর্বশেষ ১০টি মেইলের লিস্ট:**\n\n"
    markup = InlineKeyboardMarkup()
    for m in mails:
        data = m.to_dict()
        tag = "🟢 Fresh" if data['status'] == 'fresh' else "🔴 Sold"
        text += f"📧 `{data['email']}` - {tag}\n"
        markup.add(InlineKeyboardButton(f"🗑 Delete {data['email']}", callback_data=f"delmail_{m.id}"))
    
    markup.add(InlineKeyboardButton("📄 Export All to TXT File", callback_data="export_all_mails"))
    bot.send_message(call.message.chat.id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "export_all_mails")
def export_all_mails_txt(call):
    bot.answer_callback_query(call.id)
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
    bot.answer_callback_query(call.id)
    doc_id = call.data.split('_')[1]
    db.collection('inventory').document(doc_id).delete()
    bot.edit_message_text("✅ মেইলটি ডাটাবেস থেকে ডিলিট করা হয়েছে।", chat_id=call.message.chat.id, message_id=call.message.message_id)

# ===================== অ্যাডমিন: SETTINGS & NOTICE =====================
@bot.message_handler(func=lambda message: message.text == "⚙️ Bot Settings" and message.chat.id == ADMIN_ID)
def admin_settings(message):
    markup = InlineKeyboardMarkup()
    markup.add(
        InlineKeyboardButton("💳 Payment Gateway Setup", callback_data="setup_payments"),
        InlineKeyboardButton("🏷 Service Price Setup", callback_data="setprice_Gmail")
    )
    bot.send_message(message.chat.id, "⚙️ **Bot Settings Menu**", parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "setup_payments")
def payment_setup(call):
    bot.answer_callback_query(call.id)
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
    bot.answer_callback_query(call.id)
    method = call.data.split('_')[1]
    msg = bot.send_message(call.message.chat.id, f"নতুন {method.capitalize()} নম্বর/ID দিন:", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, save_payment_method, method)

def save_payment_method(message, method):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    db.collection('settings').document('payment_methods').update({method: message.text.strip()})
    bot.send_message(message.chat.id, f"✅ {method.capitalize()} আপডেট করা হয়েছে!", reply_markup=admin_menu())

@bot.callback_query_handler(func=lambda call: call.data == "setprice_Gmail")
def ask_price(call):
    bot.answer_callback_query(call.id)
    msg = bot.send_message(call.message.chat.id, f"**OTP Service** এর জন্য নতুন প্রাইস দিন।\n(যেমন: `6`)", parse_mode='Markdown', reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, save_price_validity)

def save_price_validity(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
    try:
        price = int(message.text.strip())
        db.collection('settings').document('prices').update({
            'Gmail': {'price': price, 'validity': '6 Hours'}
        })
        bot.send_message(message.chat.id, f"✅ প্রাইস আপডেট হয়েছে!\nPrice: {price}৳", parse_mode='Markdown', reply_markup=admin_menu())
    except:
        bot.send_message(message.chat.id, "❌ ফরম্যাট ভুল। শুধু সংখ্যা দিন।", reply_markup=admin_menu())

@bot.message_handler(func=lambda message: message.text == "📢 Global Notice" and message.chat.id == ADMIN_ID)
def send_notice_start(message):
    msg = bot.send_message(message.chat.id, "সব ইউজারের কাছে যে নোটিশ পাঠাতে চান, তা লিখে পাঠান:", reply_markup=cancel_markup())
    bot.register_next_step_handler(msg, broadcast_notice)

def broadcast_notice(message):
    if message.text == "❌ Cancel Action": return cancel_action(message)
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


# ================= রান স্ক্রিপ্ট =================
if __name__ == "__main__":
    threading.Thread(target=run_server, daemon=True).start()
    print("Waiting 15 seconds to kill the old instance...")
    time.sleep(15) 
    
    try:
        bot.remove_webhook()
        time.sleep(2)
        print("Starting Verification Bot...")
        bot.infinity_polling(timeout=20, long_polling_timeout=15)
    except Exception as e:
        print("Bot Polling Error:", e)
