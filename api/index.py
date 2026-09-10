import os
import json
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
	os.environ.get("SUPABASE_SERVICE_KEY"))
	evaluator = Evaluator()
	startup_ok = True
	startup_error = ""
except Exception as e:
	startup_ok = False
	startup_error = str(e)

def evaluate_poker_hand(hero_cards, board_cards):
	hero = [Card.new(c) for c in hero_cards]
	board = [Card.new(c) for c in board_cards]
	score = evaluator.evaluate(board, hero)
	rank_class = evaluator.get_rank_class(score)
	rank_str = evaluator.class_to_string(rank_class)
	return json.dumps({"score": score, "hand_rank": rank_str})

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

def log_hand(hand, position=None, action=None, result=None, amount=None):
	tier_num = None
	if len(hand) == 2 or len(hand) == 3:
		try:
			c1 = hand[0] + "h"
			c2 = hand[1] + "d"
			tier_num = get_hand_tier(to_canonical(c1, c2))
		except Exception:
			pass
	tier_name = TIER_NAMES.get(tier_num, None) if tier_num else None
	return json.dumps({"hand": hand, "tier": tier_name, "position": position, "action": action, "result": result, "amount": amount})

tools = [
{"type": "function", "function": {"name": "evaluate_poker_hand", "description": "Evaluate a poker hand from hole cards and board cards. Use when the player provides a board.", "parameters": {"type": "object", "properties": {"hero_cards": {"type": "array", "items": {"type": "string"}}, "board_cards": {"type": "array", "items": {"type": "string"}}}, "required": ["hero_cards", "board_cards"]}}},
{"type": "function", "function": {"name": "preflop_advice", "description": "Get preflop strategy for two hole cards. Use when no board is provided.", "parameters": {"type": "object", "properties": {"card1": {"type": "string"}, "card2": {"type": "string"}, "position": {"type": "string", "description": "UTG, MP, CO, BTN, SB, BB. Default BTN."}}, "required": ["card1", "card2"]}}},
{"type": "function", "function": {"name": "log_hand", "description": "Log a poker hand with the action taken and optional result. Use for tracking, not coaching.", "parameters": {"type": "object", "properties": {"hand": {"type": "string", "description": "The starting hand, e.g. AKo, 72s, JJ, 93o"}, "position": {"type": "string", "description": "Optional position: UTG, MP, CO, BTN, SB, BB"}, "action": {"type": "string", "description": "What the player did: fold, call, raise, 3-bet, check, all-in"}, "result": {"type": "string", "description": "Optional: won or lost"}, "amount": {"type": "number", "description": "Optional: dollar amount won or lost"}}, "required": ["hand"]}}},
]

available = {"evaluate_poker_hand": evaluate_poker_hand, "preflop_advice": preflop_advice, "log_hand": log_hand}

def get_session_context(user_id):
	try:
		result = supabase.table("messages").select("input, hand, position").eq("user_id", user_id).order("created_at", desc=True).limit(10).execute()
		if not result.data:
			return None
		msgs = list(reversed(result.data))
		anchor = None
		streets = []
		for m in msgs:
			if m.get("hand") and not anchor:
				anchor = m
			elif anchor:
				streets.append(m.get("input", ""))
		if anchor:
			return {"hand": anchor["hand"], "position": anchor.get("position", ""), "prev_input": anchor.get("input", ""), "streets": streets}
	except Exception:
		pass
	return None

def build_system(mode, session=None):
	if mode == "track":
		base = "You are a poker hand tracker. From the player's message, extract their hand, position, what they did, whether they won or lost, and how much. Call log_hand with everything you find. Respond in one line like: 'Logged - [hand], [action], [result if any], [amount if any].' No advice. No strategy."
	else:
		base = "You are a poker coach. When a player describes their hand WITH a board, use evaluate_poker_hand to compute real math. When a player describes ONLY hole cards with no board, use preflop_advice. Respond in 2-3 short sentences. Talk like a friend texting you from the table."
	if session and session.get("hand"):
		hand = session["hand"]
		pos = session.get("position", "")
		prev = session.get("prev_input", "")
		streets = session.get("streets", [])
		base += f" CONTEXT - this player is holding {hand}"
		if pos:
			base += f" from {pos}"
		base += f". their original message was '{prev}'."
		if streets:
			for s in streets:
				if s:
					base += f" they then said: '{s}'."
		base += " Their new message is a continuation of this same hand. If they describe any board or street, use evaluate_poker_hand with their hole cards plus ALL cards mentioned across these messages - the flop, turn, river - combined."
	return {"role": "system", "content": base}
def run_pipeline(user_input, mode, user_id=None):
    session = None
    if user_id:
        session = get_session_context(user_id)

    system_msg = build_system(mode, session)
    messages = [system_msg, {"role": "user", "content": user_input}]

    try:
        response = groq_client.chat.completions.create(
            model="openai/gpt-oss-120b",
            messages=messages,
            tools=tools,
            tool_choice="auto",
        )
    except Exception as e:
        return f"AI error: {str(e)}", {}, session

    msg = response.choices[0].message
    parsed = {}
    if msg.tool_calls:
        messages.append(msg)
        for tc in msg.tool_calls:
            fn = available.get(tc.function.name)
            try:
                args = json.loads(tc.function.arguments)
                result = fn(**args) if fn else "Not found."
            except Exception as e:
                result = json.dumps({"error": f"Tool failed: {str(e)}. Try cards like Ah Kd or Jh 4d."})

            if tc.function.name in ("preflop_advice", "evaluate_poker_hand", "log_hand"):
                try:
                    parsed = json.loads(result)
                except Exception:
                    pass

            result_text = ""
            if parsed.get("hand"):
                result_text += f"Hand: {parsed['hand']}. "
            if parsed.get("tier"):
                result_text += f"Tier: {parsed['tier']}. "
            if parsed.get("position"):
                result_text += f"Position: {parsed['position']}. "
            if parsed.get("action"):
                result_text += f"Action: {parsed['action']}. "
            if parsed.get("hand_rank"):
                result_text += f"Hand rank: {parsed['hand_rank']}. Score: {parsed.get('score', '')}. "
            if parsed.get("result"):
                result_text += f"Result: {parsed['result']}. "
            if parsed.get("amount"):
                result_text += f"Amount: {parsed['amount']}. "
            if not result_text:
                result_text = json.dumps(parsed)

            clean = [
                {
                    "role": "system",
                    "content": "Based on this data, respond to the player briefly and friendly. No tool calls." if mode == "coach" else "Based on this data, give a one-line log summary. No advice, no tool calls."
                },
                {"role": "user", "content": user_input},
                {"role": "assistant", "content": result_text.strip()},
            ]
            try:
                second = groq_client.chat.completions.create(model="openai/gpt-oss-120b", messages=clean)
                return second.choices[0].message.content, parsed, session
            except Exception as e:
                return f"AI response error: {str(e)}", parsed, session

    return msg.content, parsed, session