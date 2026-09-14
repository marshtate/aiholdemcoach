import os
import json
import re
import threading
import urllib.request
import urllib.parse
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
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
	groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
	supabase: Client = create_client(os.environ.get("SUPABASE_URL"),
									 os.environ.get("SUPABASE_SERVICE_KEY"),)
	evaluator = Evaluator()
	startup_ok = True
	startup_error = ""
except Exception as exc:
	startup_ok = False
	startup_error = str(exc)

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")

def discord_ping(text):
	if not DISCORD_WEBHOOK_URL:
		return
	def send():
		try:
			payload = json.dumps({"content": text}).encode()
			req = urllib.request.Request(DISCORD_WEBHOOK_URL, data=payload, headers={"Content-Type": "application/json"})
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

def log_hand(hand, position=None, action=None, result=None, amount=None, hands=None):
	if hands:
		row0 = hands[0]
		return json.dumps({"hands": hands, "hand": row0.get("hand"), "position": row0.get("position"), "action": row0.get("action"), "result": row0.get("result"), "amount": row0.get("amount")})
	return json.dumps({"hand": hand, "position": position, "action": action, "result": result, "amount": amount})

def close_session(profit=None, cashout=None):
	return json.dumps({"closed": True, "profit": profit, "cashout": cashout})

def record_buyin(amount):
	return json.dumps({"buyin": True, "amount": amount})

def get_or_create_session(user_id):
	try:
		result = supabase.table("sessions").select("id").eq("user_id", user_id).eq("status", "open").order("created_at", desc=True).limit(1).execute()
		if result.data and result.data[0]:
			return result.data[0]["id"]
		new = supabase.table("sessions").insert({"user_id": user_id}).execute()
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
{"type": "function", "function": {"name": "log_hand", "description": "Log a poker hand with action and optional result. If the player's message contains MULTIPLE hands (e.g. 'won AKo, then lost 77'), put ALL of them in the hands array at once - one object per hand.", "parameters": {"type": "object", "properties": {"hand": {"type": "string", "description": "The hand, e.g. AKo, 72s, JJ (only the ONE hand if there is only one)"}, "position": {"type": ["string", "null"], "description": "Optional position"}, "action": {"type": ["string", "null"], "description": "What the player did: fold, call, raise, check, all-in"}, "result": {"type": ["string", "null"], "description": "Optional: won or lost"}, "amount": {"type": ["number", "null"], "description": "Optional: amount won or lost"}, "hands": {"type": ["array", "null"], "items": {"type": "object", "properties": {"hand": {"type": "string"}, "position": {"type": ["string", "null"]}, "action": {"type": ["string", "null"]}, "result": {"type": ["string", "null"]}, "amount": {"type": ["number", "null"]}}, "required": ["hand"]}, "description": "Multiple hands at once: one object per hand. Use this whenever the message mentions more than one hand."}}, "required": []}}} ,
{"type": "function", "function": {"name": "close_session", "description": "Close the player's session with either their total profit or loss, OR their cashout amount. If the player says they were up/down X, pass profit (positive for profit, negative for loss). If they say they cashed out X, pass cashout.", "parameters": {"type": "object", "properties": {"profit": {"type": ["number", "null"], "description": "Total profit (positive) or loss (negative) in dollars"}, "cashout": {"type": ["number", "null"], "description": "Total amount cashed out at the end of the session in dollars"}}, "required": []}}},
{"type": "function", "function": {"name": "record_buyin", "description": "Record a buy-in or re-buy for the current session.", "parameters": {"type": "object", "properties": {"amount": {"type": "number", "description": "Dollar amount of this buy-in or re-buy"}}, "required": ["amount"]}}},
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

track_system = "You are a poker hand tracker. From the player's message, extract their hand, position, what they did, whether they won or lost, and how much - call log_hand with everything you find. If the message contains MORE THAN ONE hand (e.g. 'won with AKo, then lost with 77'), put EVERY hand into the hands array of a SINGLE log_hand call - one object per hand - and never skip any. Never drop a result or amount the player mentions. If they buy in or rebuy - 'bought in', 'buy-in', 'rebuy', 'loaded up', with an amount - call record_buyin with that amount. If they tell you their total for the night - profit or loss - call close_session with profit, positive for profit, negative for loss. If they tell you they cashed out or walked away with an amount, call close_session with cashout. If they say they're done - 'done', 'end session', 'that's it', 'I'm out' - do NOT close the session yet. Instead, ask them to confirm their total buy-in and total cash-out. Once they give you both numbers, call record_buyin with their total buy-in, then call close_session with cashout. If they say they're done with no numbers at all, close with cashout 0. Respond ONLY with the confirmation, e.g. 'Bought in for $5.' or 'Session closed - [+/-profit].' or 'Logged - AKo, won, $20. Logged - 77, lost, $10.' Never give advice. Never judge a hand's quality. If they don't state exact hole cards and this is a new conversation - no hand mentioned before - do NOT guess, respond 'What hand were you holding?'"

