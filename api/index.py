import os
import json
import re
import time
from datetime import datetime, timezone, timedelta
import threading
import base64
import hashlib
import hmac
import urllib.request
import urllib.parse
import urllib.error
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from groq import Groq
from treys import Card, Evaluator
from supabase import create_client, Client

app = FastAPI()

app.add_middleware(CORSMiddleware,
allow_origins=["*"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],)

try:
	groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"), timeout=60.0, max_retries=2)
	supabase: Client = create_client(os.environ.get("SUPABASE_URL"),
									 os.environ.get("SUPABASE_SERVICE_KEY"),)
	evaluator = Evaluator()
	startup_ok = True
	startup_error = ""
except Exception as exc:
	startup_ok = False
	startup_error = str(exc)

GROQ_MODELS = ["openai/gpt-oss-120b", "openai/gpt-oss-20b", "llama-3.3-70b-versatile"]

def groq_ask(messages, tools=None, tool_choice=None):
	last_err = None
	for model in GROQ_MODELS:
		for attempt in range(2):
			try:
				kwargs = {"model": model, "messages": messages}
				if tools is not None:
					kwargs["tools"] = tools
					kwargs["tool_choice"] = tool_choice
				return groq_client.chat.completions.create(**kwargs)
			except Exception as e:
				last_err = e
				code = getattr(e, "status_code", 0)
				if code in (429, 500, 502, 503, 504) or "rate limit" in str(e).lower():
					time.sleep(0.6 * (attempt + 1))
					continue
				break
	raise last_err

GROQ_VISION_MODELS = ["qwen/qwen3.8-27b", "qwen/qwen3.6-27b", "meta-llama/llama-4-scout-17b-16e-instruct", "llama-3.2-90b-vision-preview", "llama-3.2-11b-vision-preview"]

