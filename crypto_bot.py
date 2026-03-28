import os
import asyncio
import logging
import pandas as pd
import pandas_ta as ta
import ccxt.async_support as ccxt
from datetime import datetime, timedelta
from telegram.ext import Application, CommandHandler, ContextTypes

BOT_TOKEN = os.getenv("8682468007:AAEZcluqk6rgkLjVkaYEA-paJxlwnmsU59o")
CHAT_ID = os.getenv("7550540182")
if not BOT_TOKEN or not CHAT_ID:
    raise Exception("请设置环境变量 BOT_TOKEN 和 CHAT_ID")

EXCHANGE = ccxt.binance({'enableRateLimit': True})
user_pairs = []
signal_log = {}

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def calculate_indicators(df):
    df['rsi'] = ta.rsi(df['close'], length=14)
    df['volume_ma'] = df['volume'].rolling(20).mean()
    df['volume_ratio'] = df['volume'] / df['volume_ma']
    bbands = ta.bbands(df['close'], length=20, std=2)
    df['bb_upper'] = bbands['BBU_20_2.0']
    df['bb_lower'] = bbands['BBL_20_2.0']
    df['ema20'] = ta.ema(df['close'], length=20)
    df['ema50'] = ta.ema(df['close'], length=50)
    return df

def generate_signals(df):
    if df.empty or len(df) < 50:
        return []
    signals = []
    last = df.iloc[-1]
    prev = df.iloc[-2] if len(df) > 1 else last
    rsi = last['rsi']
    vol_ratio = last['volume_ratio']
    close = last['close']
    bb_upper = last['bb_upper']
    bb_lower = last['bb_lower']
    ema20 = last['ema20']
    ema50 = last['ema50']
    is_uptrend = close > ema20 and ema20 > ema50
    is_downtrend = close < ema20 and ema20 < ema50
    if not is_uptrend and not is_downtrend:
        return signals
    if is_uptrend and rsi < 30 and vol_ratio > 1.3:
        signals.append({"type": "BUY", "reason": f"RSI超卖({rsi:.1f})+放量({vol_ratio:.1f}x)"})
    if is_downtrend and rsi > 70 and vol_ratio > 1.3:
        signals.append({"type": "SELL", "reason": f"RSI超买({rsi:.1f})+放量({vol_ratio:.1f}x)"})
    return signals

async def analyze_and_notify(symbol, timeframe):
    try:
        ohlcv = await EXCHANGE.fetch_ohlcv(symbol, timeframe, limit=200)
        if not ohlcv:
            return
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        df = calculate_indicators(df)
        signals = generate_signals(df)
        if not signals:
            return
        close_now = df.iloc[-1]['close']
        close_prev = df.iloc[-2]['close'] if len(df) > 1 else close_now
        change_pct = (close_now - close_prev) / close_prev * 100
        change_str = f"{'+' if change_pct >= 0 else ''}{change_pct:.2f}%"
        now = datetime.now()
        for sig in signals:
            key = f"{symbol}_{sig['type']}"
            last_time = signal_log.get(key)
            if last_time and (now - last_time) < timedelta(hours=1):
                continue
            msg = (
                f"🚨 *{sig['type']} 信号*\n"
                f"交易对: `{symbol}`\n"
                f"周期: {timeframe}\n"
                f"当前价: {close_now:.2f} ({change_str})\n"
                f"原因: {sig['reason']}\n"
                f"时间: {now.strftime('%m-%d %H:%M:%S')}"
            )
            await application.bot.send_message(chat_id=CHAT_ID, text=msg, parse_mode='Markdown')
            signal_log[key] = now
    except Exception as e:
        logger.error(f"分析 {symbol} 出错: {e}")

async def scheduled_analysis(context: ContextTypes.DEFAULT_TYPE):
    for pair in user_pairs:
        if pair.get("enabled", True):
            await analyze_and_notify(pair["symbol"], pair["timeframe"])

async def start(update, context):
    await update.message.reply_text("🤖 机器人已启动！\n/addpair BTC/USDT 1h 添加监控")

async def add_pair(update, context):
    args = context.args
    if len(args) < 2:
        await update.message.reply_text("用法: /addpair BTC/USDT 1h")
        return
    symbol = args[0].upper()
    tf = args[1].lower()
    if tf not in ['15m', '1h', '4h', '1d']:
        await update.message.reply_text("周期须为 15m/1h/4h/1d")
        return
    user_pairs.append({"symbol": symbol, "timeframe": tf, "enabled": True})
    await update.message.reply_text(f"✅ 已添加 {symbol} ({tf})")

async def remove_pair(update, context):
    if len(context.args) < 1:
        await update.message.reply_text("用法: /removepair BTC/USDT")
        return
    symbol = context.args[0].upper()
    global user_pairs
    user_pairs = [p for p in user_pairs if p['symbol'] != symbol]
    await update.message.reply_text(f"✅ 已移除 {symbol}")

async def list_pairs(update, context):
    if not user_pairs:
        await update.message.reply_text("暂无监控")
        return
    text = "📊 监控列表：\n" + "\n".join([f"{'✅' if p['enabled'] else '⛔'} {p['symbol']} ({p['timeframe']})" for p in user_pairs])
    await update.message.reply_text(text)

async def toggle_pair(update, context):
    if len(context.args) < 1:
        await update.message.reply_text("用法: /toggle BTC/USDT")
        return
    symbol = context.args[0].upper()
    for p in user_pairs:
        if p['symbol'] == symbol:
            p['enabled'] = not p['enabled']
            await update.message.reply_text(f"{symbol} 已{'启用' if p['enabled'] else '禁用'}")
            return
    await update.message.reply_text("未找到")

async def help_command(update, context):
    await update.message.reply_text("/addpair <交易对> <周期>\n/removepair <交易对>\n/listpairs\n/toggle <交易对>")

async def main():
    global application
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("addpair", add_pair))
    application.add_handler(CommandHandler("removepair", remove_pair))
    application.add_handler(CommandHandler("listpairs", list_pairs))
    application.add_handler(CommandHandler("toggle", toggle_pair))
    application.add_handler(CommandHandler("help", help_command))
    job_queue = application.job_queue
    if job_queue:
        job_queue.run_repeating(scheduled_analysis, interval=120, first=10)
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    logger.info("机器人已启动")
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