def build_system(mode, session=None):
	base = track_system if mode == "track" else coach_system
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
	elif session and session.get("hand") and mode == "track":
		hand = session["hand"]
		pos = session.get("position", "")
		base += f" CONTEXT - an earlier hand this player logged was {hand}"
		if pos: base += f" from {pos}"
		base += f". Only reuse {hand} when the player's message REPEATS it, or clearly continues that exact hand without naming any different cards. CRITICAL RULES: (1) If the message names ANY hole cards - e.g. AKo, 77, TT, QJ, 72s - those are NEW hands and you MUST log exactly those cards - never {hand} for them. (2) If several different hands are mentioned, log EVERY one in the hands array - never skip any. (3) Log every result and amount the player mentions next to a hand. (4) When new cards are named, base your log ENTIRELY on those cards and ignore {hand}."
	return {"role": "system", "content": base}

def format_track(parsed, session=None, closed=False, logged_hands=None, units="dollars"):
	if parsed.get("buyin"):
		return f"Bought in for {fmt_amount(parsed['amount'], units)}."
	if closed and (parsed.get("profit") is not None or parsed.get("cashout") is not None):
		if parsed.get("cashout") is not None and parsed.get("profit") is None:
			return f"Session closed - cashed out {fmt_amount(parsed['cashout'], units)}."
		p = parsed.get("profit", 0)
		extra = f" Cashed out {fmt_amount(parsed['cashout'], units)}." if parsed.get("cashout") is not None else ""
		return f"Session closed - {'+' if p >= 0 else ''}{p}.{extra}"
	if logged_hands:
		out = []
		for h in logged_hands:
			parts = [h.get("hand") or "?"]
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
    try:
        response = groq_client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages, tools=tools, tool_choice="auto")
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
                if isinstance(hs, list) and hs:
                    for h in hs:
                        if h.get("result") is not None:
                            h["result"] = "won" if str(h["result"]).lower() in ("won", "win", "w") else "lost"
                        logged_hands.append(h)
                elif parsed.get("hand"):
                    logged_hands.append(parsed)
            if tc.function.name == "record_buyin" and mode == "track":
                try:
                    sid = get_or_create_session(user_id)
                    if sid and args.get("amount") is not None:
                        supabase.table("buyins").insert({"session_id": sid, "user_id": user_id, "amount": args["amount"]}).execute()
                except Exception as exc:
                    discord_ping(f"record_buyin insert: {exc}")
            if tc.function.name == "close_session":
                closed = True
        if mode == "track":
            if closed and user_id:
                try:
                    sid = get_or_create_session(user_id)
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
        second = groq_client.chat.completions.create(model="openai/gpt-oss-120b", messages=clean)
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
            resp = groq_client.chat.completions.create(model="openai/gpt-oss-120b", messages=msgs)
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
    auth_header = req.headers.get("authorization", "")
    user_id = None
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        try:
            resp = supabase.auth.get_user(token)
            if resp and resp.user:
                user_id = resp.user.id
        except:
            pass
    if mode == "recap":
        if not user_id:
            return {"reply": "Sign in to recap a session."}
        reply, rid = recap_turn(user_input, user_id, body.get("session_id"))
        return {"reply": reply, "parsed": {}, "recap_session_id": rid}
    reply, parsed, session, tool_called, closed, logged_hands = run_pipeline(user_input, mode, user_id, body.get("units", "dollars"))
    if user_id and tool_called and not closed and not parsed.get("buyin"):
        batch = logged_hands if logged_hands else [parsed]
        if any(b.get("hand") for b in batch):
            try:
                session_id = get_or_create_session(user_id) if mode == "track" else None
                prev_hand = session.get("hand") if session else None
                single = len(batch) == 1
                for bh in batch:
                    row_hand = bh.get("hand") or prev_hand
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
    auth_header = req.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return {"error": "unauthorized"}
    token = auth_header[7:]
    try:
        resp = supabase.auth.get_user(token)
        if not resp or not resp.user:
            return {"error": "unauthorized"}
        user_id = resp.user.id
    except:
        return {"error": "unauthorized"}
    try:
        result = supabase.table("sessions").select("id, created_at, closed_at, profit, cashout, status").eq("user_id", user_id).order("created_at", desc=True).execute()
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
        result = supabase.table("messages").select("id, input, reply, hand, tier, position, player_action, result, amount, created_at").eq("user_id", user_id).order("created_at", desc=True).execute()
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

