#!/usr/bin/env python3
"""
XRP Trading Bot v1 — реальная торговля
Стратегия: 5m L12 Breakout · TP +2% / SL -5% · Position sizing

Config via env vars: BOT_TOKEN, CHAT_ID, API_KEY
"""
import ccxt, requests, time, json
import os
from datetime import datetime, timedelta
from pathlib import Path

# ===== КОНФИГ =====
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
API_KEY = os.environ.get("API_KEY", "")
SECRET = "66221499e1cc48a79de0e3b1eaaae26b"
SYMBOL = "XRP/USDT:USDT"
TF = '1m'
LOOKBACK = 12
VOL_MULT = 1.2
COOLDOWN_BARS = 3
TP_PCT = 0.5       # +0.5% профит
SL_PCT = 1.5       # -1.5% стоп
LEVERAGE = 10
FIXED_QTY = 40  # фиксированное количество контрактов
STATE_FILE = Path(__file__).parent / "bot_state.json"

class XRPBot:
    def __init__(self):
        self.ex = ccxt.mexc({
            'apiKey': API_KEY,
            'secret': SECRET,
            'enableRateLimit': True,
            'options': {'defaultType': 'swap'}
        })
        self.ex.load_markets()
        try:
            self.ex.set_leverage(LEVERAGE, SYMBOL, {'openType': 2, 'positionType': 2})
        except:
            pass

        self.state = self._load()
        self.running = False
        self.offset = 0
        self.last_candle_ts = 0
        self.last_signal_bar = -999

        self.log("🤖 XRP Бот запущен")

    def _load(self):
        d = {"trades": [], "date": "", "day_trades": 0, "day_wins": 0,
             "day_losses": 0, "day_pnl": 0.0, "paused_until": 0, "sl_streak": 0,
             "balance_start": 0, "total_pnl": 0.0, "active": None}
        if STATE_FILE.exists():
            try:
                s = json.loads(STATE_FILE.read_text())
                d.update({k: s[k] for k in d if k in s})
            except:
                pass
        return d

    def _save(self):
        STATE_FILE.write_text(json.dumps(self.state, default=str, indent=2))

    def log(self, msg):
        ts = datetime.now().strftime('%H:%M:%S')
        print(f"[{ts}] {msg}", flush=True)

    def tg(self, text, kb=None):
        try:
            data = {'chat_id': CHAT_ID, 'text': text, 'parse_mode': 'Markdown'}
            if kb:
                data['reply_markup'] = kb
            requests.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                         json=data, timeout=10)
        except Exception as e:
            self.log(f"TG err: {e}")

    def _balance(self):
        try:
            b = self.ex.fetch_balance()
            u = b.get('USDT', {})
            return float(u.get('free', 0)), float(u.get('total', 0))
        except:
            return 0, 0

    def _position(self):
        try:
            pos = self.ex.fetch_positions([SYMBOL])
            for p in pos:
                if float(p.get('contracts', 0) or 0) > 0:
                    return p
            return None
        except:
            return None

    def _calc_qty(self, price):
        return FIXED_QTY

    def _check_new_day(self):
        today = datetime.utcnow().strftime('%Y-%m-%d')
        if self.state['date'] != today:
            if self.state['day_trades'] > 0:
                self.tg(f"📊 *День {self.state['date']}*\n"
                       f"Сделок: {self.state['day_trades']}\n"
                       f"✅ {self.state['day_wins']} ❌ {self.state['day_losses']}\n"
                       f"💰 ${self.state['day_pnl']:+.2f}")
            self.state['date'] = today
            self.state['day_trades'] = 0
            self.state['day_wins'] = 0
            self.state['day_losses'] = 0
            self.state['day_pnl'] = 0.0
            self._save()

    def _pause_until(self, sl_time):
        pause_12h = sl_time + timedelta(hours=12)
        nxt = sl_time.replace(hour=8, minute=0, second=0, microsecond=0)
        if sl_time >= nxt:
            nxt += timedelta(days=1)
        return max(pause_12h, nxt)

    def _handle_buttons(self):
        try:
            r = requests.get(
                f"https://api.telegram.org/bot{BOT_TOKEN}/getUpdates",
                params={'timeout': 3, 'offset': self.offset},
                timeout=10
            )
            if not r.ok:
                return
            for u in r.json().get('result', []):
                self.offset = u['update_id'] + 1
                cb = u.get('callback_query', {})
                if cb:
                    data = cb['data']
                    if data == 'start':
                        self.running = True
                        self.log("▶️ Старт")
                        self.tg("✅ *XRP Бот запущен*")
                    elif data == 'stop':
                        self.running = False
                        self.log("⏹️ Стоп")
                        self.tg("⏹️ *XRP Бот остановлен*")
                    elif data == 'status':
                        free, total = self._balance()
                        pos = self._position()
                        status = "🟢 В позиции" if pos else "⚪ Ожидание"
                        paused = "⏸ Пауза" if self.state['paused_until'] > time.time() else "✅ Активен"
                        self.tg(f"📊 *XRP Статус*\n"
                               f"💼 ${total:.2f}\n"
                               f"{status}\n{paused}\n"
                               f"Сегодня: {self.state['day_trades']} сделок, ${self.state['day_pnl']:+.2f}")
                    requests.post(
                        f"https://api.telegram.org/bot{BOT_TOKEN}/answerCallbackQuery",
                        json={'callback_query_id': cb['id'], 'text': '✅'},
                        timeout=3
                    )
        except Exception as e:
            self.log(f"Buttons: {e}")

    def _check_tp_sl(self, price, entry):
        """Проверяем TP/SL в %"""
        direction = entry.get('direction', 'LONG')
        entry_price = entry['entry']

        if direction == 'LONG':
            pct = (price - entry_price) / entry_price * 100
            if pct >= TP_PCT:
                return 'TP'
            if pct <= -SL_PCT:
                return 'SL'
        else:
            pct = (entry_price - price) / entry_price * 100
            if pct >= TP_PCT:
                return 'TP'
            if pct <= -SL_PCT:
                return 'SL'

        return None

    def _enter_trade(self, direction, entry_price):
        qty = self._calc_qty(entry_price)
        side = 'buy' if direction == 'LONG' else 'sell'

        try:
            order = self.ex.create_order(SYMBOL, 'market', side, qty)
            self.log(f"📩 {direction} {qty} @ ${entry_price:.4f}")
        except Exception as e:
            self.log(f"❌ Entry err: {e}")
            return False

        time.sleep(1)

        # Ставим TP лимитником (reduceOnly)
        close_side = 'sell' if direction == 'LONG' else 'buy'
        tp_price = round(entry_price * (1 + TP_PCT/100), 4) if direction == 'LONG' else round(entry_price * (1 - TP_PCT/100), 4)

        try:
            tp_order = self.ex.create_order(SYMBOL, 'limit', close_side, qty, tp_price,
                                            params={'reduceOnly': True})
            self.log(f"🎯 TP @ ${tp_price}")
        except Exception as e:
            self.log(f"⚠️ TP err: {e}")

        # Запоминаем
        self.state['active'] = {
            'direction': direction,
            'entry': entry_price,
            'tp': tp_price,
            'qty': qty,
            'time': datetime.utcnow().isoformat()
        }
        self._save()

        # Уведомление
        sl_price = round(entry_price * (1 - SL_PCT/100), 4) if direction == 'LONG' else round(entry_price * (1 + SL_PCT/100), 4)
        tp_dollar = abs(tp_price - entry_price) * qty
        sl_dollar = abs(entry_price - sl_price) * qty
        emoji = '🟢' if direction == 'LONG' else '🔴'
        self.tg(f"{emoji} *XRP {direction}* {qty}x\n"
               f"💰 Вход: ${entry_price:.4f}\n"
               f"🎯 TP: ${tp_price:.4f} (+${tp_dollar:.2f})\n"
               f"🛑 SL: ${sl_price:.4f} (-${sl_dollar:.2f})\n"
               f"💼 ${self._balance()[1]:.1f}")

        return True

    def _close_trade(self, reason, price):
        if not self.state.get('active'):
            return

        pos = self._position()
        if pos:
            close_side = 'sell' if pos.get('side') == 'long' else 'buy'
            try:
                orders = self.ex.fetch_open_orders(SYMBOL)
                for o in orders:
                    try:
                        self.ex.cancel_order(o['id'], SYMBOL)
                    except:
                        pass
                self.ex.create_order(SYMBOL, 'market', close_side, abs(float(pos['contracts'])),
                                    params={'reduceOnly': True})
                self.log(f"🔒 {reason}")
            except Exception as e:
                self.log(f"❌ Close err: {e}")

        entry = self.state['active'].get('entry', 0)
        qty = self.state['active'].get('qty', 1)
        delta = (price - entry) * qty if self.state['active'].get('direction') == 'LONG' else (entry - price) * qty
        is_win = (reason == 'TP')

        self.state['day_trades'] += 1
        self.state['total_pnl'] = self.state.get('total_pnl', 0) + delta
        self.state['day_pnl'] += delta

        if is_win:
            self.state['day_wins'] += 1
            self.state['sl_streak'] = 0
        else:
            self.state['day_losses'] += 1
            self.state['sl_streak'] += 1

        self.state['trades'].append({
            'time': datetime.utcnow().isoformat(),
            'direction': self.state['active']['direction'],
            'entry': entry,
            'exit': price,
            'qty': qty,
            'pnl': round(delta, 2),
            'result': reason
        })

        if reason == 'SL':
            sl_time = datetime.utcnow()
            pu = self._pause_until(sl_time)
            self.state['paused_until'] = pu.timestamp()
            self.tg(f"⏸ *SL!* Пауза до {pu.strftime('%m-%d %H:%M')} UTC")
            self.state.pop('daily_pnl_reset', None)
            self.log(f"⏸ Пауза до {pu.strftime('%m-%d %H:%M')} UTC")

        self.state['active'] = None
        self._save()

        emoji = '✅' if is_win else '❌'
        self.tg(f"{emoji} *XRP {reason}* — ${delta:+.2f}\n"
               f"💼 ${self._balance()[1]:.1f}")

    def _scan(self):
        now = datetime.utcnow()

        if self.state.get('paused_until', 0) > time.time():
            return

        self._check_new_day()

        try:
            candles = self.ex.fetch_ohlcv(SYMBOL, TF, limit=40)
        except Exception as e:
            self.log(f"Fetch err: {e}")
            return

        if len(candles) < LOOKBACK + 10:
            return

        # Проверяем новая ли свеча (по timestamp последней закрытой)
        last_ts = candles[-1][0]  # timestamp последней свечи (ещё формируется)
        if last_ts == self.last_candle_ts:
            return
        self.last_candle_ts = last_ts
        
        # Используем предпоследнюю свечу (уже закрыта) для анализа
        check_idx = -2
        ts_check = datetime.utcfromtimestamp(candles[check_idx][0] / 1000)
        self.log(f"Проверка {ts_check.strftime('%H:%M')} {candles[check_idx][4]:.4f}")

        closes = [x[4] for x in candles[:check_idx+1]]
        highs = [x[2] for x in candles[:check_idx+1]]
        lows = [x[3] for x in candles[:check_idx+1]]
        vols = [x[5] for x in candles[:check_idx+1]]
        current_price = candles[check_idx][4]

        candle_time = datetime.utcfromtimestamp(candles[check_idx][0] / 1000)

        # Проверяем, есть ли позиция на бирже (чтобы не открывать новую)
        pos = self._position()
        if pos:
            return
        if self.state.get('active'):
            # Монитор уже должен был обработать, но на всякий случай
            self.log("⚠️ active есть, позиции нет — очищаю")
            self.state['active'] = None
            self._save()
            return

        # Сигнал: Breakout L12 + Volume
        hh = max(highs[-(LOOKBACK+1):-1])
        ll = min(lows[-(LOOKBACK+1):-1])

        avg_v = sum(vols[-20:-1]) / 19 if len(vols) > 20 else 0
        vr = vols[-1] / avg_v if avg_v > 0 else 0

        bar_num = int(last_ts / 1000 / 300)

        if current_price > hh and vr > VOL_MULT and (bar_num - self.last_signal_bar) >= COOLDOWN_BARS:
            self.last_signal_bar = bar_num
            self._enter_trade('LONG', current_price)
            return

        elif current_price < ll and vr > VOL_MULT and (bar_num - self.last_signal_bar) >= COOLDOWN_BARS:
            self.last_signal_bar = bar_num
            self._enter_trade('SHORT', current_price)
            return

    def _monitor(self):
        """Всегда активный мониторинг: SL/TP + проверка позиции"""
        active = self.state.get('active')
        if not active:
            return

        try:
            candles = self.ex.fetch_ohlcv(SYMBOL, TF, limit=3)
            if len(candles) < 2:
                return
            current_price = candles[-1][4]
        except:
            return

        entry_price = active['entry']
        direction = active.get('direction', 'LONG')

        # Проверка TP/SL
        result = self._check_tp_sl(current_price, active)
        if result:
            self._close_trade(result, current_price)
            return

        # Если active есть, а позиции на бирже нет — фиксируем закрытие
        try:
            pos = self._position()
        except:
            return
        if not pos:
            qty = active.get('qty', 1)
            delta = (current_price - entry_price) * qty if direction == 'LONG' else (entry_price - current_price) * qty
            is_win = delta > 0
            self.state['day_trades'] += 1
            self.state['total_pnl'] = self.state.get('total_pnl', 0) + delta
            self.state['day_pnl'] = self.state.get('day_pnl', 0) + delta
            if is_win:
                self.state['day_wins'] += 1
                self.state['sl_streak'] = 0
            else:
                self.state['day_losses'] += 1
                self.state['sl_streak'] += 1
            reason = 'TP' if is_win else 'SL'
            self.state['trades'].append({
                'time': datetime.utcnow().isoformat(),
                'direction': direction,
                'entry': entry_price,
                'exit': current_price,
                'qty': qty,
                'pnl': round(delta, 2),
                'result': reason
            })
            self.state['active'] = None
            self._save()
            emoji = '✅' if is_win else '❌'
            self.log(f"🔒 {direction} {reason}: ${entry_price:.4f} → ${current_price:.4f} ${delta:+.2f}")

    def run(self):
        kb = {
            'inline_keyboard': [
                [
                    {'text': '▶️ Старт', 'callback_data': 'start'},
                    {'text': '⏹️ Стоп', 'callback_data': 'stop'},
                    {'text': '📊 Статус', 'callback_data': 'status'},
                ]
            ]
        }
        balance = self._balance()[1]
        self.tg(f"🤖 *XRP Trading Bot v2*\n"
               f"TP +{TP_PCT}% · SL -{SL_PCT}% · L12 Breakout\n"
               f"Контрактов: {FIXED_QTY}\n"
               f"💼 ${balance:.2f}", kb=kb)

        self.log(f"🚀 XRP Bot запущен | Баланс ${balance:.2f}")

        # При старте сразу проверяем активную позицию
        if self.state.get('active'):
            self.log("📋 Обнаружена активная позиция при запуске, мониторинг активен")
            self.tg("📋 *Позиция восстановлена*, SL/TP мониторинг активен")

        while True:
            try:
                self._handle_buttons()

                # SL/TP мониторинг — ВСЕГДА, независимо от running
                self._monitor()

                if self.running:
                    self._scan()

                    now = datetime.utcnow()
                    if now.minute == 0 and now.second < 5:
                        free, total = self._balance()
                        pos = self._position()
                        status = "🟢" if pos else "⚪"
                        paused = "⏸" if self.state['paused_until'] > time.time() else ""
                        self.log(f"💼 ${total:.2f} {status}{paused} | "
                                f"день: {self.state['day_trades']}сд ${self.state['day_pnl']:+.2f}")

                time.sleep(5)

            except KeyboardInterrupt:
                self.log("⏹️ Остановлен")
                break
            except Exception as e:
                self.log(f"❌ Ошибка: {e}")
                time.sleep(10)

if __name__ == "__main__":
    XRPBot().run()
