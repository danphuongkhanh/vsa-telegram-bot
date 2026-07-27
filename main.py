import os
import time
import threading
import asyncio
import re
from datetime import datetime, timedelta
from http.server import HTTPServer, BaseHTTPRequestHandler
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, MessageHandler, filters, ContextTypes
from vnstock.api.quote import Quote
from google import genai
from google.genai import types

# ==========================================
# 1. KHỞI TẠO WEB SERVER ĐỂ RENDER WEB SERVICE FREE
# ==========================================
class HealthCheckHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write("Bot VSA Telegram đang hoạt động 24/7!".encode("utf-8"))
        
    def log_message(self, format, *args):
        return  # Tắt log HTTP thừa

def run_health_check_server():
    port = int(os.environ.get("PORT", 10000))
    try:
        server = HTTPServer(('0.0.0.0', port), HealthCheckHandler)
        print(f"🌐 Web Server cho Render đã kích hoạt trên Port {port}")
        server.serve_forever()
    except Exception as e:
        print(f"⚠️ Lỗi Web Server: {e}")

# Kích hoạt Web Server trên luồng riêng
threading.Thread(target=run_health_check_server, daemon=True).start()

# ==========================================
# 2. CẤU HÌNH TOKEN VÀ KEY (THAY KEY MỚI BẮT ĐẦU BẰNG AIzaSy... VÀO ĐÂY)
# ==========================================
TELEGRAM_TOKEN = "8834290127:AAHX9rNmHD3NOZx8q7I39Jmmz999WU3t1dE"
GEMINI_API_KEY = "AQ.Ab8RN6KAMnzQ_5EOfsun4KrYWpkJ4WZaSdghHHwIDndZOClZvg"

MY_CHAT_ID = None
WATCHLIST = ["SSI", "HPG", "PDR", "KBC", "MWG", "TCB", "VCI", "DIG", "CEO", "VHM"]

ai_client = genai.Client(api_key=GEMINI_API_KEY)
WORKING_MODEL_CACHE = None

# ==========================================
# 3. CÁC HÀM XỬ LÝ DỮ LIỆU ĐỒNG BỘ (SYNC)
# ==========================================
def call_gemini_bulletproof(prompt, use_search=False):
    global WORKING_MODEL_CACHE
    
    search_config = types.GenerateContentConfig(
        tools=[types.Tool(google_search=types.GoogleSearch())]
    ) if use_search else None

    # Ưu tiên các mô hình Gemini ổn định nhất
    models_to_try = ['gemini-2.5-flash', 'gemini-2.0-flash', 'gemini-1.5-flash', 'gemini-1.5-pro']
    if WORKING_MODEL_CACHE and WORKING_MODEL_CACHE in models_to_try:
        models_to_try.remove(WORKING_MODEL_CACHE)
        models_to_try.insert(0, WORKING_MODEL_CACHE)

    last_error = None
    for model_name in models_to_try:
        try:
            response = ai_client.models.generate_content(
                model=model_name, 
                contents=prompt,
                config=search_config
            )
            if response and response.text:
                WORKING_MODEL_CACHE = model_name
                return response.text
        except Exception as e:
            last_error = e
            print(f"⚠️ Thử Gemini model '{model_name}' thất bại: {e}")
            if use_search:
                try:
                    response = ai_client.models.generate_content(model=model_name, contents=prompt)
                    if response and response.text:
                        WORKING_MODEL_CACHE = model_name
                        return response.text
                except Exception as inner_e:
                    last_error = inner_e
            continue

    raise Exception(f"Lỗi kết nối Gemini API. Chi tiết: {last_error}")

def get_upcoming_listings_report():
    try:
        prompt = """
        Bạn là Chuyên gia Tư vấn Đầu tư Chứng khoán Việt Nam.
        NHIỆM VỤ: Tra cứu thông tin MỚI NHẤT về các doanh nghiệp/cổ phiếu SẮP NIÊM YẾT hoặc MỚI ĐƯỢC CHẤP THUẬN NIÊM YẾT trên các sàn HOSE, HNX, UPCoM.
        BÁO CÁO TỔNG HỢP:
        1. Danh sách Mã/Doanh nghiệp chuẩn bị lên sàn (Sàn dự kiến, Số lượng CP, Giá tham chiếu/IPO, Ngày dự kiến).
        2. Đánh giá nhanh tiềm năng & cơ hội lướt sóng T+ hoặc nắm giữ.
        """
        return call_gemini_bulletproof(prompt, use_search=True)
    except Exception as e:
        return f"❌ Lỗi khi tìm kiếm thông tin niêm yết: {str(e)}"