@app.get("/api/session")
async def session_detail(req: Request):
    uid = auth_user_id(req)
    if not uid:
        return {"error": "unauthorized"}
    sid = req.query_params.get("id")
    if not sid:
        return {"error": "missing id"}
    try:
        sres = supabase.table("sessions").select("id, created_at, closed_at, profit, cashout, status, label").eq("id", sid).eq("user_id", uid).execute()
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
        supabase.table("buyins").delete().eq("session_id", sid).eq("user_id", uid).execute()
        supabase.table("recap_messages").delete().eq("session_id", sid).eq("user_id", uid).execute()
        supabase.table("messages").delete().eq("session_id", sid).eq("user_id", uid).execute()
        supabase.table("sessions").delete().eq("id", sid).eq("user_id", uid).execute()
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

DISCORD_CLIENT_ID = os.environ.get("DISCORD_CLIENT_ID", "")
DISCORD_CLIENT_SECRET = os.environ.get("DISCORD_CLIENT_SECRET", "")

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
        sres = supabase.table("sessions").select("id, profit, cashout, created_at").eq("user_id", uid).eq("status", "closed").order("closed_at", desc=True).limit(1).execute()
        sess = sres.data[0] if (sres.data and sres.data[0]) else None
        if not sess:
            return {"error": "No completed session to share."}
        hands_res = supabase.table("messages").select("hand").eq("session_id", sess["id"]).execute()
        hand_count = len([h for h in (hands_res.data or []) if h.get("hand")])
        buyin_total = session_buyin_total(sess["id"])
        p = sess.get("profit")
        pstr = f"{'+' if p >= 0 else ''}{p:.2f}" if p is not None else "0.00"
        c = supabase.table("profiles").select("username").eq("user_id", uid).execute()
        username = (c.data[0] or {}).get("username", "Player") if c.data else "Player"
        msg = f"**{username}** tonight: **${pstr}** over **{hand_count} hands**"
        if buyin_total:
            msg += f", **${buyin_total:.2f}** bought in"
        msg += " · AI Holdem Coach"
        lres = supabase.table("discord_links").select("discord_id").eq("user_id", uid).execute()
        if lres.data and lres.data[0] and lres.data[0].get("discord_id"):
            msg += f" <@{lres.data[0]['discord_id']}>"
        payload = urllib.request.Request(webhook, data=json.dumps({"content": msg}).encode(), headers={"Content-Type": "application/json"})
        urllib.request.urlopen(payload, timeout=10)
        return {"ok": True}
    except Exception as exc:
        discord_ping(f"discord share: {exc}")
        return {"error": "Could not post to Discord."}

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

def session_stats(user_id):
    try:
        res = supabase.table("sessions").select("id, profit, cashout, created_at").eq("user_id", user_id).eq("status", "closed").order("created_at", desc=True).execute()
        rows = list(res.data or [])
        profits = [s.get("profit") for s in rows if s.get("profit") is not None]
    except:
        rows = []
        profits = []
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
    if rows:
        session_ids = {row["id"] for row in rows}
        try:
            bres = supabase.table("buyins").select("amount, session_id").in_("session_id", [r["id"] for r in rows]).execute()
            for r in (bres.data or []):
                if r.get("session_id") in session_ids:
                    total_buyins += r.get("amount") or 0
        except:
            pass
        cashouts = [s.get("cashout") for s in rows if s.get("cashout") is not None]
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
    user_id = auth_user_id(req)
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
    if target == user_id:
        return {"profile": {"username": username, "stats": session_stats(target), "you": True}}
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
    me = ensure_profile(user_id)
    names = usernames_for([user_id] + my_friend_ids(user_id))
    rows = []
    for uid in [user_id] + my_friend_ids(user_id):
        stats = session_stats(uid)
        if stats["nights"] == 0:
            continue
        rows.append({"username": names.get(uid, "?"), "you": uid == user_id, **stats})
    rows.sort(key=lambda r: r["total_profit"], reverse=True)
    for i, r in enumerate(rows):
        r["rank"] = i + 1
    return {"username": me["username"], "leaderboard": rows}

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