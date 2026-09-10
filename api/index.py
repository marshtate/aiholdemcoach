import os
import json
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
from treys import Card, Evaluator
from supabase import create_client, Client

app = FastAPI()

app.add_middleware(CORSMiddleware,
allow_origins=["*"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],)

groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
supabase: Client = create_client(os.environ.get("SUPABASE_URL"),
os.environ.get("SUPABASE_SERVICE_KEY"))
evaluator = Evaluator()

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
			c1 = hand[0] + ("h" if hand[0]!= hand[0] else "s")
			c2 = hand[1] + ("d" if hand[1]!= hand[1] else "c")
			tier_num = get_hand_tier(to_canonical(c1, c2))
		except: pass
	tier_name = TIER_NAMES.get(tier_num, None) if tier_num else None
	return json.dumps({"hand": hand, "tier": tier_name, "position": position, "action": action, "result": result, "amount": amount})

tools = [
{"type": "function", "function": {"name": "evaluate_poker_hand", "description": "Evaluate a poker hand from hole cards and board cards. Use when the player provides a board.", "parameters": {"type": "object", "properties": {"hero_cards": {"type": "array", "items": {"type": "string"}}, "board_cards": {"type": "array", "items": {"type": "string"}}}, "required": ["hero_cards", "board_cards"]}}},
{"type": "function", "function": {"name": "preflop_advice", "description": "Get preflop strategy for two hole cards. Use when no board is provided.", "parameters": {"type": "object", "properties": {"card1": {"type": "string"}, "card2": {"type": "string"}, "position": {"type": "string", "description": "UTG, MP, CO, BTN, SB, BB. Default BTN."}}, "required": ["card1", "card2"]}}},
{"type": "function", "function": {"name": "log_hand", "description": "Log a poker hand with the action taken and optional result. Use for tracking, not coaching.", "parameters": {"type": "object", "properties": {"hand": {"type": "string", "description": "The starting hand, e.g. AKo, 72s, JJ, 93o"}, "position": {"type": "string", "description": "Optional: UTG, MP, CO, BTN, SB, BB"}, "action": {"type": "string", "description": "What the player did: fold, call, raise, 3-bet, check, all-in"}, "result": {"type": "string", "description": "Optional: won or lost"}, "amount": {"type": "number", "description": "Optional: dollar amount won or lost"}}, "required": ["hand"]}}},
]

available = {"evaluate_poker_hand": evaluate_poker_hand, "preflop_advice": preflop_advice, "log_hand": log_hand}

coach_system = {"role": "system", "content": "You are a poker coach. When a player describes their hand WITH a board, use evaluate_poker_hand. When they describe ONLY hole cards, use preflop_advice. Respond in 2-3 short sentences. Talk like a friend texting you from the table."}

track_system = {"role": "system", "content": "You are a poker hand tracker. From the player's message, extract their hand, position, what they did, whether they won or lost, and how much. Call log_hand with everything you find. Respond in one line like: 'Logged - [hand], [action], [result if any], [amount if any].' No advice. No strategy."}

def run_pipeline(user_input, system_msg):
	messages = [system_msg, {"role": "user", "content": user_input}]
	response = groq_client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages, tools=tools, tool_choice="auto")
	msg = response.choices[0].message
	parsed = {}
	if msg.tool_calls:
		messages.append(msg)
		for tc in msg.tool_calls:
			fn = available.get(tc.function.name)
			args = json.loads(tc.function.arguments)
			result = fn(**args) if fn else "Not found."
			messages.append({"tool_call_id": tc.id, "role": "tool", "name": tc.function.name, "content": result})
			if tc.function.name in ("preflop_advice", "evaluate_poker_hand", "log_hand"):
				try:
					parsed = json.loads(result)
				except (TypeError, json.JSONDecodeError):
					pass
		second = groq_client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages)
		return second.choices[0].message.content, parsed
	return msg.content, parsed
class ChatRequest(BaseModel):
	message: str
	mode: str = "coach"

@app.post("/api/chat")
async def chat_endpoint(req: Request):
	body = await req.json()
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
	if mode == "track":
		reply, parsed = run_pipeline(user_input, track_system)
	else:
		reply, parsed = run_pipeline(user_input, coach_system)
	if user_id:
		try:
			row = {"user_id": user_id, "input": user_input, "reply": reply}
			if parsed.get("hand"): row["hand"] = parsed["hand"]
			if parsed.get("tier"): row["tier"] = parsed["tier"]
			if parsed.get("position"): row["position"] = parsed["position"]
			if parsed.get("action"): row["player_action"] = parsed["action"]
			if parsed.get("result"): row["result"] = parsed["result"]
			if parsed.get("amount"): row["amount"] = parsed["amount"]
			if parsed.get("hand_rank"): row["hand"] = parsed["hand_rank"]
			supabase.table("messages").insert(row).execute()
		except:
			pass
	return {"reply": reply, "parsed": parsed}

@app.post("/api/result")
async def result_endpoint(req: Request):
	body = await req.json()
	entry_id = body.get("id")
	result = body.get("result")
	amount = body.get("amount")
	auth_header = req.headers.get("authorization", "")
	if not auth_header.startswith("Bearer "):
		return {"error": "unauthorized"}
	token = auth_header[7:]
	try:
		resp = supabase.auth.get_user(token)
		if not resp or not resp.user:
			return {"error": "unauthorized"}
	except:
		return {"error": "unauthorized"}
	try:
		supabase.table("messages").update({"result": result, "amount": amount}).eq("id", entry_id).execute()
		return {"ok": True}
	except:
		return {"error": "could not save"}

@app.get("/api/history")
async def history_endpoint(req: Request):
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
	result = supabase.table("messages").select("id, input, reply, hand, tier, position, player_action, result, amount, created_at").eq("user_id", user_id).order("created_at", desc=True).execute()
	return {"history": result.data}