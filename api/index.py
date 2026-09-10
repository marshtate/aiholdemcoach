import os
import json
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from groq import Groq
from treys import Card, Evaluator

app = FastAPI()

app.add_middleware(CORSMiddleware,
allow_origins=["*"],
allow_credentials=True,
allow_methods=["*"],
allow_headers=["*"],)

client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
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
	if len(card1) == 1:
		card1 = card1 + "h"
	if len(card2) == 1:
		card2 = card2 + "d"
	r1, s1 = card1[0].upper(), card1[1].lower()
	r2, s2 = card2[0].upper(), card2[1].lower()
	val1, val2 = RANK_VALUES[r1], RANK_VALUES[r2]
	if val1 < val2:
		r1, r2 = r2, r1
		s1, s2 = s2, s1
	if r1 == r2:
		return f"{r1}{r2}"
	elif s1 == s2:
		return f"{r1}{r2}s"
	else:
		return f"{r1}{r2}o"

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
	if pos == "BB":
		action = "Check if unraised, defend vs one open depending on pot odds"
	elif tier in open_thresholds.get(pos, []):
		action = "Raise (open 2.2x-2.5x BB)"
	else:
		action = "Fold"
	return json.dumps({"hand": hand, "tier": TIER_NAMES[tier], "position": pos, "action": action})

tools = [
{"type": "function", "function": {"name": "evaluate_poker_hand", "description": "Evaluate a poker hand from hole cards and community board cards. Use when the player provides a board.", "parameters": {"type": "object", "properties": {"hero_cards": {"type": "array", "items": {"type": "string"}, "description": "Two hole cards, e.g. Ah and Kd"}, "board_cards": {"type": "array", "items": {"type": "string"}, "description": "Three to five community cards"}}, "required": ["hero_cards", "board_cards"]}}},
{"type": "function", "function": {"name": "preflop_advice", "description": "Get preflop strategy for two hole cards. Use when no board is provided.", "parameters": {"type": "object", "properties": {"card1": {"type": "string", "description": "First hole card, e.g. Ah"}, "card2": {"type": "string", "description": "Second hole card, e.g. Kd"}, "position": {"type": "string", "description": "Position: UTG, MP, CO, BTN, SB, BB. Default BTN."}}, "required": ["card1", "card2"]}}},
]

available = {"evaluate_poker_hand": evaluate_poker_hand, "preflop_advice": preflop_advice}

system_msg = {"role": "system", "content": "You are a poker coach. When a player describes their hand WITH a board, use evaluate_poker_hand. When they describe ONLY hole cards with no board, use preflop_advice. Respond in 2-3 short sentences. Talk like a friend texting you from the table."}

def coach(user_input):
	messages = [system_msg, {"role": "user", "content": user_input}]
	response = client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages, tools=tools, tool_choice="auto")
	response_message = response.choices[0].message
	tool_calls = response_message.tool_calls
	if tool_calls:
		messages.append(response_message)
		for tool_call in tool_calls:
			function_name = tool_call.function.name
			function_args = json.loads(tool_call.function.arguments)
			func = available.get(function_name)
			result = func(**function_args) if func else "Function not found."
			messages.append({"tool_call_id": tool_call.id, "role": "tool", "name": function_name, "content": result})
		second = client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages)
		return second.choices[0].message.content
	return response_message.content

class ChatRequest(BaseModel):
	message: str

@app.post("/api/chat")
async def chat_endpoint(req: ChatRequest):
	return {"reply": coach(req.message)}