def groq_vision_text(image_b64, prompt, mime="image/jpeg"):
	models = []
	env_m = os.environ.get("GROQ_VISION_MODEL", "").strip()
	if env_m:
		models.append(env_m)
	models += GROQ_VISION_MODELS
	last_err = None
	for model in models:
		try:
			msg = {"role": "user", "content": [
				{"type": "text", "text": prompt},
				{"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
			]}
			resp = groq_client.chat.completions.create(model=model, messages=[msg], max_tokens=4000)
			return resp.choices[0].message.content or ""
		except Exception as e:
			last_err = e
			code = getattr(e, "status_code", 0)
			low = str(e).lower()
			if code in (429, 500, 502, 503, 504) or "rate limit" in low:
				time.sleep(0.6)
				continue
			if code == 400 and any(k in low for k in ("vision", "image", "model", "modality", "content type", "not support")):
				continue
			break
	raise last_err

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
DISCORD_SUPPORT_WEBHOOK_URL = os.environ.get("DISCORD_SUPPORT_WEBHOOK_URL")
USER_AGENT = "AIHoldemCoach (https://aiholdemcoach.com, v1.0)"

CHAT_DAILY_LIMIT = int(os.environ.get("CHAT_DAILY_LIMIT", "300"))
CHAT_GLOBAL_DAILY_LIMIT = int(os.environ.get("CHAT_GLOBAL_DAILY_LIMIT", "3000"))
CHAT_WHITELIST = {e.strip().lower() for e in os.environ.get("CHAT_WHITELIST", "").split(",") if e.strip()}
FREE_COACH_LIMIT = int(os.environ.get("FREE_COACH_LIMIT", "5"))
FREE_TRACK_LIMIT = int(os.environ.get("FREE_TRACK_LIMIT", "10"))
FREE_HISTORY_DAYS = int(os.environ.get("FREE_HISTORY_DAYS", "30"))
TRIAL_DAYS = int(os.environ.get("TRIAL_DAYS", "7"))
GRANDFATHER_MONTHS = int(os.environ.get("GRANDFATHER_MONTHS", "6"))
ADMIN_EMAILS = {e.strip().lower() for e in os.environ.get("ADMIN_EMAILS", "").split(",") if e.strip()}
APP_URL = os.environ.get("APP_URL", "https://aiholdemcoach.vercel.app")
STRIPE_SECRET_KEY = os.environ.get("STRIPE_SECRET_KEY", "")
STRIPE_WEBHOOK_SECRET = os.environ.get("STRIPE_WEBHOOK_SECRET", "")
STRIPE_PRO_PRICE = os.environ.get("STRIPE_PRO_PRICE", "")
STRIPE_PREMIUM_PRICE = os.environ.get("STRIPE_PREMIUM_PRICE", "")
USAGE_SENTINEL_GLOBAL = "00000000-0000-0000-0000-000000000000"
USAGE_SENTINEL_ANON = "ffffffff-ffff-ffff-ffff-ffffffffffff"
_usage_gate_warned = False

PLAN_LIMITS = {
    "free": {"coach": FREE_COACH_LIMIT, "track": FREE_TRACK_LIMIT, "history_days": FREE_HISTORY_DAYS, "recap": True, "recap_daily": 1, "import": False},
    "pro": {"coach": 0, "track": 0, "history_days": 0, "recap": True, "recap_daily": 0, "import": True},
    "premium": {"coach": 0, "track": 0, "history_days": 0, "recap": True, "recap_daily": 0, "import": True},
    "legacy": {"coach": 0, "track": 0, "history_days": 0, "recap": True, "recap_daily": 0, "import": True},
    "admin": {"coach": 0, "track": 0, "history_days": 0, "recap": True, "recap_daily": 0, "import": True},
}

def check_chat_quota(user_email, user_id, mode="chat", ent=None):
	global _usage_gate_warned
	if ent and ent.get("tier") == "admin":
		if not user_id:
			pass
		return None
	if user_email and user_email.lower() in CHAT_WHITELIST:
		return None
	u = user_id or USAGE_SENTINEL_ANON
	try:
		res = supabase.rpc("bump_chat_usage", {
			"p_day": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
			"p_user": u,
			"p_global": USAGE_SENTINEL_GLOBAL,
			"p_mode": "track" if mode == "session" else ("chat" if mode not in ("coach", "track", "recap") else mode),
		}).execute()
	except Exception as exc:
		if not _usage_gate_warned:
			_usage_gate_warned = True
			discord_ping(f"Usage gate not installed (run schema.sql v4 block): {exc}")
		return None
	rows = res.data if isinstance(res.data, list) else ([res.data] if res.data else [])
	row = rows[0] if rows else {}
	g_count = row.get("g_chats") or row.get("g_count") or 0
	if g_count > CHAT_GLOBAL_DAILY_LIMIT:
		return "Coach is at capacity for today. Try again tomorrow!"
	if not ent or ent.get("tier") != "free":
		return None
	limits = ent.get("limits") or {}
	if mode == "recap" and limits.get("recap_daily"):
		if (row.get("u_recap") or 0) > limits["recap_daily"]:
			return f"You've used your {limits['recap_daily']} free recap{'s' if limits['recap_daily'] != 1 else ''} for today. Upgrade to Pro for unlimited recaps, or come back tomorrow!"
	if mode == "coach" and limits.get("coach"):
		if (row.get("u_coach") or 0) > limits["coach"]:
			return f"You've used your {limits['coach']} daily coach chats on the Free plan. Upgrade to Pro for unlimited coaching, recap, and import."
	if mode in ("track", "session") and limits.get("track"):
		if (row.get("u_track") or 0) > limits["track"]:
			return f"You've used your {limits['track']} daily tracked hands on the Free plan. Upgrade to Pro for unlimited tracking."
	return None

def _parse_ts(value):
	if isinstance(value, (int, float)):
		return datetime.fromtimestamp(float(value), timezone.utc)
	if not value:
		return None
	try:
		return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
	except Exception:
		return None

def entitlement(user_id, user_email=None):
	if user_id and user_email and user_email.lower() in ADMIN_EMAILS:
		return {"tier": "admin", "plan": "admin", "limits": tier_limits("admin"), "trial": {"active": False, "days_left": 0, "ended": False}}
	sub = None
	if user_id:
		try:
			r = supabase.table("subscriptions").select("tier,status,current_period_end,stripe_subscription_id,stripe_customer_id").eq("user_id", user_id).execute()
			if r.data:
				sub = r.data[0]
		except Exception:
			sub = None
	if sub:
		status = sub.get("status")
		stripe_tier = sub.get("tier")
		if stripe_tier in ("pro", "premium", "legacy") and status in ("active", "trial", "legacy"):
			expired = False
			if sub.get("current_period_end"):
				pe = _parse_ts(sub["current_period_end"])
				if pe is not None and pe < datetime.now(timezone.utc) - timedelta(days=1):
					expired = True
			if not expired:
				return {"tier": stripe_tier, "plan": stripe_tier, "limits": tier_limits(stripe_tier), "subscription": sub, "trial": {"active": False, "days_left": 0, "ended": False}}
		return {"tier": "free", "plan": "free", "limits": tier_limits("free"), "subscription": sub, "trial": {"active": False, "days_left": 0, "ended": False}}
	created_at = None
	if user_id:
		try:
			r = supabase.table("profiles").select("created_at").eq("user_id", user_id).execute()
			if r.data and r.data[0].get("created_at"):
				created_at = r.data[0]["created_at"]
		except Exception:
			created_at = None
		if not created_at:
			try:
				u = supabase.auth.admin.get_user_by_id(user_id)
				uu = getattr(u, "user", None)
				created_at = getattr(uu, "created_at", None) if uu else None
			except Exception:
				created_at = None
	if created_at:
		age = None
		ts = _parse_ts(created_at)
		if ts is not None:
			age = (datetime.now(timezone.utc) - ts).days
		if age is not None and age < TRIAL_DAYS:
			return {"tier": "pro", "plan": "trial", "limits": tier_limits("pro"), "trial": {"active": True, "days_left": max(0, TRIAL_DAYS - age), "ended": False}}
	return {"tier": "free", "plan": "free", "limits": tier_limits("free"), "trial": {"active": False, "days_left": 0, "ended": created_at is not None and age is not None and age >= TRIAL_DAYS}}

def tier_limits(tier):
	return PLAN_LIMITS.get(tier, PLAN_LIMITS["free"])

def auth_identity(req):
	auth_header = req.headers.get("authorization", "")
	if not auth_header.startswith("Bearer "):
		return None, None
	token = auth_header[7:]
	try:
		resp = supabase.auth.get_user(token)
		if resp and resp.user:
			return resp.user.id, resp.user.email
	except Exception:
		pass
	return None, None

def upsert_subscription(user_id, tier, status, period_end=None, sub_id=None, customer_id=None):
	row = {"user_id": user_id, "tier": tier, "status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
	if period_end:
		row["current_period_end"] = period_end
	if sub_id:
		row["stripe_subscription_id"] = sub_id
	if customer_id:
		row["stripe_customer_id"] = customer_id
	try:
		supabase.table("subscriptions").upsert(row, on_conflict="user_id").execute()
		return True
	except Exception as exc:
		discord_ping(f"upsert_subscription: {exc}")
		return False

def find_user_by_subscription(sub_id):
	try:
		r = supabase.table("subscriptions").select("user_id").eq("stripe_subscription_id", sub_id).execute()
		if r.data:
			return r.data[0]["user_id"]
	except Exception:
		pass
	return None

def stripe_api(method, path, payload=None, form=False, with_api_key=True):
	if not STRIPE_SECRET_KEY:
		return {"error": "Billing is not set up yet — come back soon."}
	headers = {}
	data = None
	if payload is not None:
		if form:
			data = urllib.parse.urlencode(payload).encode()
			headers["Content-Type"] = "application/x-www-form-urlencoded"
		else:
			data = json.dumps(payload).encode()
			headers["Content-Type"] = "application/json"
	req = urllib.request.Request("https://api.stripe.com/v1/" + path, data=data, method=method, headers=headers)
	req.add_header("Authorization", "Basic " + base64.b64encode((STRIPE_SECRET_KEY + ":").encode()).decode())
	try:
		with urllib.request.urlopen(req, timeout=20) as res:
			return json.loads(res.read().decode())
	except urllib.error.HTTPError as e:
		body = e.read().decode()
		try:
			err = json.loads(body)
			msg = (err.get("error") or {}).get("message") or "Billing error"
			return {"error": msg}
		except Exception:
			return {"error": body[:300]}
	except Exception as exc:
		return {"error": str(exc)}

def verify_stripe_signature(payload, signature):
	if not signature:
		return False
	try:
		parts = {}
		for item in signature.split(","):
			if "=" in item:
				k, v = item.split("=", 1)
				parts[k] = v
		ts = parts.get("t", "")
		expected = parts.get("v1", "")
		signed = (ts + "." + payload.decode()).encode()
		digest = hmac.new(STRIPE_WEBHOOK_SECRET.encode(), signed, hashlib.sha256).hexdigest()
		return hmac.compare_digest(digest, expected)
	except Exception:
		return False

def discord_ping(text):
	if not DISCORD_WEBHOOK_URL:
		return
	def send():
		try:
			payload = json.dumps({"content": text}).encode()
			req = urllib.request.Request(DISCORD_WEBHOOK_URL, data=payload, headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
			urllib.request.urlopen(req, timeout=5)
		except Exception:
			pass
	threading.Thread(target=send, daemon=True).start()

if startup_ok is False:
	discord_ping(f"Startup failed: {startup_error}")

def evaluate_poker_hand(hero_cards, board_cards):
	hero = [Card.new(c) for c in hero_cards]
	board = [Card.new(c) for c in board_cards]
	score = evaluator.evaluate(board, hero)
	rank = evaluator.class_to_string(evaluator.get_rank_class(score))
	return json.dumps({"score": score, "hand_rank": rank})

RANKS = "23456789TJQKA"
RANK_VALUES = {r: i for i, r in enumerate(RANKS, start=2)}
TIER_1 = {"AA", "KK", "QQ", "JJ", "AKs", "AKo"}
TIER_2 = {"TT", "99", "88", "AQs", "AJs", "ATs", "KQs", "KJs", "AQo"}
TIER_3 = {"77", "66", "A9s", "A8s", "A7s", "A6s", "A5s", "A4s", "A3s", "A2s", "KTs", "QJs", "QTs", "JTs", "T9s", "98s", "87s", "AJo", "KQo", "KJo"}
TIER_4 = {"55", "44", "33", "22", "K9s", "Q9s", "J9s", "T8s", "97s", "86s", "76s", "65s", "54s", "ATo", "KTo", "QTo", "JTo", "QJo"}
TIER_NAMES = {1: "Premium", 2: "Strong", 3: "Playable", 4: "Speculative", 5: "Trash"}

def to_canonical(card1, card2):
	if len(card1) == 1: card1 = card1 + "h"
	if len(card2) == 1: card2 = card2 + "d"
	r1, s1 = card1[0].upper(), card1[1].lower()
	r2, s2 = card2[0].upper(), card2[1].lower()
	val1, val2 = RANK_VALUES[r1], RANK_VALUES[r2]
	if val1 < val2: r1, r2 = r2, r1; s1, s2 = s2, s1
	if r1 == r2: return f"{r1}{r2}"
	elif s1 == s2: return f"{r1}{r2}s"
	else: return f"{r1}{r2}o"

def get_hand_tier(hand):
	if hand in TIER_1: return 1
	elif hand in TIER_2: return 2
	elif hand in TIER_3: return 3
	elif hand in TIER_4: return 4
	return 5

def preflop_advice(card1, card2, position="BTN"):
	hand = to_canonical(card1, card2)
	tier = get_hand_tier(hand)
	pos = position.upper()
	open_thresholds = {"UTG": [1,2], "MP": [1,2], "CO": [1,2,3], "BTN": [1,2,3,4], "SB": [1,2,3,4]}
	if pos == "BB": action = "Check if unraised, defend vs one open depending on pot odds"
	elif tier in open_thresholds.get(pos, []): action = "Raise (open 2.2x-2.5x BB)"
	else: action = "Fold"
	return json.dumps({"hand": hand, "tier": TIER_NAMES[tier], "position": pos, "action": action})

def fmt_amount(v, units="dollars"):
	if v is None:
		return ""
	if units == "bb":
		return f"{v}bb"
	if units == "chips":
		f = float(v)
		return f"{int(f)} chips"
	return f"${v}"

def log_hand(hand=None, position=None, action=None, result=None, amount=None, hands=None):
	if hands:
		row0 = hands[0]
		return json.dumps({"hands": hands, "hand": row0.get("hand"), "position": row0.get("position"), "action": row0.get("action"), "result": row0.get("result"), "amount": row0.get("amount")})
	return json.dumps({"hand": hand, "position": position, "action": action, "result": result, "amount": amount})

def close_session(profit=None, cashout=None):
	return json.dumps({"closed": True, "profit": profit, "cashout": cashout})

def record_buyin(amount):
	return json.dumps({"buyin": True, "amount": amount})

def get_or_create_session(user_id, units="dollars"):
	try:
		result = supabase.table("sessions").select("id, units").eq("user_id", user_id).eq("status", "open").order("created_at", desc=True).limit(1).execute()
		if result.data and result.data[0]:
			row = result.data[0]
			if (row.get("units") or "dollars") == (units or "dollars"):
				return row["id"]
			try:
				supabase.table("sessions").update({"status": "closed"}).eq("id", row["id"]).execute()
			except Exception as exc:
				discord_ping(f"close orphan session: {exc}")
		new = supabase.table("sessions").insert({"user_id": user_id, "units": units or "dollars"}).execute()
		if new.data and new.data[0]:
			return new.data[0]["id"]
	except Exception as exc:
		discord_ping(f"get_or_create_session: {exc}")
	return None

def session_buyin_total(session_id):
	if not session_id:
		return 0
	try:
		res = supabase.table("buyins").select("amount").eq("session_id", session_id).execute()
		return round(sum(r.get("amount") or 0 for r in (res.data or [])), 2)
	except Exception as exc:
		discord_ping(f"session_buyin_total: {exc}")
		return 0

tools = [
{"type": "function", "function": {"name": "evaluate_poker_hand", "description": "Evaluate a poker hand from hole cards and board cards.", "parameters": {"type": "object", "properties": {"hero_cards": {"type": "array", "items": {"type": "string"}}, "board_cards": {"type": "array", "items": {"type": "string"}}}, "required": ["hero_cards", "board_cards"]}}},
{"type": "function", "function": {"name": "preflop_advice", "description": "Get preflop strategy for two hole cards.", "parameters": {"type": "object", "properties": {"card1": {"type": "string"}, "card2": {"type": "string"}, "position": {"type": ["string", "null"], "description": "UTG, MP, CO, BTN, SB, BB."}}, "required": ["card1", "card2"]}}},
{"type": "function", "function": {"name": "log_hand", "description": "Log a poker hand with action and optional result. If the player's message contains MULTIPLE hands (e.g. 'won AKo, then lost 77'), put ALL of them in the hands array at once - one object per hand. OMIT the hand/position only when the player's message gives NO hole cards - the system attaches their most recent hand.", "parameters": {"type": "object", "properties": {"hand": {"type": "string", "description": "The hand, e.g. AKo, 72s, JJ (only the ONE hand if there is only one). Leave OUT only when no hole cards were given."}, "position": {"type": ["string", "null"], "description": "Optional position"}, "action": {"type": ["string", "null"], "description": "What the player did: fold, call, raise, check, all-in"}, "result": {"type": ["string", "null"], "description": "Optional: won or lost"}, "amount": {"type": ["number", "null"], "description": "Optional: amount won or lost"}, "hands": {"type": ["array", "null"], "items": {"type": "object", "properties": {"hand": {"type": "string"}, "position": {"type": ["string", "null"]}, "action": {"type": ["string", "null"]}, "result": {"type": ["string", "null"]}, "amount": {"type": ["number", "null"]}}, "required": ["hand"]}, "description": "Multiple hands at once: one object per hand. Use this whenever the message mentions more than one hand."}}, "required": []}}} ,
{"type": "function", "function": {"name": "close_session", "description": "Close the player's session with either their total profit or loss, OR their cashout amount. If the player says they were up/down X, pass profit (positive for profit, negative for loss). If they say they cashed out X, pass cashout. Report the number exactly as the player stated it in their unit (dollars, bb, or chips) - never convert units.", "parameters": {"type": "object", "properties": {"profit": {"type": ["number", "null"], "description": "Total profit (positive) or loss (negative) in the player's unit"}, "cashout": {"type": ["number", "null"], "description": "Total amount cashed out at the end of the session in the player's unit"}}, "required": []}}},
{"type": "function", "function": {"name": "record_buyin", "description": "Record a buy-in or re-buy for the current session.", "parameters": {"type": "object", "properties": {"amount": {"type": "number", "description": "Amount of this buy-in or re-buy in the player's unit - report the number exactly as they stated it, never convert"}}, "required": ["amount"]}}},
]

available = {"evaluate_poker_hand": evaluate_poker_hand, "preflop_advice": preflop_advice, "log_hand": log_hand, "close_session": close_session, "record_buyin": record_buyin}
def get_session_context(user_id):
    try:
        result = supabase.table("messages").select("hand, position, input").eq("user_id", user_id).order("created_at", desc=True).limit(1).execute()
        if result.data and result.data[0] and result.data[0].get("hand"):
            m = result.data[0]
            return {"hand": m["hand"], "position": m.get("position", ""), "prev_input": m.get("input", "")}
    except:
        pass
    return None
coach_system = "You are a poker coach. When a player describes their hand WITH a board, use evaluate_poker_hand. When they describe ONLY hole cards, use preflop_advice. Respond in 2-3 short sentences. Talk like a friend texting from the table."

track_system = "You are a poker hand tracker. From the player's message, extract their hand, position, what they did, whether they won or lost, and how much - call log_hand with everything you find. If the message contains MORE THAN ONE hand (e.g. 'won with AKo, then lost with 77'), put EVERY hand into the hands array of a SINGLE log_hand call - one object per hand - and never skip any. Never drop a result or amount the player mentions. If they buy in or rebuy - 'bought in', 'buy-in', 'rebuy', 'loaded up', with an amount - call record_buyin with that amount. If they tell you their total for the night - profit or loss - call close_session with profit, positive for profit, negative for loss. If they tell you they cashed out or walked away with an amount, call close_session with cashout. If they say they're done - 'done', 'end session', 'that's it', 'I'm out' - do NOT close the session yet. Instead, ask them to confirm their total buy-in and total cash-out. Once they give you both numbers, call record_buyin with their total buy-in, then call close_session with cashout. If they say they're done with no numbers at all, close with cashout 0. Respond ONLY with the confirmation, e.g. 'Bought in for $5.' or 'Session closed - [+/-profit].' or 'Logged - AKo, won, $20. Logged - 77, lost, $10.' Never give advice. Never judge a hand's quality. If the player's message names NO hole cards at all (e.g. just 'lost 35', 'won the pot', 'flop came 8 7 2'), leave the hand field OUT of log_hand - the system attaches their most recent hand itself. Only respond 'What hand were you holding?' when the player gives no cards and there is no previous hand to attach. If they say they're done AND give a profit or cash-out figure now, call close_session immediately with those figures - never reply with conversation or advice instead of closing, and if the buy-in was already recorded earlier in this conversation, use it - do not ask them to confirm buy-in again."

session_system = "You are a poker session logger. This player only wants their session results tracked - buy-ins and the final number - NOT individual hands or cards. Ignore any mention of specific hands, cards, positions, or actions and never ask about them. If they mention a buy-in or rebuy - 'bought in', 'buy-in', 'rebuy', 'loaded up', with an amount - call record_buyin with that amount. If they say they're done or give their result - 'done', 'end of session', 'cashed out X', 'walked away with X', 'won X', 'up X', 'lost X', 'down X' - call close_session with the figure: cashout for an amount they walked away with, profit otherwise (positive for profit, negative for loss). If they say done without any figure, ask once for their total buy-in and total cash-out, then call record_buyin with the total buy-in and close_session with cashout. Never call log_hand. Respond ONLY with short confirmations, e.g. 'Bought in for $5.' or 'Session closed: +$30.' Never give advice."

def build_system(mode, session=None):
	base = session_system if mode == "session" else (track_system if mode == "track" else coach_system)
	if session and session.get("hand") and mode == "coach":
		hand = session["hand"]
		pos = session.get("position", "")
		prev = session.get("prev_input", "")
		streets = session.get("streets", [])
		base += f" CONTEXT - holding {hand}"
		if pos: base += f" from {pos}"
		base += f". original: '{prev}'."
		if streets:
			for s in streets:
				if s: base += f" then: '{s}'."
		base += " Continuation - if they describe a board, use evaluate_poker_hand with hole cards plus ALL cards mentioned."
	return {"role": "system", "content": base}

def format_track(parsed, session=None, closed=False, logged_hands=None, units="dollars"):
	if parsed.get("buyin"):
		return f"Bought in for {fmt_amount(parsed['amount'], units)}."
	if closed and (parsed.get("profit") is not None or parsed.get("cashout") is not None):
		if parsed.get("cashout") is not None and parsed.get("profit") is None:
			return f"Session closed: cashed out {fmt_amount(parsed['cashout'], units)}."
		p = parsed.get("profit", 0)
		psym = "$" if (units or "dollars") == "dollars" else ""
		psfx = "" if (units or "dollars") == "dollars" else (units or "dollars")
		sign = "+" if p >= 0 else "-"
		return f"Session closed: {sign}{psym}{abs(p)}{psfx}."
	if logged_hands:
		out = []
		for h in logged_hands:
			parts = [h.get("hand") or (session.get("hand") if session else None) or "?"]
			if h.get("position"): parts.append(h["position"])
			if h.get("action"): parts.append(h["action"])
			if h.get("result"): parts.append("won" if str(h["result"]).lower() in ("won", "win", "w") else "lost")
			if h.get("amount") is not None: parts.append(fmt_amount(h["amount"], units))
			out.append("Logged - " + ", ".join(parts))
		return ". ".join(out) + "."
	hand = parsed.get("hand") or (session.get("hand") if session else None) or "?"
	parts = [hand]
	if parsed.get("position"): parts.append(parsed["position"])
	if parsed.get("action"): parts.append(parsed["action"])
	if parsed.get("result"): parts.append("won" if str(parsed["result"]).lower() in ("won", "win", "w") else "lost")
	if parsed.get("amount") is not None: parts.append(fmt_amount(parsed["amount"], units))
	return "Logged - " + ", ".join(parts) + "."
def run_pipeline(user_input, mode, user_id=None, units="dollars"):
    session = None
    if user_id:
        session = get_session_context(user_id)
    system_msg = build_system(mode, session)
    messages = [{"role": "system", "content": system_msg["content"]}, {"role": "user", "content": user_input}]
    if units and units in ("bb", "chips"):
        messages[0]["content"] += f" The player is tracking this session in {units}. Report amounts exactly as stated, in {units}, without converting."
    try:
        response = groq_ask(messages, tools=tools, tool_choice="auto")
    except Exception as e:
        return f"AI error: {str(e)}", {}, session, False, False, []
    msg = response.choices[0].message
    parsed = {}
    tool_called = False
    logged_hands = []
    if msg.tool_calls:
        tool_called = True
        messages.append(msg)
        closed = False
        for tc in msg.tool_calls:
            fn = available.get(tc.function.name)
            try:
                args = json.loads(tc.function.arguments)
                result = fn(**args) if fn else "Not found."
            except Exception as e:
                result = json.dumps({"error": f"Tool failed: {str(e)}"})
            messages.append({"tool_call_id": tc.id, "role": "tool", "name": tc.function.name, "content": result})
            if tc.function.name in ("preflop_advice", "evaluate_poker_hand", "log_hand", "close_session", "record_buyin"):
                try:
                    parsed = json.loads(result)
                except:
                    pass
                if parsed.get("result") is not None:
                    parsed["result"] = "won" if str(parsed["result"]).lower() in ("won", "win", "w") else "lost"
            if tc.function.name == "log_hand":
                hs = parsed.get("hands")
                ctx_hand = session.get("hand") if session else None
                if isinstance(hs, list) and hs:
                    for h in hs:
                        if h.get("result") is not None:
                            h["result"] = "won" if str(h["result"]).lower() in ("won", "win", "w") else "lost"
                        if not h.get("hand") and ctx_hand:
                            h["hand"] = ctx_hand
                        logged_hands.append(h)
                elif parsed.get("hand") or ctx_hand:
                    if not parsed.get("hand") and ctx_hand:
                        parsed["hand"] = ctx_hand
                    logged_hands.append(parsed)
            if tc.function.name == "record_buyin" and mode in ("track", "session"):
                try:
                    sid = get_or_create_session(user_id, units)
                    if sid and args.get("amount") is not None:
                        supabase.table("buyins").insert({"session_id": sid, "user_id": user_id, "amount": args["amount"]}).execute()
                except Exception as exc:
                    discord_ping(f"record_buyin insert: {exc}")
            if tc.function.name == "close_session":
                closed = True
        if mode in ("track", "session"):
            if closed and user_id:
                try:
                    sid = get_or_create_session(user_id, units)
                    if sid:
                        profit = parsed.get("profit")
                        cashout = parsed.get("cashout")
                        if profit is None and cashout is not None:
                            profit = round(cashout - session_buyin_total(sid), 2)
                        if profit is not None:
                            parsed["profit"] = profit
                        row = {"status": "closed", "profit": parsed.get("profit"), "closed_at": "now()"}
                        if cashout is not None:
                            row["cashout"] = cashout
                        try:
                            supabase.table("sessions").update(row).eq("id", sid).execute()
                        except Exception as exc:
                            if "cashout" in row:
                                del row["cashout"]
                                supabase.table("sessions").update(row).eq("id", sid).execute()
                            else:
                                discord_ping(f"close_session update: {exc}")
                        if (units or "dollars") == "dollars":
                            credit_bankroll(user_id, parsed.get("profit"))
                except Exception as exc:
                    discord_ping(f"close_session: {exc}")
            reply = format_track(parsed, session, closed, logged_hands, units)
            return reply, parsed, session, tool_called, closed, logged_hands
    eval_data = ""
    if parsed.get("hand"):
        eval_data += f"Hand: {parsed['hand']}. "
    if parsed.get("tier"):
        eval_data += f"Tier: {parsed['tier']}. "
    if parsed.get("position"):
        eval_data += f"Position: {parsed['position']}. "
    if parsed.get("action"):
        eval_data += f"Strategy: {parsed['action']}. "
    if parsed.get("hand_rank"):
        eval_data += f"Hand rank: {parsed['hand_rank']}. Score: {parsed.get('score', '')}. "
    if not eval_data:
        eval_data = json.dumps(parsed)
    clean = [
        {"role": "system", "content": "You are a poker coach. Respond to the player based on this data - 2-3 short sentences. No tool calls."},
        {"role": "user", "content": f"Asked: {user_input}\nData: {eval_data.strip()}"}
    ]
    try:
        second = groq_ask(clean)
        return second.choices[0].message.content, parsed, session, tool_called, False, logged_hands
    except Exception:
        return format_track(parsed, session), parsed, session, tool_called, False, logged_hands
    return msg.content, parsed, session, tool_called, False, logged_hands
def recap_turn(user_input, user_id, session_id):
    try:
        if session_id:
            sres = supabase.table("sessions").select("id, created_at, closed_at, profit, cashout, status").eq("user_id", user_id).eq("id", session_id).execute()
            sess = sres.data[0] if (sres.data and sres.data[0]) else None
            if not sess:
                return "That session isn't available.", None
        else:
            sres = supabase.table("sessions").select("id, created_at, closed_at, profit, cashout, status").eq("user_id", user_id).eq("status", "closed").order("closed_at", desc=True).limit(1).execute()
            sess = sres.data[0] if (sres.data and sres.data[0]) else None
            if not sess:
                return "No completed session to recap yet.", None
        sid = sess["id"]
        hr = supabase.table("messages").select("hand, position, player_action, result, amount, input, created_at").eq("session_id", sid).eq("user_id", user_id).order("created_at", desc=False).execute()
        hands = [h for h in (hr.data or []) if h.get("hand")][:30]
        if not hands:
            return "That session has no logged hands to recap yet.", sid
        buyin_total = session_buyin_total(sid)
        lines = []
        for i, h in enumerate(hands, 1):
            parts = [h.get("hand", "?")]
            if h.get("position"): parts.append(h["position"])
            if h.get("player_action"): parts.append(h["player_action"])
            if h.get("result"):
                r = h["result"]
                if h.get("amount"): r += f" ${h['amount']}"
                parts.append(r)
            lines.append(f"{i}. " + " / ".join(parts))
        hand_text = "\n".join(lines)
        summary = (f"Buy-ins: ${buyin_total:.2f} total. Cashed out: ${(sess.get('cashout') or 0):.2f}. "
                   f"Net: ${(sess.get('profit') or 0):+.2f}. Played from {sess.get('created_at')} to {sess.get('closed_at')}.")
        system = ("You are a poker coach doing a post-session recap. The user just finished a tracking session. "
                  "Use ONLY the hands listed below - they are exactly what was played. Go through them and point out "
                  "errors and missed opportunities: leaks, sizing, positions, folding too much or too little, passive play. "
                  "Be specific and friendly, like a trusted friend texting advice. For your first message give an honest "
                  "short verdict plus 1-2 concrete things to fix. Then answer follow-ups about these hands in 2-3 short "
                  "sentences. Never log or save anything - this is conversation only.\n\n"
                  f"SESSION\n{summary}\n\nHANDS PLAYED\n{hand_text}")
        hist = supabase.table("recap_messages").select("role, content").eq("session_id", sid).eq("user_id", user_id).order("created_at", desc=False).limit(40).execute()
        msgs = [{"role": "system", "content": system}]
        for m in (hist.data or []):
            msgs.append({"role": m["role"], "content": m["content"]})
        msgs.append({"role": "user", "content": user_input})
        try:
            resp = groq_ask(msgs)
            reply = resp.choices[0].message.content or ""
        except Exception as e:
            return f"AI error: {str(e)}", sid
        try:
            supabase.table("recap_messages").insert([
                {"session_id": sid, "user_id": user_id, "role": "user", "content": user_input},
                {"session_id": sid, "user_id": user_id, "role": "assistant", "content": reply},
            ]).execute()
        except Exception as exc:
            discord_ping(f"recap insert: {exc}")
        return reply, sid
    except Exception as exc:
        discord_ping(f"recap_turn: {exc}")
        return "Could not recap that session.", None
def build_performance_summary(user_id):
	try:
		sres = supabase.table("sessions").select("id, created_at, closed_at, profit, cashout, status, units, label").eq("user_id", user_id).eq("status", "closed").order("created_at", desc=True).limit(120).execute()
	except Exception as exc:
		discord_ping(f"perf sessions: {exc}")
		sres = None
	sessions = (sres.data or []) if sres else []
	sid_list = [s["id"] for s in sessions]
	buyin_map = {}
	if sid_list:
		try:
			bres = supabase.table("buyins").select("session_id, amount").in_("session_id", sid_list).execute()
			for r in (bres.data or []):
				buyin_map[r["session_id"]] = round(buyin_map.get(r["session_id"], 0) + (r.get("amount") or 0), 2)
		except Exception:
			pass
	for s in sessions:
		s["buyins"] = buyin_map.get(s["id"], 0)
	hand_counts = {}
	all_hands = []
	try:
		hres = supabase.table("messages").select("session_id, hand, position, player_action, result, amount, tier").eq("user_id", user_id).execute()
		for r in (hres.data or []):
			if r.get("session_id") in (sid_list or []) and r.get("hand"):
				hand_counts[r["session_id"]] = hand_counts.get(r["session_id"], 0) + 1
			if r.get("hand"):
				all_hands.append(r)
	except Exception as exc:
		discord_ping(f"perf hands: {exc}")
	actions = {}
	tiers = {}
	positions = {}
	for h in all_hands:
		a = (h.get("player_action") or "").lower()
		if a: actions[a] = actions.get(a, 0) + 1
		t = (h.get("tier") or "").lower()
		if t: tiers[t] = tiers.get(t, 0) + 1
		p = h.get("position")
		if p:
			key = p.upper()
			if key: positions[key] = positions.get(key, 0) + 1
	dollar = [s for s in sessions if (s.get("units") or "dollars") == "dollars"]
	def agg(rows):
		if not rows:
			return None
		vals = [(r.get("profit") or 0) for r in rows]
		total = round(sum(vals), 2)
		wins = sum(1 for v in vals if v > 0)
		bi = sum(r.get("buyins") or 0 for r in rows)
		return {"n": len(rows), "total": total, "avg": round(total / len(rows), 2),
		        "wr": round(wins / len(rows) * 100), "buyin": bi,
		        "roi": round(total / bi * 100) if bi else None}
	agg_all = agg(dollar)
	with_hands = [s for s in dollar if hand_counts.get(s["id"], 0) > 0]
	low_bucket = high_bucket = None
	if len(with_hands) >= 4:
		counts = sorted(hand_counts[s["id"]] for s in with_hands)
		med = counts[len(counts) // 2]
		low_a = agg([s for s in with_hands if hand_counts[s["id"]] <= med])
		high_a = agg([s for s in with_hands if hand_counts[s["id"]] > med])
		if low_a and high_a:
			low_bucket = {"n": low_a["n"], "hands": "fewer", "avg": low_a["avg"], "total": low_a["total"], "wr": low_a["wr"]}
			high_bucket = {"n": high_a["n"], "hands": "more", "avg": high_a["avg"], "total": high_a["total"], "wr": high_a["wr"]}
	notable = [h for h in all_hands if h.get("amount") is not None]
	notable.sort(key=lambda h: abs(h.get("amount") or 0), reverse=True)
	notable = notable[:10]
	lines = [f"Total closed sessions: {len(sessions)}"]
	if agg_all:
		lines.append(f"Overall (dollar sessions, n={agg_all['n']}): total profit {agg_all['total']:+.2f}, avg per session {agg_all['avg']:+.2f}, win rate {agg_all['wr']}%, ROI {agg_all['roi']}%")
	if not sessions:
		lines.append("The player has no completed sessions yet.")
	ps_lines = []
	for s in sessions[:40]:
		unit = s.get("units") or "dollars"
		p = s.get("profit") if s.get("profit") is not None else 0
		label = (s.get("label") or "").strip()
		d = (s.get("closed_at") or s.get("created_at") or "")[:10]
		bits = [f"{d} {label}".strip(), f"buyin {s.get('buyins') or 0}", f"profit {p:+.2f}{'' if unit == 'dollars' else ' ' + unit}", f"hands {hand_counts.get(s['id'], 0)}"]
		ps_lines.append("; ".join(bits))
	if ps_lines:
		lines.append("Per-session (most recent first): " + " || ".join(ps_lines))
	if low_bucket:
		lines.append(f"Volume split: sessions with FEWER hands (<=median, n={low_bucket['n']}): avg profit {low_bucket['avg']:+.2f}, win rate {low_bucket['wr']}%. Sessions with MORE hands (n={high_bucket['n']}): avg profit {high_bucket['avg']:+.2f}, win rate {high_bucket['wr']}%.")
	if actions:
		atxt = ", ".join(f"{k} {v}" for k, v in sorted(actions.items(), key=lambda x: -x[1]))
		lines.append(f"Action mix across logged hands: {atxt}.")
	if tiers:
		ttxt = ", ".join(f"{k} {v}" for k, v in sorted(tiers.items(), key=lambda x: -x[1]))
		lines.append(f"Hand tier mix: {ttxt}.")
	if positions:
		ptxt = ", ".join(f"{k} {v}" for k, v in sorted(positions.items(), key=lambda x: -x[1]))
		lines.append(f"Position frequency: {ptxt}.")
	if notable:
		nl = []
		for h in notable[:8]:
			parts = [h.get("hand") or "?", h.get("position") or "", h.get("player_action") or "", "won" if str(h.get("result") or "").lower() in ("won", "win", "w") else ("lost" if h.get("result") else ""), f"{h.get('amount')}"]
			nl.append(" ".join(x for x in parts if x))
		lines.append("Biggest hands by amount: " + "; ".join(nl))
	if len(sessions) == 0 and len(all_hands) == 0:
		lines.append("No tracked data at all yet.")
	return "\n".join(lines)

def performance_insight_turn(user_input, user_id, history=None):
	summary = build_performance_summary(user_id)
	system = ("You are a poker performance analyst. Below is the player's ACTUAL tracked data from their own app: aggregate stats, "
	          "per-session results, hand counts, action/tier mix, and their biggest hands. Analyze that data and answer their question. "
	          "Ground every claim in the data given - NEVER invent numbers, hands, sessions, or patterns. "
	          "If it's the first question (no prior conversation), give an honest overall verdict plus 2 concrete themes from their data. "
	          "When asked about session length vs profitability, use the provided volume split averages. "
	          "Keep answers to 2-4 short sentences unless you're walking through a theme, then be concrete and specific with their numbers. "
	          "Talk like a trusted poker friend. Do not ask the user for more data - you have everything.\n\n"
	          f"PLAYER DATA\n{summary}")
	msgs = [{"role": "system", "content": system}]
	if history:
		msgs.extend([{"role": h.get("role") if h.get("role") in ("user", "assistant") else "user", "content": h.get("content", "")} for h in history[-16:]])
	msgs.append({"role": "user", "content": user_input})
	try:
		resp = groq_ask(msgs)
		return resp.choices[0].message.content or "Could not analyze that right now."
	except Exception as e:
		return f"AI error: {str(e)}"

def drill_context(user_id):
	lines = []
	try:
		hres = supabase.table("messages").select("session_id, hand, position, player_action, result, amount, created_at").eq("user_id", user_id).order("created_at", desc=True).limit(200).execute()
	except Exception as exc:
		discord_ping(f"drill hands: {exc}")
		hres = None
	hands = [h for h in ((hres.data or []) if hres else []) if h.get("hand")]
	recent = hands[:12]
	if recent:
		rl = []
		for h in recent[:12]:
			parts = [h.get("hand") or "?", h.get("position") or "", h.get("player_action") or "",
			         "won" if str(h.get("result") or "").lower() in ("won", "win", "w") else ("lost" if h.get("result") else ""),
			         f"{h.get('amount')}" if h.get("amount") is not None else ""]
			rl.append(" ".join(x for x in parts if x))
		lines.append("Recent hands: " + "; ".join(rl))
	losing = [h for h in hands if str(h.get("result") or "").lower() in ("lost", "lose", "l") and h.get("amount") is not None]
	losing.sort(key=lambda h: abs(h.get("amount") or 0), reverse=True)
	if losing:
		ll = []
		for h in losing[:5]:
			parts = [h.get("hand") or "?", h.get("position") or "", h.get("player_action") or "", f"lost {h.get('amount')}"]
			ll.append(" ".join(x for x in parts if x))
		lines.append("Biggest losses: " + "; ".join(ll))
	actions = {}
	tiers = {}
	fold = 0
	total = 0
	for h in hands:
		a = (h.get("player_action") or "").lower()
		if a:
			actions[a] = actions.get(a, 0) + 1
		if a == "fold":
			fold += 1
		total += 1
		t = (h.get("tier") or "").lower()
		if t:
			tiers[t] = tiers.get(t, 0) + 1
	if actions:
		lines.append("Action mix: " + ", ".join(f"{k} {v}" for k, v in sorted(actions.items(), key=lambda x: -x[1])) + ".")
	if tiers:
		lines.append("Hand tier mix: " + ", ".join(f"{k} {v}" for k, v in sorted(tiers.items(), key=lambda x: -x[1])) + ".")
	if total:
		lines.append(f"Fold rate: {round(fold / total * 100)}% across {total} logged hands.")
	if not lines:
		lines.append("No logged hands yet - use general poker fundamentals drills.")
	return "\n".join(lines)

def drill_turn(user_input, user_id, history=None):
	ctx = drill_context(user_id)
	system = ("You are a poker training coach that drills the player on their OWN tendencies, using the hand data below. "
	          "Ask ONE hand-scenario question at a time: give the situation (position, hole cards, maybe a board) - reuse their real hands "
	          "and leak patterns whenever you can. Then STOP and wait for their answer. After they answer, give short honest feedback "
	          "(correct play vs their leak, and why) in 2-3 sentences, then ask the NEXT question. "
	          "Start your FIRST message by naming their clearest leak from the data and leading with a drill on it. "
	          "Keep each scenario under ~60 words. Never reveal the answer before they answer. Be encouraging but honest, like a friend coaching from the rail.\n\n"
	          f"PLAYER DATA\n{ctx}")
	msgs = [{"role": "system", "content": system}]
	if history:
		msgs.extend([{"role": h.get("role") if h.get("role") in ("user", "assistant") else "user", "content": h.get("content", "")} for h in history[-16:]])
	msgs.append({"role": "user", "content": user_input})
	try:
		resp = groq_ask(msgs)
		return resp.choices[0].message.content or "Could not build a drill right now."
	except Exception as e:
		return f"AI error: {str(e)}"

@app.post("/api/chat")
async def chat_endpoint(req: Request):
    if not startup_ok:
        return {"reply": f"Startup failed: {startup_error}"}
    try:
        body = await req.json()
    except:
        return {"reply": "Could not read your message."}
    user_input = body.get("message", "")
    mode = body.get("mode", "coach")
    units = body.get("units", "dollars")
    auth_header = req.headers.get("authorization", "")
    user_id = None
    user_email = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            resp = supabase.auth.get_user(token)
            if resp and resp.user:
                user_id = resp.user.id
                user_email = resp.user.email
        except:
            pass
    ent = entitlement(user_id, user_email) if user_id else {"tier": "free", "plan": "free", "limits": tier_limits("free")}
    if mode == "recap":
        if not user_id:
            return {"reply": "Sign in to recap a session."}
        if not (ent.get("limits") or {}).get("recap"):
            return {"reply": "Recap is a Pro feature. Upgrade to unlock it and re-analyze any past session in one tap.", "parsed": {}, "paywall": "recap"}
        limit_msg = check_chat_quota(user_email, user_id, "recap", ent)
        if limit_msg:
            return {"reply": limit_msg, "parsed": {}, "quota": "recap", "bullets": ["Where you bled the most chips", "Spots you over-called or over-folded", "Win rate by position", "Your 3 biggest missed opportunities"]}
        reply, rid = recap_turn(user_input, user_id, body.get("session_id"))
        return {"reply": reply, "parsed": {}, "recap_session_id": rid}
    if mode == "review":
        if not user_id:
            return {"reply": "Sign in to review your performance."}
        if not (ent.get("limits") or {}).get("recap"):
            return {"reply": "Performance review is a Pro feature. Upgrade to unlock it and get a full analysis of your saved sessions, themes, and leaks.", "parsed": {}, "paywall": "review"}
        limit_msg = check_chat_quota(user_email, user_id, "recap", ent)
        if limit_msg:
            return {"reply": limit_msg, "parsed": {}, "quota": "review", "bullets": ["Are you more profitable with fewer or more hands per night", "Biggest wins and worst leaks by the numbers", "Where your value leaks: sizing, calls, folds, positions", "Session trends and tilt patterns"]}
        reply = performance_insight_turn(user_input, user_id, body.get("history"))
        return {"reply": reply, "parsed": {}}
    if mode == "drill":
        if not user_id:
            return {"reply": "Sign in to train your leaks."}
        limit_msg = check_chat_quota(user_email, user_id, "coach", ent)
        if limit_msg:
            return {"reply": limit_msg, "parsed": {}, "quota": "drill", "bullets": ["Hand drills ripped from your own game", "Instant feedback on each decision you make", "Focuses your biggest, costliest leaks"]}
        reply = drill_turn(user_input, user_id, body.get("history"))
        return {"reply": reply, "parsed": {}}
    limit_msg = check_chat_quota(user_email, user_id, mode if mode in ("coach", "track", "session") else "chat", ent)
    if limit_msg:
        return {"reply": limit_msg, "parsed": {}, "quota": mode if mode in ("coach", "track", "session") else "chat"}
    reply, parsed, session, tool_called, closed, logged_hands = run_pipeline(user_input, mode, user_id, body.get("units", "dollars"))
    if user_id and tool_called and not closed and not parsed.get("buyin"):
        batch = logged_hands if logged_hands else [parsed]
        if any(b.get("hand") or b.get("result") or b.get("amount") for b in batch):
            try:
                session_id = get_or_create_session(user_id, units) if mode == "track" else None
                prev_hand = session.get("hand") if session else None
                single = len(batch) == 1
                for bh in batch:
                    row_hand = bh.get("hand")
                    if not row_hand and mode == "track" and prev_hand:
                        named_cards = bool(re.search(r"(?i)\b[2-9tjqka]{2}[oOsS]?\b", user_input))
                        if not named_cards:
                            row_hand = prev_hand
                    if not row_hand:
                        continue
                    row = {
                        "user_id": user_id,
                        "input": user_input,
                        "reply": reply,
                        "hand": row_hand,
                        "position": bh.get("position"),
                        "player_action": bh.get("action"),
                        "result": bh.get("result"),
                        "amount": bh.get("amount"),
                        "session_id": session_id,
                    }
                    if mode == "coach" and bh.get("tier"):
                        row["tier"] = bh["tier"]
                    if single and prev_hand and row_hand == prev_hand:
                        q = supabase.table("messages").select("id").eq("user_id", user_id).eq("hand", prev_hand)
                        if mode == "track" and session_id:
                            q = q.eq("session_id", session_id)
                        last = q.order("created_at", desc=True).limit(1).execute()
                        if last.data and last.data[0]:
                            update = {"reply": reply}
                            if bh.get("action"):
                                update["player_action"] = bh["action"]
                            if bh.get("result"):
                                update["result"] = bh["result"]
                            if bh.get("amount") is not None:
                                update["amount"] = bh["amount"]
                            supabase.table("messages").update(update).eq("id", last.data[0]["id"]).execute()
                            continue
                    supabase.table("messages").insert(row).execute()
            except Exception as e:
                discord_ping(f"chat message insert: {e}")
                reply += f" (log error: {str(e)})"
    return {"reply": reply, "parsed": parsed}

@app.get("/api/sessions")
async def sessions_endpoint(req: Request):
    user_id, email = auth_identity(req)
    if not user_id:
        return {"error": "unauthorized"}
    ent = entitlement(user_id, email)
    try:
        q = supabase.table("sessions").select("id, created_at, closed_at, profit, cashout, status, units, label").eq("user_id", user_id)
        hdays = (ent.get("limits") or {}).get("history_days")
        if hdays:
            q = q.gte("created_at", (datetime.now(timezone.utc) - timedelta(days=hdays)).isoformat())
        result = q.order("created_at", desc=True).execute()
        sessions = result.data or []
    except Exception as exc:
        discord_ping(f"get sessions: {exc}")
        sessions = []
    sid_list = [r["id"] for r in sessions]
    buyin_map = {}
    if sid_list:
        try:
            bres = supabase.table("buyins").select("session_id, amount").in_("session_id", sid_list).execute()
            for r in (bres.data or []):
                buyin_map[r["session_id"]] = round(buyin_map.get(r["session_id"], 0) + (r.get("amount") or 0), 2)
        except:
            pass
    for r in sessions:
        r["buyins"] = buyin_map.get(r["id"], 0)
    return {"sessions": sessions}

@app.post("/api/result")
async def result_endpoint(req: Request):
    try:
        body = await req.json()
        auth_header = req.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return {"error": "unauthorized"}
        token = auth_header[7:]
        resp = supabase.auth.get_user(token)
        if not resp or not resp.user:
            return {"error": "unauthorized"}
        supabase.table("messages").update({"result": body.get("result"), "amount": body.get("amount")}).eq("id", body.get("id")).execute()
        return {"ok": True}
    except Exception as e:
        return {"error": str(e)}

@app.get("/api/history")
async def history_endpoint(req: Request):
    try:
        auth_header = req.headers.get("authorization", "")
        if not auth_header.startswith("Bearer "):
            return {"error": "unauthorized"}
        token = auth_header[7:]
        resp = supabase.auth.get_user(token)
        if not resp or not resp.user:
            return {"error": "unauthorized"}
        user_id = resp.user.id
        ent = entitlement(user_id, resp.user.email)
        q = supabase.table("messages").select("id, input, reply, hand, tier, position, player_action, result, amount, created_at").eq("user_id", user_id)
        hdays = (ent.get("limits") or {}).get("history_days")
        if hdays:
            q = q.gte("created_at", (datetime.now(timezone.utc) - timedelta(days=hdays)).isoformat())
        result = q.order("created_at", desc=True).execute()
        return {"history": result.data}
    except Exception as e:
        return {"error": "unauthorized"}

def auth_user_id(req):
    auth_header = req.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None
    token = auth_header[7:]
    try:
        resp = supabase.auth.get_user(token)
        if resp and resp.user:
            return resp.user.id
    except:
        pass
    return None

@app.get("/api/export")
async def export_endpoint(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        profile = supabase.table("profiles").select("username, created_at").eq("user_id", uid).execute()
        sessions = supabase.table("sessions").select("*").eq("user_id", uid).order("created_at", desc=False).execute()
        sess_ids = [s["id"] for s in (sessions.data or [])]
        buyins = []
        if sess_ids:
            bres = supabase.table("buyins").select("session_id, amount, created_at").in_("session_id", sess_ids).order("created_at", desc=False).execute()
            buyins = bres.data or []
        hands = supabase.table("messages").select("hand, position, player_action, result, amount, input, reply, tier, created_at").eq("user_id", uid).order("created_at", desc=False).execute()
        bankroll = supabase.table("bankrolls").select("amount, goal, updated_at").eq("user_id", uid).execute()
        discord = supabase.table("discord_links").select("discord_username, linked_at").eq("user_id", uid).execute()
        stats = session_stats(uid)
    except Exception as exc:
        discord_ping(f"export: {exc}")
        return {"error": "Could not export data right now."}
    return {
        "ok": True,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "username": (profile.data[0] or {}).get("username") if profile.data else None,
        "joined_at": (profile.data[0] or {}).get("created_at") if profile.data else None,
        "stats": stats,
        "bankroll": (bankroll.data[0] or {}) if bankroll.data else None,
        "discord_link": (discord.data[0] or {}) if discord.data else None,
        "sessions": sessions.data or [],
        "buyins": buyins,
        "hands": hands.data or [],
    }

@app.post("/api/account/delete")
async def account_delete(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except:
        body = {}
    if (body.get("confirm") or "").strip().lower() != "delete":
        return {"error": "Type DELETE to confirm you want your account removed."}
    try:
        for tbl in ("buyins", "recap_messages", "messages", "sessions", "friends", "discord_links", "bankrolls", "chat_usage", "profiles"):
            supabase.table(tbl).delete().eq("user_id", uid).execute()
        supabase.table("friends").delete().eq("friend_id", uid).execute()
        supabase.auth.admin.delete_user(uid)
    except Exception as exc:
        discord_ping(f"account delete: {exc}")
        return {"error": "Could not delete your account right now. Try again in a minute."}
    try:
        discord_ping(f"Account deleted: {uid[:8]}")
    except Exception:
        pass
    return {"ok": True}

@app.post("/api/history/update")
async def history_update(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except:
        return {"error": "bad request"}
    rid = body.get("id")
    if not rid:
        return {"error": "missing id"}
    updates = {}
    for k in ("hand", "position", "player_action", "result", "amount"):
        if k in body:
            v = body[k]
            updates[k] = v if v not in ("", None) else None
    if not updates:
        return {"error": "nothing to update"}
    try:
        supabase.table("messages").update(updates).eq("id", rid).eq("user_id", uid).execute()
        return {"ok": True}
    except Exception as exc:
        discord_ping(f"history update: {exc}")
        return {"error": str(exc)}

@app.post("/api/history/delete")
async def history_delete(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except:
        return {"error": "bad request"}
    rid = body.get("id")
    if not rid:
        return {"error": "missing id"}
    try:
        supabase.table("messages").delete().eq("id", rid).eq("user_id", uid).execute()
        return {"ok": True}
    except Exception as exc:
        discord_ping(f"history delete: {exc}")
        return {"error": str(exc)}

@app.post("/api/session/start")
async def session_start(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except:
        body = {}
    try:
        amount = body.get("amount")
        amount = float(amount) if amount not in (None, "") else 0
        if amount < 0:
            amount = 0
    except (TypeError, ValueError):
        return {"error": "Enter a valid buy-in amount."}
    try:
        sid = get_or_create_session(uid, body.get("units", "dollars"))
        if not sid:
            return {"error": "Could not start a session right now."}
        if amount > 0:
            try:
                supabase.table("buyins").insert({"session_id": sid, "user_id": uid, "amount": round(amount, 2)}).execute()
            except Exception as exc:
                discord_ping(f"session/start buyin: {exc}")
        return {"ok": True, "session_id": sid, "buyins_total": session_buyin_total(sid)}
    except Exception as exc:
        discord_ping(f"session/start: {exc}")
        return {"error": str(exc)}

@app.get("/api/session")
async def session_detail(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    sid = req.query_params.get("id")
    if not sid:
        return {"error": "missing id"}
    try:
        sres = supabase.table("sessions").select("id, created_at, closed_at, profit, cashout, status, label, units").eq("id", sid).eq("user_id", uid).execute()
        sess = sres.data[0] if (sres.data and sres.data[0]) else None
        if not sess:
            return {"error": "not found"}
        hands = supabase.table("messages").select("id, hand, position, player_action, result, amount, created_at").eq("session_id", sid).order("created_at", desc=False).execute()
        buyins = supabase.table("buyins").select("amount, created_at").eq("session_id", sid).order("created_at", desc=False).execute()
        sess["hands"] = hands.data or []
        sess["buyin_list"] = buyins.data or []
        sess["buyins_total"] = session_buyin_total(sid)
        return {"session": sess}
    except Exception as exc:
        discord_ping(f"session detail: {exc}")
        return {"error": str(exc)}

@app.post("/api/session/delete")
async def session_delete(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except:
        return {"error": "bad request"}
    sid = body.get("id")
    if not sid:
        return {"error": "missing id"}
    try:
        try:
            srow = supabase.table("sessions").select("status, profit, units").eq("id", sid).eq("user_id", uid).execute()
            sess = srow.data[0] if (srow.data and srow.data[0]) else None
        except:
            sess = None
        supabase.table("buyins").delete().eq("session_id", sid).eq("user_id", uid).execute()
        supabase.table("recap_messages").delete().eq("session_id", sid).eq("user_id", uid).execute()
        supabase.table("messages").delete().eq("session_id", sid).eq("user_id", uid).execute()
        supabase.table("sessions").delete().eq("id", sid).eq("user_id", uid).execute()
        if sess and sess.get("status") == "closed" and (sess.get("units") or "dollars") == "dollars" and sess.get("profit"):
            revert_bankroll(uid, float(sess["profit"]))
        return {"ok": True}
    except Exception as exc:
        discord_ping(f"session delete: {exc}")
        return {"error": str(exc)}

@app.post("/api/session/rename")
async def session_rename(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except:
        return {"error": "bad request"}
    sid = body.get("id")
    if not sid:
        return {"error": "missing id"}
    label = (body.get("label") or "").strip()[:40]
    try:
        supabase.table("sessions").update({"label": label or None}).eq("id", sid).eq("user_id", uid).execute()
        return {"ok": True}
    except Exception as exc:
        discord_ping(f"session rename: {exc}")
        return {"error": str(exc)}

@app.post("/api/import/session")
async def import_session(req: Request):
    uid, email = auth_identity(req)
    if not uid:
        return {"error": "unauthorized"}
    ent = entitlement(uid, email)
    if not (ent.get("limits") or {}).get("import"):
        return {"error": "Importing past sessions is a Pro feature. Upgrade to unlock it.", "paywall": "import"}
    try:
        body = await req.json()
    except:
        return {"error": "bad request"}
    date = str(body.get("date") or "").strip()
    if not date:
        return {"error": "Pick a date."}
    units = str(body.get("units") or "dollars").lower()
    if units not in ("dollars", "bb", "chips"):
        units = "dollars"
    try:
        buyins = round(float(body.get("buyins") or 0), 2)
    except (TypeError, ValueError):
        return {"error": "Buy-in must be a number."}
    if buyins < 0:
        return {"error": "Buy-in can't be negative."}
    label = str(body.get("label") or "").strip()[:40] or None
    cashout, profit = None, None
    try:
        if body.get("use_profit"):
            profit = float(body.get("profit"))
        else:
            cashout = float(body.get("cashout"))
            if cashout < 0:
                return {"error": "Cash-out can't be negative."}
    except (TypeError, ValueError):
        return {"error": "Enter a valid result amount."}
    final_profit = round(profit, 2) if profit is not None else (round(cashout - buyins, 2) if cashout is not None else None)
    try:
        row = {"user_id": uid, "units": units, "status": "closed", "label": label,
               "profit": final_profit, "cashout": None if body.get("use_profit") else cashout,
               "created_at": date, "closed_at": date}
        inserted = supabase.table("sessions").insert(row).execute()
        sid = inserted.data[0]["id"]
        if buyins > 0:
            supabase.table("buyins").insert({"session_id": sid, "user_id": uid, "amount": buyins, "created_at": date}).execute()
        bankroll_applied = False
        if body.get("apply_bankroll") and units == "dollars" and final_profit is not None and final_profit != 0:
            credit_bankroll(uid, final_profit)
            bankroll_applied = True
        return {"ok": True, "session_id": sid, "profit": final_profit, "bankroll_applied": bankroll_applied}
    except Exception as exc:
        discord_ping(f"import session: {exc}")
        return {"error": str(exc)}

ACTION_VERBS = {
    "fold": "fold", "folds": "fold", "check": "check", "checks": "check",
    "call": "call", "calls": "call", "limp": "call",
    "raise": "raise", "raises": "raise", "3-bet": "raise", "3bet": "raise",
    "open": "raise", "bet": "raise", "bets": "raise", "all-in": "raise", "allin": "raise", "shove": "raise",
}
_POS_FULL = {3: "UTG", 4: "UTG+1", 5: "MP", 6: "MP+1", 7: "CO", 8: "HJ", 9: "LJ"}
_POS_6MAX = {3: "UTG", 4: "MP", 5: "CO"}
_HH_HEADER = re.compile(r"^\*{3,}.*[Hh]and [Hh]istory.*$|^[^\n]*[Hh]and\s*#\s*\d+.*$")

def _money(x):
    m = re.search(r"([\d][\d,]{0,9}(?:\.\d{1,2})?)", str(x))
    return float(m.group(1).replace(",", "")) if m else None

def _nums(s):
    return [float(v.replace(",", "")) for v in re.findall(r"[\d][\d,]{0,9}(?:\.\d{1,2})?", str(s))]

def _canonical(cards):
    text = str(cards)
    parts = re.findall(r"[2-9TJQKA][shdcSHDC]", text)
    if len(parts) == 2:
        try:
            return to_canonical(parts[0][0] + parts[0][1].lower(), parts[1][0] + parts[1][1].lower())
        except Exception:
            pass
    m = re.search(r"\b([2-9TJQKA]{2})([oOsS])?\b", text)
    if m:
        c1, c2 = m.group(1)[0], m.group(1)[1]
        if c1 == c2:
            return c1 + c2
        if RANK_VALUES[c1] < RANK_VALUES[c2]:
            c1, c2 = c2, c1
        return c1 + c2 + ("s" if (m.group(2) or "").lower() == "s" else "o")
    return None

def _position_from(rel, n):
    if n == 2:
        return "BTN" if rel == 0 else "BB"
    if rel == 0: return "BTN"
    if rel == 1: return "SB"
    if rel == 2: return "BB"
    if n <= 6: return _POS_6MAX.get(rel, "")
    return _POS_FULL.get(rel, "")

def _parse_poker_block(blk):
    hero_m = re.search(r"Dealt to (\S+)", blk)
    if not hero_m:
        return {}
    hero = hero_m.group(1)
    cards_m = re.search(r"Dealt to[^\[]*\[([^\]]+)\]", blk)
    hand = _canonical(cards_m.group(1) if cards_m else "") or None
    if not hand:
        return {}
    seats = {}
    for s, nm in re.findall(r"Seat (\d+): ([^(\n]+)", blk):
        seats[int(s)] = nm.strip()
    n = (max(seats) - min(seats) + 1) if seats else 2
    hero_seat = next((s for s, nm in seats.items() if nm == hero or nm.startswith(hero)), None)
    btn_m = re.search(r"Seat #?(\d+) is the button", blk)
    btn = int(btn_m.group(1)) if btn_m else (n or 2)
    pos = ""
    if hero_seat:
        pos = _position_from((hero_seat - btn) % n, n)
    hero_lines = [ln.strip() for ln in blk.splitlines() if re.match(r"^\s*" + re.escape(hero) + r"[:\s]", ln)]
    action = ""
    contrib = 0.0
    for ln in hero_lines:
        low = ln.lower()
        if not action:
            for k, v in ACTION_VERBS.items():
                if k in low:
                    action = v
                    break
        nums = _nums(ln)
        if not nums:
            continue
        if "raise" in low or "all-in" in low or "shove" in low:
            contrib += nums[-1]
        elif "call" in low or "bet" in low:
            contrib += nums[0]
        elif "post" in low and "blind" in low:
            contrib += nums[0]
    won = None
    ret = re.search(r"uncalled bet\s*\(?\$?([\d.,]+)\)?\s*(?:returned|back)?\s*(?:to\s*)?" + re.escape(hero), blk)
    if ret:
        won = _money(ret.group(1))
    if won is None:
        ret = re.search(re.escape(hero) + r"\s*(?:collected|wins|won)\s+.*?([\d][\d,]{0,9}(?:\.\d{1,2})?)", blk, re.I)
        if ret:
            won = _money(ret.group(1))
    hero_showed = bool(re.search(r"^\s*" + re.escape(hero) + r":\s*shows", blk, re.M))
    hero_mucked = bool(re.search(r"^\s*" + re.escape(hero) + r":\s*(?:mucked|does(?: n)?['']?t?\s*show)", blk, re.I))
    opp_collected = bool(re.search(r"(?m)^(?!\s*" + re.escape(hero) + r"\b)[^\n]*?(?:collected|wins)\s+\$?", blk))
    result, amount = None, None
    if won is not None:
        result, amount = "won", round(won, 2)
    elif hero_showed or hero_mucked or opp_collected:
        result = "lost"
        amount = round(contrib, 2) if contrib else None
    elif action == "fold" and contrib:
        result, amount = "lost", round(contrib, 2)
    return {"hand": hand, "position": pos or None, "action": action, "result": result, "amount": amount}

def parse_full_history(text):
    blocks, cur = [], []
    for ln in text.splitlines():
        if _HH_HEADER.match(ln.strip()):
            if cur:
                blocks.append("\n".join(cur)); cur = []
            cur.append(ln)
        else:
            cur.append(ln)
    if cur:
        blocks.append("\n".join(cur))
    out = []
    for b in blocks:
        h = _parse_poker_block(b)
        if h.get("hand"):
            out.append(h)
    return out

def _extract_hand(line):
    m = re.search(r"((?:[2-9TJQKA][shdc]){2})", line, re.I)
    if m:
        return _canonical(m.group(1))
    m = re.search(r"\b([2-9TJQKA]{2})([oOsS])?\b", line)
    if m:
        return _canonical(m.group(1) + (m.group(2) or ""))
    return None

def _parse_simple_hand_object(h):
    hand = _canonical(str(h.get("hand") or h.get("cards") or "")) or _extract_hand(str(h.get("hand") or ""))
    if not hand:
        return {}
    action = str(h.get("action") or h.get("player_action") or "").strip().lower()
    action = ACTION_VERBS.get(action, "") or ""
    result = str(h.get("result") or "").strip().lower()
    result = result if result in ("won", "lost") else None
    amount = h.get("amount")
    try:
        amount = round(float(amount), 2) if amount not in (None, "") else None
    except (TypeError, ValueError):
        amount = None
    pos = str(h.get("position") or "").strip().upper()
    return {"hand": hand, "position": pos or None, "action": action, "result": result, "amount": amount}

def parse_simple_lines(text):
    out = []
    _SIMPLE_POS = re.compile(r"\b(BTN|BU|SB|BB|UTG\+1|UTG\+2|UTG|MP\+1|MP\+2|MP|CO|HJ|LJ)\b", re.I)
    for ln in text.splitlines():
        ln = ln.strip()
        if not ln:
            continue
        hand = _extract_hand(ln)
        if not hand:
            continue
        low = ln.lower()
        action = ""
        for k, v in ACTION_VERBS.items():
            if k in low:
                action = v
                break
        result = "won" if re.search(r"\b(won|wins|win|profit)\b", low) else ("lost" if re.search(r"\b(lost|lose|loss)\b", low) else None)
        amount = None
        nums = _nums(ln)
        if nums:
            amount = round(nums[0], 2) if result else None
        pos_m = _SIMPLE_POS.search(ln)
        pos = "BTN" if (pos_m and pos_m.group(1).upper() == "BU") else (pos_m.group(1).upper() if pos_m else "")
        out.append({"hand": hand, "position": pos or None, "action": action, "result": result, "amount": amount})
    return out

def parse_hand_text(text, source=""):
    text = (text or "").strip()
    if "Hand #" in text or "Hand History" in text or "Dealt to" in text or source in ("pokerstars", "partypoker", "ipoker", "pokernow"):
        full = parse_full_history(text)
        if full:
            return full
    return parse_simple_lines(text)

@app.post("/api/import/hands")
async def import_hands(req: Request):
    uid, email = auth_identity(req)
    if not uid:
        return {"error": "unauthorized"}
    ent = entitlement(uid, email)
    if not (ent.get("limits") or {}).get("import"):
        return {"error": "Importing hand histories is a Pro feature. Upgrade to unlock it.", "paywall": "import"}
    try:
        body = await req.json()
    except Exception:
        return {"error": "bad request"}
    source = str(body.get("source") or "").strip().lower()
    label = str(body.get("label") or "").strip()[:40] or None
    units = str(body.get("units") or ("chips" if source == "offsuit" else "dollars")).lower()
    if units not in ("dollars", "bb", "chips"):
        units = "dollars"
    text = str(body.get("text") or "").strip()
    raw = body.get("hands")
    hands = []
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict):
                h = _parse_simple_hand_object(item)
                if h.get("hand"):
                    hands.append(h)
    if not hands and text:
        hands = parse_hand_text(text, source)
    if not hands:
        return {"error": "Couldn't find any hands in what you pasted. Try one hand per line like: AKo BTN raise won 25"}
    if len(hands) > 500:
        return {"error": "That's more than 500 hands. Import in smaller batches."}
    try:
        return commit_import(uid, units, label, text, source, hands)
    except Exception as exc:
        discord_ping(f"import hands: {exc}")
        return {"error": str(exc)}

def commit_import(user_id, units, label, text, source, hands):
    profit = 0.0
    resolved = 0
    for h in hands:
        if h.get("result") in ("won", "lost") and h.get("amount") is not None:
            profit += h["amount"] if h["result"] == "won" else -h["amount"]
            resolved += 1
    profit = round(profit, 2) if resolved else None
    now = datetime.now(timezone.utc).isoformat()
    sid = supabase.table("sessions").insert({
        "user_id": user_id, "units": units, "status": "closed", "label": label,
        "profit": profit, "cashout": None, "created_at": now, "closed_at": now
    }).execute().data[0]["id"]
    rows = []
    for h in hands:
        rows.append({
            "user_id": user_id, "session_id": sid, "hand": h["hand"],
            "position": h.get("position"), "player_action": h.get("action"),
            "result": h.get("result"), "amount": h.get("amount"),
            "input": text[:1000] if text else f"Imported {source or 'hand'} history",
            "reply": f"Imported from {source or 'hand history'}.",
        })
    supabase.table("messages").insert(rows).execute()
    return {"ok": True, "session_id": sid, "hands": len(hands), "profit": profit, "units": units, "resolved": resolved, "source": source}

def _strip_data_uri(b64):
    b64 = (b64 or "").strip()
    if b64.startswith("data:"):
        if "," in b64:
            b64 = b64.split(",", 1)[1]
    return b64.replace(" ", "+")

@app.post("/api/import/screenshot")
async def import_screenshot(req: Request):
    uid, email = auth_identity(req)
    if not uid:
        return {"error": "unauthorized"}
    ent = entitlement(uid, email)
    if not (ent.get("limits") or {}).get("import"):
        return {"error": "Importing hand histories is a Pro feature. Upgrade to unlock it.", "paywall": "import"}
    try:
        body = await req.json()
    except Exception:
        return {"error": "bad request"}
    raw_uri = str(body.get("image") or "")
    b64 = _strip_data_uri(raw_uri)
    if not b64:
        return {"error": "No image received."}
    try:
        raw_img = base64.b64decode(b64)
    except Exception:
        pad = b64 + "=" * (-len(b64) % 4)
        try:
            raw_img = base64.b64decode(pad)
        except Exception:
            return {"error": "Could not read that image."}
    if not raw_img:
        return {"error": "Could not read that image."}
    if len(raw_img) > 9_000_000:
        return {"error": "Image is too large. Use a smaller screenshot."}
    mime = "image/png" if raw_uri.startswith("data:image/png") else "image/jpeg"
    prompt = ("Transcribe the poker hand history in this image EXACTLY, verbatim, as plain text: "
              "card hands, positions, actions, and dollar amounts, keeping every line break and number. "
              "If the image instead shows a session or profit summary (like 'Won $50 tonight' or a cashier/"
              "results screen), transcribe those figures too. Output ONLY the transcribed text - no commentary, "
              "no markdown, no headers.")
    try:
        text = groq_vision_text(b64, prompt, mime)
    except Exception as exc:
        discord_ping(f"screenshot vision: {exc}")
        return {"error": "Could not read the image. Try a sharper screenshot."}
    text = (text or "").strip()
    if not text:
        return {"error": "Could not read the image. Try a sharper screenshot."}
    source = str(body.get("source") or "").strip().lower()
    label = str(body.get("label") or "").strip()[:40] or None
    units = str(body.get("units") or ("chips" if source == "offsuit" else "dollars")).lower()
    if units not in ("dollars", "bb", "chips"):
        units = "dollars"
    hands = parse_hand_text(text, source)
    if hands:
        if len(hands) > 500:
            return {"error": "That's more than 500 hands. Import in smaller batches."}
        try:
            return commit_import(uid, units, label, text, source, hands)
        except Exception as exc:
            discord_ping(f"screenshot commit: {exc}")
            return {"error": str(exc)}
    fall = None
    for ln in text.splitlines():
        low = ln.lower()
        if re.search(r"\b(won|lost|profit|made|net)\b", low):
            nums = _nums(ln)
            if nums:
                fall = nums[0]
                if "lost" in low or "loss" in low:
                    fall = -abs(fall)
                break
        m = re.search(r"([+-])\s*\$?\s*(\d+(?:\.\d+)?)", ln)
        if m:
            fall = float(m.group(2)) if m.group(1) == "+" else -float(m.group(2))
            break
    if fall is not None and abs(fall) < 1_000_000_000:
        now = datetime.now(timezone.utc).isoformat()
        try:
            sid = supabase.table("sessions").insert({
                "user_id": uid, "units": units, "status": "closed", "label": label,
                "profit": round(fall, 2), "cashout": None, "created_at": now, "closed_at": now
            }).execute().data[0]["id"]
            return {"ok": True, "session_id": sid, "hands": 0, "profit": round(fall, 2), "units": units, "resolved": 1, "source": "screenshot", "summary": True}
        except Exception as exc:
            discord_ping(f"screenshot sum: {exc}")
            return {"error": str(exc)}
    return {"error": "Couldn't find hands or a profit figure in that screenshot. Try a clearer image of the hand history."}

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_ROLE_PREMIUM = os.environ.get("DISCORD_ROLE_PREMIUM", "")
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID") or "1549096373977354271"
DISCORD_FALLBACK_INVITE = "https://discord.gg/KB4rNwnea"
_widget_cache = {"at": 0.0, "data": None}

@app.get("/api/discord/widget")
async def discord_widget(req: Request):
    if time.time() - _widget_cache["at"] < 60 and _widget_cache["data"] is not None:
        return _widget_cache["data"]
    try:
        wh = urllib.request.Request(f"https://discord.com/api/guilds/{DISCORD_GUILD_ID}/widget.json",
                                   headers={"User-Agent": USER_AGENT})
        with urllib.request.urlopen(wh, timeout=10) as r:
            data = json.loads(r.read().decode())
        result = {"ok": True, "name": data.get("name") or "", "presence_count": data.get("presence_count") or 0,
                  "invite": data.get("instant_invite") or DISCORD_FALLBACK_INVITE}
    except Exception:
        result = {"ok": False, "invite": DISCORD_FALLBACK_INVITE}
    _widget_cache["at"] = time.time()
    _widget_cache["data"] = result
    return result

@app.get("/api/discord/config")
async def discord_config(req: Request):
    return {"client_id": DISCORD_CLIENT_ID, "enabled": bool(DISCORD_CLIENT_ID and DISCORD_CLIENT_SECRET)}

@app.get("/api/discord/link")
async def discord_link_status(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        res = supabase.table("discord_links").select("discord_id, discord_username").eq("user_id", uid).execute()
        row = res.data[0] if (res.data and res.data[0]) else None
        return {"linked": bool(row), "username": row.get("discord_username", "") if row else ""}
    except Exception as exc:
        discord_ping(f"discord link status: {exc}")
        return {"linked": False, "username": ""}

@app.post("/api/discord/link")
async def discord_link(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except:
        return {"error": "bad request"}
    code = body.get("code")
    redirect_uri = body.get("redirect_uri") or ""
    if not code:
        return {"error": "missing code"}
    if not DISCORD_CLIENT_ID or not DISCORD_CLIENT_SECRET:
        return {"error": "Discord is not configured yet."}
    try:
        form = urllib.parse.urlencode({
            "client_id": DISCORD_CLIENT_ID,
            "client_secret": DISCORD_CLIENT_SECRET,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
        }).encode()
        treq = urllib.request.Request("https://discord.com/api/oauth2/token", data=form, headers={"Content-Type": "application/x-www-form-urlencoded", "User-Agent": "AIHoldemCoach (https://aiholdemcoach.com, v1.0)"})
        try:
            tres = urllib.request.urlopen(treq, timeout=10)
        except urllib.error.HTTPError as http_exc:
            detail = http_exc.read().decode(errors="replace")[:300]
            discord_ping(f"discord link token exchange {http_exc.code}: {detail}")
            return {"error": f"Discord rejected the code ({http_exc.code}): {detail}"}
        tokens = json.loads(tres.read().decode())
        if not tokens.get("access_token"):
            return {"error": "Could not exchange code."}
        mreq = urllib.request.Request("https://discord.com/api/v10/users/@me", headers={"Authorization": "Bearer " + tokens["access_token"], "User-Agent": "AIHoldemCoach (https://aiholdemcoach.com, v1.0)"})
        me = json.loads(urllib.request.urlopen(mreq, timeout=10).read().decode())
        discord_id = me.get("id")
        if not discord_id:
            return {"error": "Could not fetch Discord user."}
        username = me.get("username", "DiscordUser")
        rel = supabase.table("discord_links")
        rel.delete().eq("user_id", uid).execute()
        rel.insert({"user_id": uid, "discord_id": discord_id, "discord_username": username}).execute()
        try:
            sub = supabase.table("subscriptions").select("tier,status").eq("user_id", uid).eq("tier", "premium").in_("status", ("active", "trial", "legacy")).limit(1).execute()
            if sub.data:
                assign_premium_role(discord_id)
        except Exception:
            pass
        return {"ok": True, "username": username}
    except Exception as exc:
        discord_ping(f"discord link exception: {exc}")
        return {"error": "Discord linking failed."}

@app.post("/api/discord/share")
async def discord_share(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    webhook = os.environ.get("DISCORD_SHARE_WEBHOOK_URL", "")
    if not webhook:
        return {"error": "Share webhook not configured."}
    try:
        body = await req.json()
    except:
        body = {}
    tz_off = int(body.get("tz") or 0)
    try:
        sres = supabase.table("sessions").select("id, profit, cashout, created_at, label, units").eq("user_id", uid).eq("status", "closed").order("closed_at", desc=True).limit(1).execute()
        sess = sres.data[0] if (sres.data and sres.data[0]) else None
        if not sess:
            return {"error": "No completed session to share."}
        u = sess.get("units") or "dollars"
        unit_sym = "$" if u == "dollars" else ""
        unit_sfx = "" if u == "dollars" else ("bb" if u == "bb" else " chips")
        hands_res = supabase.table("messages").select("hand, result, player_action").eq("session_id", sess["id"]).execute()
        hands = [h for h in (hands_res.data or []) if h.get("hand")]
        hand_count = len(hands)
        plays = [h for h in hands if h.get("player_action") != "fold"]
        play_count = len(plays)
        won_count = len([h for h in plays if h.get("result") == "won"])
        buyin_total = session_buyin_total(sess["id"])
        p = sess.get("profit")
        pstr = f"{'+' if p >= 0 else ''}{p:.2f}" if p is not None else "0.00"
        c = supabase.table("profiles").select("username").eq("user_id", uid).execute()
        username = (c.data[0] or {}).get("username", "Player") if c.data else "Player"
        created = sess.get("created_at", "")
        try:
            local_dt = datetime.fromisoformat(str(created).replace("Z", "+00:00")).astimezone(timezone(timedelta(minutes=-tz_off)))
            date_str = local_dt.strftime("%a, %b %-d")
        except Exception:
            date_str = ""
        lines = []
        label = sess.get("label")
        if label:
            lines.append(f"**{label}**")
        header = username
        if date_str:
            header += f" · {date_str}"
        lines.append(header)
        lines.append(f"Profit: **{unit_sym}{pstr}{unit_sfx}** over **{hand_count} {'hand' if hand_count == 1 else 'hands'}**")
        stats = []
        if play_count > 0:
            stats.append(f"Win rate: **{won_count}/{play_count} ({won_count/play_count*100:.0f}%)**")
        if buyin_total and p is not None:
            stats.append(f"ROI: **{p/buyin_total*100:.0f}%**")
        if stats:
            lines.append(" · ".join(stats))
        if buyin_total:
            lines.append(f"Bought in: **{unit_sym}{buyin_total:.2f}{unit_sfx}**")
        lines.append("· AI Holdem Coach")
        lres = supabase.table("discord_links").select("discord_id").eq("user_id", uid).execute()
        if lres.data and lres.data[0] and lres.data[0].get("discord_id"):
            lines[-1] += f" <@{lres.data[0]['discord_id']}>"
        msg = "\n".join(lines)
        payload = urllib.request.Request(webhook, data=json.dumps({"content": msg}).encode(), headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
        try:
            urllib.request.urlopen(payload, timeout=10)
        except urllib.error.HTTPError as he:
            discord_ping(f"discord share {he.code} {he.reason}: {msg[:80]}")
            code = he.code
            if code in (403, 404):
                return {"error": "Discord rejected the share — the share webhook looks out of date. Recreate it in your Discord server and check the app's Discord setup."}
            return {"error": f"Discord didn't accept the share ({code}). Try again in a minute."}
        return {"ok": True}
    except Exception as exc:
        discord_ping(f"discord share: {exc}")
        return {"error": "Could not post to Discord right now. Try again in a minute."}

def ensure_profile(user_id):
    try:
        res = supabase.table("profiles").select("user_id, username").eq("user_id", user_id).execute()
        rows = getattr(res, "data", None) or []
        if rows and rows[0].get("username"):
            return {"user_id": user_id, "username": rows[0]["username"]}
    except:
        pass
    username = "player-" + user_id[:8]
    try:
        supabase.table("profiles").insert({"user_id": user_id, "username": username}).execute()
    except:
        pass
    return {"user_id": user_id, "username": username}

def ensure_bankroll(user_id):
    try:
        res = supabase.table("bankrolls").select("user_id").eq("user_id", user_id).execute()
        if not (res.data or []):
            supabase.table("bankrolls").insert({"user_id": user_id, "amount": 0}).execute()
    except Exception as exc:
        discord_ping(f"ensure_bankroll: {exc}")

def credit_bankroll(user_id, profit):
    if profit is None:
        return
    try:
        ensure_bankroll(user_id)
        res = supabase.table("bankrolls").select("amount").eq("user_id", user_id).execute()
        current = float((res.data[0] or {}).get("amount") or 0) if (res.data or []) else 0
        supabase.table("bankrolls").update({"amount": round(current + float(profit), 2)}).eq("user_id", user_id).execute()
    except Exception as exc:
        discord_ping(f"credit_bankroll: {exc}")

def revert_bankroll(user_id, profit):
    if profit is None:
        return
    try:
        ensure_bankroll(user_id)
        res = supabase.table("bankrolls").select("amount").eq("user_id", user_id).execute()
        current = float((res.data[0] or {}).get("amount") or 0) if (res.data or []) else 0
        supabase.table("bankrolls").update({"amount": round(current - float(profit), 2)}).eq("user_id", user_id).execute()
    except Exception as exc:
        discord_ping(f"revert_bankroll: {exc}")

@app.get("/api/bankroll")
async def bankroll_get(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        ensure_bankroll(uid)
        res = supabase.table("bankrolls").select("amount, goal").eq("user_id", uid).execute()
        row = res.data[0] if (res.data and res.data[0]) else {"amount": 0, "goal": None}
        return {"amount": float(row.get("amount") or 0), "goal": row.get("goal")}
    except Exception as exc:
        discord_ping(f"bankroll get: {exc}")
        return {"amount": 0, "goal": None}

@app.post("/api/bankroll")
async def bankroll_set(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except:
        return {"error": "bad request"}
    updates = {}
    if "amount" in body:
        try:
            updates["amount"] = round(float(body["amount"]), 2)
        except:
            return {"error": "amount must be a number"}
    if "goal" in body:
        g = body["goal"]
        if g in ("", None):
            updates["goal"] = None
        else:
            try:
                updates["goal"] = round(float(g), 2)
            except:
                return {"error": "goal must be a number"}
    if not updates:
        return {"error": "nothing to update"}
    try:
        ensure_bankroll(uid)
        supabase.table("bankrolls").update(updates).eq("user_id", uid).execute()
        res = supabase.table("bankrolls").select("amount, goal").eq("user_id", uid).execute()
        row = res.data[0] if (res.data and res.data[0]) else {"amount": 0, "goal": None}
        return {"ok": True, "amount": float(row.get("amount") or 0), "goal": row.get("goal")}
    except Exception as exc:
        discord_ping(f"bankroll set: {exc}")
        return {"error": "Could not update bankroll."}

def get_pair_rows(a, b):
    try:
        res = supabase.table("friends").select("id, user_id, friend_id, status").or_(
            f"user_id.eq.{a},friend_id.eq.{a}"
        ).execute()
    except:
        return []
    return [r for r in (res.data or [])
            if (r["user_id"] == a and r["friend_id"] == b) or (r["user_id"] == b and r["friend_id"] == a)]

def are_friends(a, b):
    return any(r.get("status") == "accepted" for r in get_pair_rows(a, b))

def my_friend_ids(user_id):
    try:
        res = supabase.table("friends").select("user_id, friend_id, status").or_(
            f"user_id.eq.{user_id},friend_id.eq.{user_id}"
        ).execute()
    except:
        return []
    ids = []
    for r in (res.data or []):
        other = r["friend_id"] if r["user_id"] == user_id else r["user_id"]
        if r.get("status") == "accepted" and other != user_id and other not in ids:
            ids.append(other)
    return ids

def usernames_for(user_ids):
    if not user_ids:
        return {}
    try:
        res = supabase.table("profiles").select("user_id, username").in_("user_id", user_ids).execute()
        return {r["user_id"]: r.get("username") for r in (res.data or [])}
    except:
        return {}

def session_stats(user_id, since=None):
    rows = []
    try:
        q = supabase.table("sessions").select("id, profit, cashout, units, created_at").eq("user_id", user_id).eq("status", "closed")
        if since:
            q = q.gte("created_at", since)
        res = q.order("created_at", desc=True).execute()
        rows = list(res.data or [])
    except Exception:
        try:
            q = supabase.table("sessions").select("id, profit, cashout, created_at").eq("user_id", user_id).eq("status", "closed")
            if since:
                q = q.gte("created_at", since)
            res = q.order("created_at", desc=True).execute()
            rows = list(res.data or [])
        except Exception:
            pass
    dollar_rows = [r for r in rows if (r.get("units") or "dollars") == "dollars"]
    profits = [s.get("profit") for s in dollar_rows if s.get("profit") is not None]
    nights = len(profits)
    total = sum(profits)
    wins = sum(1 for p in profits if p > 0)
    streak = 0
    for p in profits:
        if p > 0:
            streak += 1
        else:
            break
    total_buyins = 0.0
    cashouts = []
    if dollar_rows:
        session_ids = {row["id"] for row in dollar_rows}
        try:
            bres = supabase.table("buyins").select("amount, session_id").in_("session_id", [r["id"] for r in dollar_rows]).execute()
            for r in (bres.data or []):
                if r.get("session_id") in session_ids:
                    total_buyins += r.get("amount") or 0
        except:
            pass
        cashouts = [s.get("cashout") for s in dollar_rows if s.get("cashout") is not None]
    roi = round(total / total_buyins * 100, 1) if total_buyins else None
    return {
        "nights": nights,
        "total_profit": round(total, 2),
        "win_rate": round(wins / nights * 100) if nights else None,
        "avg_profit": round(total / nights, 2) if nights else None,
        "best_night": round(max(profits), 2) if nights else None,
        "streak": streak,
        "total_buyins": round(total_buyins, 2),
        "total_cashouts": round(sum(cashouts), 2),
        "roi": roi,
    }

@app.get("/api/profile")
async def profile_endpoint(req: Request):
    user_id, email = auth_identity(req)
    if not user_id:
        return {"error": "unauthorized"}
    username = (req.query_params.get("username") or "").strip()
    if not username:
        return {"error": "missing username"}
    try:
        res = supabase.table("profiles").select("user_id, username").eq("username", username).execute()
    except:
        res = None
    rows = getattr(res, "data", None) or []
    if not rows:
        return {"error": "user not found"}
    target = rows[0]["user_id"]
    ent = entitlement(user_id, email)
    since = None
    hdays = (ent.get("limits") or {}).get("history_days")
    if hdays:
        since = (datetime.now(timezone.utc) - timedelta(days=hdays)).isoformat()
    if target == user_id:
        return {"profile": {"username": username, "stats": session_stats(target, since), "you": True}}
    if not are_friends(user_id, target):
        return {"error": "not friends"}
    return {"profile": {"username": username, "stats": session_stats(target)}}

@app.post("/api/friend-request")
async def friend_request_endpoint(req: Request):
    user_id = auth_user_id(req)
    if not user_id:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except:
        return {"error": "bad request"}
    username = (body.get("username") or "").strip()
    if not username:
        return {"error": "missing username"}
    try:
        res = supabase.table("profiles").select("user_id, username").eq("username", username).execute()
    except:
        res = None
    rows = getattr(res, "data", None) or []
    if not rows:
        return {"error": "user not found"}
    target = rows[0]["user_id"]
    if target == user_id:
        return {"error": "can't add yourself"}
    pair = get_pair_rows(user_id, target)
    if pair:
        if any(r.get("status") == "accepted" for r in pair):
            return {"error": "already friends"}
        return {"error": "request already exists"}
    try:
        supabase.table("friends").insert({"user_id": user_id, "friend_id": target, "status": "pending"}).execute()
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True}

@app.post("/api/friend-action")
async def friend_action_endpoint(req: Request):
    user_id = auth_user_id(req)
    if not user_id:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except:
        return {"error": "bad request"}
    action = body.get("action")
    friend_id = body.get("friend_id")
    if action not in ("accept", "remove") or not friend_id:
        return {"error": "bad request"}
    pair = get_pair_rows(user_id, friend_id)
    if not pair:
        return {"error": "not found"}
    if action == "accept":
        if not any(r.get("user_id") == friend_id and r.get("status") == "pending" for r in pair):
            if any(r.get("status") == "accepted" for r in pair):
                return {"ok": True}
            return {"error": "no request to accept"}
        try:
            for r in pair:
                supabase.table("friends").update({"status": "accepted"}).eq("id", r["id"]).execute()
            if not any(r.get("user_id") == user_id for r in pair):
                supabase.table("friends").insert({"user_id": user_id, "friend_id": friend_id, "status": "accepted"}).execute()
        except Exception as e:
            return {"error": str(e)}
        return {"ok": True}
    try:
        for r in pair:
            supabase.table("friends").delete().eq("id", r["id"]).execute()
    except Exception as e:
        return {"error": str(e)}
    return {"ok": True}

@app.get("/api/friends")
async def friends_endpoint(req: Request):
    user_id = auth_user_id(req)
    if not user_id:
        return {"error": "unauthorized"}
    me = ensure_profile(user_id)
    try:
        res = supabase.table("friends").select("user_id, friend_id, status").or_(
            f"user_id.eq.{user_id},friend_id.eq.{user_id}"
        ).execute()
    except:
        res = None
    friend_ids = []
    incoming_ids = []
    outgoing_ids = []
    for r in ((res.data or []) if res else []):
        other = r["friend_id"] if r["user_id"] == user_id else r["user_id"]
        if other == user_id:
            continue
        if r.get("status") == "accepted":
            if other not in friend_ids:
                friend_ids.append(other)
        elif r.get("user_id") == user_id:
            if other not in outgoing_ids:
                outgoing_ids.append(other)
        elif other not in incoming_ids:
            incoming_ids.append(other)
    names = usernames_for(friend_ids + incoming_ids + outgoing_ids)
    friends = [{"user_id": fid, "username": names.get(fid, "?"), "stats": session_stats(fid)} for fid in friend_ids]
    incoming = [{"user_id": uid, "username": names.get(uid, "?")} for uid in incoming_ids]
    outgoing = [{"user_id": uid, "username": names.get(uid, "?")} for uid in outgoing_ids]
    return {
        "username": me["username"],
        "stats": session_stats(user_id),
        "friends": friends,
        "incoming": incoming,
        "outgoing": outgoing,
    }

@app.get("/api/leaderboard")
async def leaderboard_endpoint(req: Request):
    user_id = auth_user_id(req)
    if not user_id:
        return {"error": "unauthorized"}
    rng = (req.query_params.get("range") or "all").lower()
    since = None
    now = datetime.now(timezone.utc)
    if rng == "week":
        since = (now - timedelta(days=7)).isoformat()
    elif rng == "month":
        since = (now - timedelta(days=30)).isoformat()
    elif rng == "ytd":
        since = now.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0).isoformat()
    me = ensure_profile(user_id)
    names = usernames_for([user_id] + my_friend_ids(user_id))
    rows = []
    for uid in [user_id] + my_friend_ids(user_id):
        stats = session_stats(uid, since=since)
        if stats["nights"] == 0:
            continue
        rows.append({"username": names.get(uid, "?"), "you": uid == user_id, **stats})
    rows.sort(key=lambda r: r["total_profit"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return {"username": me["username"], "leaderboard": rows}

def _closed_dollars(user_id, since=None, until=None):
    try:
        q = supabase.table("sessions").select("id, profit, cashout, units, created_at").eq("user_id", user_id).eq("status", "closed")
        if since:
            q = q.gte("created_at", since)
        if until:
            q = q.lt("created_at", until)
        res = q.order("created_at", desc=True).execute()
        rows = list(res.data or [])
    except Exception:
        rows = []
    return [r for r in rows if (r.get("units") or "dollars") == "dollars"]

@app.get("/api/weekly")
async def weekly_endpoint(req: Request):
    user_id = auth_user_id(req)
    if not user_id:
        return {"error": "unauthorized"}
    now = datetime.now(timezone.utc)
    week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
    prev_start = week_start - timedelta(days=7)
    week = _closed_dollars(user_id, since=week_start.isoformat(), until=now.isoformat())
    prev = _closed_dollars(user_id, since=prev_start.isoformat(), until=week_start.isoformat())
    def agg(rows):
        profits = [r.get("profit") for r in rows if r.get("profit") is not None]
        if not rows:
            return {"nights": 0, "profit": 0.0, "win_rate": None, "avg": None, "best": None, "worst": None}
        total = sum(profits)
        wins = sum(1 for p in profits if p > 0)
        best = max(profits)
        worst = min(profits)
        best_s = next((r for r in rows if r.get("profit") == best), None)
        worst_s = next((r for r in rows if r.get("profit") == worst), None)
        return {
            "nights": len(rows),
            "profit": round(total, 2),
            "win_rate": round(wins / len(profits) * 100) if profits else None,
            "avg": round(total / len(rows), 2),
            "best": {"profit": round(best, 2), "date": best_s.get("created_at")} if best_s else None,
            "worst": {"profit": round(worst, 2), "date": worst_s.get("created_at")} if worst_s else None,
        }
    wk = agg(week)
    pv = agg(prev)
    hands = []
    week_sids = {r["id"] for r in week}
    if week_sids:
        try:
            hres = supabase.table("messages").select("session_id, hand, position, player_action, result, amount").in_("session_id", list(week_sids)).execute()
            hands = [h for h in (hres.data or []) if h.get("hand") and h.get("session_id") in week_sids]
        except Exception:
            hands = []
    wk["hands"] = len(hands)
    win_hands = [h for h in hands if str(h.get("result") or "").lower() in ("won", "win", "w") and h.get("amount") is not None]
    loss_hands = [h for h in hands if str(h.get("result") or "").lower() in ("lost", "lose", "l") and h.get("amount") is not None]
    def desc(h):
        parts = [h.get("hand") or "?", h.get("position") or "", h.get("player_action") or ""]
        if h.get("amount") is not None:
            parts.append("$" + str(h.get("amount")))
        return " ".join(x for x in parts if x)
    wk["biggest_win"] = desc(max(win_hands, key=lambda h: h["amount"])) if win_hands else None
    wk["biggest_loss"] = desc(max(loss_hands, key=lambda h: h["amount"])) if loss_hands else None
    leak = None
    if loss_hands:
        acts = {}
        for h in loss_hands:
            a = (h.get("player_action") or "").lower()
            if a:
                acts[a] = acts.get(a, 0) + 1
        act, cnt = (max(acts.items(), key=lambda x: x[1]) if acts else (None, 0))
        if act in ("fold", "call", "raise", "bet", "check", "all-in"):
            leak = f"Biggest leak: {act}s lost the most this week ({cnt} hands). Keep them tight."
        else:
            leak = f"{len(loss_hands)} losing hands logged this week."
    elif hands:
        fold_n = sum(1 for h in hands if (h.get("player_action") or "").lower() == "fold")
        fr = round(fold_n / len(hands) * 100)
        if fr >= 50:
            leak = f"You folded {fr}% of hands this week - maybe a little tight."
        elif len(hands) < 5:
            leak = "Log more hands per session for sharper leak notes."
    wk["leak"] = leak
    return {"ok": True, "week_start": week_start.isoformat(), "week": wk, "prev": {"nights": pv["nights"], "profit": pv["profit"]}}

@app.post("/api/username")
async def username_endpoint(req: Request):
    user_id = auth_user_id(req)
    if not user_id:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except:
        return {"error": "bad request"}
    username = (body.get("username") or "").strip().lower()
    if not re.fullmatch(r"[a-z0-9_]{3,20}", username):
        return {"error": "usernames must be 3-20 letters, numbers, or underscores"}
    try:
        existing = supabase.table("profiles").select("user_id").eq("username", username).execute()
    except:
        existing = None
    rows = getattr(existing, "data", None) or []
    if rows and rows[0].get("user_id") != user_id:
        return {"error": "username taken"}
    try:
        supabase.table("profiles").upsert({"user_id": user_id, "username": username}).execute()
        return {"ok": True, "username": username}
    except Exception as e:
        return {"error": str(e)}

@app.post("/api/resolve-login")
async def resolve_login_endpoint(req: Request):
    try:
        body = await req.json()
    except:
        return {"error": "bad request"}
    identifier = (body.get("identifier") or "").strip().lower()
    if not identifier:
        return {"error": "missing identifier"}
    if "@" in identifier:
        return {"email": identifier}
    try:
        res = supabase.table("profiles").select("user_id").eq("username", identifier).execute()
    except:
        return {"error": "user not found"}
    rows = getattr(res, "data", None) or []
    if not rows:
        return {"error": "user not found"}
    try:
        user = supabase.auth.admin.get_user_by_id(rows[0]["user_id"])
        email = getattr(user, "user", None).email if user else None
    except:
        email = None
    if not email:
        return {"error": "user not found"}
    return {"email": email}

@app.get("/api/usage")
async def usage_endpoint(req: Request):
    uid, email = auth_identity(req)
    if not uid:
        return {"error": "unauthorized"}
    ent = entitlement(uid, email)
    counts = {"chats": 0, "coach": 0, "track": 0, "recap": 0}
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        r = supabase.table("chat_usage").select("chats, coach, track, recap").eq("day", today).eq("user_id", uid).execute()
        if r.data and r.data[0]:
            row = r.data[0]
            counts = {"chats": row.get("chats") or 0, "coach": row.get("coach") or 0, "track": row.get("track") or 0, "recap": row.get("recap") or 0}
    except Exception:
        pass
    return {"tier": ent["tier"], "plan": ent["plan"], "limits": ent["limits"], "counts": counts, "trial_days": TRIAL_DAYS, "trial": ent.get("trial") or {"active": False, "days_left": 0, "ended": False}}

@app.post("/api/support")
async def support_ticket(req: Request):
    uid, email = auth_identity(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except Exception:
        return {"error": "bad request"}
    topic = str(body.get("topic") or "other").strip()[:40]
    message = str(body.get("message") or "").strip()
    if not message or len(message) < 2 or len(message) > 4000:
        return {"error": "Write a short message first."}
    tier = "free"
    try:
        tier = entitlement(uid, email).get("tier", "free")
    except Exception:
        pass
    try:
        res = supabase.table("support_tickets").insert({"user_id": uid, "topic": topic, "message": message, "tier": tier, "email": email}).execute()
        tid = res.data[0].get("id") if (res.data and res.data[0]) else None
    except Exception as exc:
        discord_ping(f"support insert: {exc}")
        return {"error": "Could not save your ticket right now."}
    webhook = os.environ.get("DISCORD_SUPPORT_WEBHOOK_URL", "")
    if webhook:
        topic_label = topic.replace("_", " ").title()
        content = (f"**Support ticket #{tid}** · {topic_label}\n"
                   f"User: {email or uid}\n"
                   f"Tier: {tier}\n"
                   f"```{message[:1500]}```")

        def post():
            try:
                payload = urllib.request.Request(webhook, data=json.dumps({"content": content}).encode(), headers={"Content-Type": "application/json", "User-Agent": USER_AGENT})
                urllib.request.urlopen(payload, timeout=10)
            except Exception:
                pass
        threading.Thread(target=post, daemon=True).start()
    return {"ok": True, "ticket": tid}

def user_discord_ids(uid):
    try:
        res = supabase.table("discord_links").select("discord_id").eq("user_id", uid).execute()
        return [r["discord_id"] for r in (res.data or []) if r.get("discord_id")]
    except Exception:
        return []

def assign_premium_role(discord_id):
    guild = DISCORD_GUILD_ID
    role = DISCORD_ROLE_PREMIUM
    if not (guild and DISCORD_BOT_TOKEN and role) or not discord_id:
        return False
    try:
        req = urllib.request.Request(
            f"https://discord.com/api/v10/guilds/{guild}/members/{discord_id}/roles/{role}",
            data=b"", method="PUT",
            headers={"Authorization": f"Bot {DISCORD_BOT_TOKEN}", "Content-Length": "0", "User-Agent": USER_AGENT})
        with urllib.request.urlopen(req, timeout=10) as res:
            return res.status in (200, 204)
    except Exception as exc:
        discord_ping(f"premium role assign: {exc}")
        return False

@app.post("/api/stripe/checkout")
async def stripe_checkout(req: Request):
    uid, email = auth_identity(req)
    if not uid:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except Exception:
        body = {}
    plan = str(body.get("plan") or "").lower()
    price = None
    if plan == "premium":
        price = STRIPE_PREMIUM_PRICE
    elif plan == "pro":
        price = STRIPE_PRO_PRICE
    if not price:
        return {"error": "Billing isn't set up yet — check back soon."}
    session = stripe_api("POST", "checkout/sessions", form=True, payload={
        "mode": "subscription",
        "customer_email": email or None,
        "client_reference_id": uid,
        "metadata[user_id]": uid,
        "metadata[plan]": plan,
        "line_items[0][price]": price,
        "line_items[0][quantity]": "1",
        "success_url": APP_URL + "/?plan=success",
        "cancel_url": APP_URL + "/",
    })
    if not session.get("url"):
        return {"error": session.get("error") or "Could not start checkout right now."}
    return {"url": session["url"]}

@app.post("/api/stripe/portal")
async def stripe_portal(req: Request):
    uid, _ = auth_identity(req)
    if not uid:
        return {"error": "unauthorized"}
    customer_id = None
    try:
        r = supabase.table("subscriptions").select("stripe_customer_id").eq("user_id", uid).execute()
        if r.data and r.data[0].get("stripe_customer_id"):
            customer_id = r.data[0]["stripe_customer_id"]
    except Exception:
        customer_id = None
    if not customer_id:
        return {"error": "No active subscription found for this account."}
    res = stripe_api("POST", "billing_portal/sessions", form=True, payload={
        "customer": customer_id,
        "return_url": APP_URL + "/",
    })
    if not res.get("url"):
        return {"error": res.get("error") or "Could not open billing settings right now."}
    return {"url": res["url"]}

@app.post("/api/stripe/webhook")
async def stripe_webhook(req: Request):
    raw = await req.body()
    sig = req.headers.get("stripe-signature", "")
    if not STRIPE_WEBHOOK_SECRET:
        return JSONResponse(status_code=503, content={"error": "webhook not configured"})
    if not verify_stripe_signature(raw, sig):
        return JSONResponse(status_code=400, content={"error": "bad signature"})
    try:
        event = json.loads(raw)
        typ = event.get("type")
        obj = event.get("data", {}).get("object", {})
        if typ in ("checkout.session.completed", "checkout.session.async_payment_succeeded"):
            if obj.get("mode") != "subscription":
                return {"ok": True}
            uid = (obj.get("metadata") or {}).get("user_id") or obj.get("client_reference_id")
            sub_id = obj.get("subscription")
            customer_id = obj.get("customer")
            status = "active"
            period_end = None
            if sub_id:
                sub = stripe_api("GET", "subscriptions/" + sub_id, with_api_key=True)
                status = sub.get("status") or "active"
                pe = sub.get("current_period_end")
                if pe:
                    period_end = datetime.fromtimestamp(float(pe), timezone.utc).isoformat()
            price_id = ""
            items = obj.get("line_items") or {}
            item_data = items.get("data") or []
            if item_data:
                price_id = ((item_data[0].get("price") or {}).get("id") or "")
            plan = "premium" if price_id == STRIPE_PREMIUM_PRICE else ("pro" if price_id == STRIPE_PRO_PRICE else (obj.get("metadata") or {}).get("plan", "pro"))
            if uid:
                upsert_subscription(uid, plan, status, period_end, sub_id, customer_id)
                try:
                    cd = obj.get("customer_details") or {}
                    cu_email = cd.get("email") or (obj.get("metadata") or {}).get("email") or ""
                    amt = obj.get("amount_total")
                    amt_str = f"${amt/100:,.2f} " if amt else ""
                    discord_ping(f"New subscriber - {plan.upper()} | {cu_email or 'no email'} | {amt_str}")
                except Exception:
                    pass
                if plan == "premium":
                    for did in user_discord_ids(uid):
                        assign_premium_role(did)
        elif typ == "customer.subscription.updated":
            sub_id = obj.get("id") or ""
            uid = find_user_by_subscription(sub_id)
            if uid:
                status = obj.get("status") or "active"
                pe = obj.get("current_period_end")
                period_end = datetime.fromtimestamp(float(pe), timezone.utc).isoformat() if pe else None
                price_id = ""
                items = obj.get("items") or {}
                item_data = items.get("data") or []
                if item_data:
                    price_id = ((item_data[0].get("price") or {}).get("id") or "")
                plan = "premium" if price_id == STRIPE_PREMIUM_PRICE else "pro"
                mapped = {"active": "active", "trialing": "active", "past_due": "past_due", "unpaid": "past_due", "incomplete": "incomplete", "paused": "past_due"}
                if status in mapped:
                    upsert_subscription(uid, plan, mapped[status], period_end, sub_id, obj.get("customer"))
                elif status in ("canceled", "incomplete_expired"):
                    upsert_subscription(uid, "free", "canceled", period_end, sub_id, obj.get("customer"))
        elif typ == "customer.subscription.deleted":
            sub_id = obj.get("id") or ""
            uid = find_user_by_subscription(sub_id)
            if uid:
                upsert_subscription(uid, "free", "canceled", None, sub_id, obj.get("customer"))
    except Exception as exc:
        discord_ping(f"stripe webhook: {exc}")
        return JSONResponse(status_code=500, content={"error": str(exc)})
    return {"ok": True}

@app.post("/api/admin/set-tier")
async def admin_set_tier(req: Request):
    uid, email = auth_identity(req)
    if not uid or not email or email.lower() not in ADMIN_EMAILS:
        return {"error": "unauthorized"}
    try:
        body = await req.json()
    except Exception:
        return {"error": "bad request"}
    target = body.get("user_id") or uid
    tier = str(body.get("tier") or "").lower()
    if tier not in ("free", "pro", "premium", "legacy", "admin"):
        return {"error": "bad tier"}
    try:
        months = float(body.get("months") or 0)
    except (TypeError, ValueError):
        months = 0
    period_end = None
    if months and months > 0:
        period_end = (datetime.now(timezone.utc) + timedelta(days=30 * months)).isoformat()
    status = "legacy" if tier == "legacy" else ("none" if tier == "free" else "active")
    if not upsert_subscription(target, tier, status, period_end):
        return {"error": "Could not update tier."}
    return {"ok": True, "tier": tier}