def analyze_vsa_and_news(symbol):
    try:
        symbol = symbol.upper().strip()
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=35)).strftime('%Y-%m-%d')
        
        stock_quote = Quote(symbol=symbol, source='VCI')
        df_stock = stock_quote.history(start=start_date, end=end_date)
        
        if df_stock is None or df_stock.empty:
            return f"⚠️ Không tìm thấy dữ liệu giao dịch cho mã '{symbol}'."
        
        latest_stock = df_stock.tail(5).to_dict(orient="records")
        
        prompt = f"""
        Bạn là Chuyên gia Phân tích Đầu tư Chứng khoán Việt Nam (VSA & Catalysts Doanh nghiệp).
        DỮ LIỆU GIAO DỊCH VSA 5 PHIÊN GẦN NHẤT CỦA MÃ {symbol}: {latest_stock}

        NHIỆM VỤ:
        1. Tra cứu TIN TỨC/SỰ KIỆN HOT về {symbol} (Cổ tức, BCTC mới nhất, Game tăng vốn...).
        2. PHÂN TÍCH VSA & CUNG CẦU THỰC TẾ (CMP, Test Cung, Shakeout, SOS...).
        3. LẬP KẾ HOẠCH LƯỚT SÓNG T+2.5 (Vùng Mua 1, Vùng Mua 2, Cắt lỗ %, Chốt lời TP1/TP2).
        """
        return call_gemini_bulletproof(prompt, use_search=True)
    except Exception as e:
        return f"❌ Lỗi khi phân tích mã {symbol}: {str(e)}"

def scan_smart_money_signals():
    alerts = []
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=35)).strftime('%Y-%m-%d')
    
    for symbol in WATCHLIST:
        try:
            df = Quote(symbol=symbol, source='VCI').history(start=start_date, end=end_date)
            if df is not None and len(df) >= 20:
                recent_volume = df.iloc[-1]['volume']
                avg_volume_20 = df.tail(20)['volume'].mean()
                price_change = ((df.iloc[-1]['close'] - df.iloc[-2]['close']) / df.iloc[-2]['close']) * 100
                
                if recent_volume > 1.8 * avg_volume_20 and price_change > 2.0:
                    alerts.append(
                        f"🔥 **CẢNH BÁO DÒNG TIỀN LỚN: {symbol}**\n"
                        f"- Giá hiện tại: {df.iloc[-1]['close']:,} VNĐ ({price_change:+.2f}%)\n"
                        f"- Thanh khoản: {recent_volume:,.0f} CP (Gấp {recent_volume/avg_volume_20:.1f} lần TB20 phiên)\n"
                        f"👉 *Tín hiệu VSA: Xảy ra phiên Bứt phá (SOS) - Smart Money đã nhập cuộc!*"
                    )
        except Exception:
            continue
    return alerts

def get_daily_report(report_type="morning"):
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=15)).strftime('%Y-%m-%d')
    
    df_vni = Quote(symbol='VNINDEX', source='VCI').history(start=start_date, end=end_date)
    latest_vni = df_vni.tail(3).to_dict(orient="records") if (df_vni is not None and not df_vni.empty) else []
    
    if report_type == "morning":
        prompt = f"Lập BẢN TIN ĐẦU PHIÊN (8:45 AM) với dữ liệu VN-Index: {latest_vni}"
    else:
        prompt = f"Lập BẢN TIN KẾT PHIÊN (15:15 PM) với dữ liệu VN-Index: {latest_vni}"
    return call_gemini_bulletproof(prompt, use_search=True)

# ==========================================
# 4. CÁC HÀM XỬ LÝ BẤT ĐỒNG BỘ (ASYNC HANDLERS)
# ==========================================
async def auto_background_worker(app):
    global MY_CHAT_ID
    already_sent_morning = False
    already_sent_evening = False
    
    while True:
        try:
            now = datetime.now()
            current_time = now.strftime("%H:%M")
            
            if now.weekday() < 5:
                if current_time == "08:45" and not already_sent_morning and MY_CHAT_ID:
                    report = await asyncio.to_thread(get_daily_report, "morning")
                    await app.bot.send_message(chat_id=MY_CHAT_ID, text=f"☀️ **BÁO CÁO ĐẦU PHIÊN (08:45 AM)**\n\n{report}")
                    already_sent_morning = True

                if current_time == "15:15" and not already_sent_evening and MY_CHAT_ID:
                    report = await asyncio.to_thread(get_daily_report, "evening")
                    await app.bot.send_message(chat_id=MY_CHAT_ID, text=f"🌆 **BÁO CÁO KẾT PHIÊN (15:15 PM)**\n\n{report}")
                    already_sent_evening = True

                if current_time == "00:00":
                    already_sent_morning = False
                    already_sent_evening = False

                if "09:15" <= current_time <= "14:30" and now.minute % 15 == 0 and MY_CHAT_ID:
                    alerts = await asyncio.to_thread(scan_smart_money_signals)
                    for alert in alerts:
                        await app.bot.send_message(chat_id=MY_CHAT_ID, text=alert)

        except Exception as e:
            print(f"Lỗi tiến trình ngầm: {e}")
            
        await asyncio.sleep(60)

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MY_CHAT_ID
    MY_CHAT_ID = update.effective_chat.id
    welcome_text = (
        "🤖 **TRỢ LÝ CHỨNG KHOÁN VSA, TIN TỨC & CỔ PHIẾU SẮP LÊN SÀN!**\n\n"
        "✅ Đã kết nối hệ thống tự động 24/7 trên Render.\n\n"
        "📌 **Các lệnh hỗ trợ:**\n"
        "• Gõ `/niemyet` hoặc nhắn `cổ phiếu sắp lên sàn`: Xem danh sách CP sắp IPO/chào sàn.\n"
        "• Gõ mã bất kỳ (Ví dụ: `VHM`, `SSI`): Phân tích VSA + Cổ tức + BCTC.\n"
        "• Gõ `thị trường` hoặc `/capnhat`: Cập nhật VN-Index.\n"
        "• Gõ `/canhbao`: Quét mã có Dòng Tiền Lớn đột biến."
    )
    await update.message.reply_text(welcome_text)

async def upcoming_listings_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Đang quét thông tin doanh nghiệp/cổ phiếu sắp niêm yết lên sàn...")
    result = await asyncio.to_thread(get_upcoming_listings_report)
    await update.message.reply_text(result)

async def trigger_scan_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🔍 Đang quét dòng tiền lớn...")
    alerts = await asyncio.to_thread(scan_smart_money_signals)
    if alerts:
        for alert in alerts:
            await update.message.reply_text(alert)
    else:
        await update.message.reply_text("✅ Chưa phát hiện mã bùng nổ thanh khoản bất thường.")

async def text_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global MY_CHAT_ID
    MY_CHAT_ID = update.effective_chat.id
    user_text = update.message.text.strip()
    clean_text = user_text.lower()
    
    if any(k in clean_text for k in ["niêm yết", "lên sàn", "ipo", "chào sàn"]):
        await update.message.reply_text("🔍 Đang quét thông tin doanh nghiệp/cổ phiếu chuẩn bị lên sàn...")
        result = await asyncio.to_thread(get_upcoming_listings_report)
        await update.message.reply_text(result)
        
    elif "thị trường" in clean_text or "cập nhật" in clean_text:
        await update.message.reply_text("📊 Đang quét dữ liệu toàn thị trường...")
        result = await asyncio.to_thread(get_daily_report, "evening")
        await update.message.reply_text(result)
        
    elif re.match(r'^[a-zA-Z]{3,4}$', user_text):
        symbol = user_text.upper()
        await update.message.reply_text(f"🔍 Đang truy xuất VSA & Tin tức cho mã {symbol}...")
        result = await asyncio.to_thread(analyze_vsa_and_news, symbol)
        await update.message.reply_text(result)

async def post_init(application):
    asyncio.create_task(auto_background_worker(application))

# ==========================================
# 5. KHỞI CHẠY BOT DẠNG BẤT ĐỒNG BỘ CHUẨN
# ==========================================
if __name__ == '__main__':
    app = ApplicationBuilder().token(TELEGRAM_TOKEN).post_init(post_init).build()
    
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("niemyet", upcoming_listings_command))
    app.add_handler(CommandHandler("ipo", upcoming_listings_command))
    app.add_handler(CommandHandler("canhbao", trigger_scan_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    
    print("🚀 Bot VSA Telegram đang chạy...")
    app.run_polling(drop_pending_updates=True)
