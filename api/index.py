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
	allow_headers=["*"],
)

try:
	groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
	supabase: Client = create_client(os.environ.get("SUPABASE_URL"),
		os.environ.get("SUPABASE_SERVICE_KEY"))
	evaluator = Evaluator()
	startup_ok = True
	startup_error = ""
except Exception as exc:
	startup_ok = False
	startup_error = str(exc)


def evaluate_poker_hand(hero_cards, board_cards):
	hero = [Card.new(card) for card in hero_cards]
	board = [Card.new(card) for card in board_cards]
	score = evaluator.evaluate(board, hero)
	rank = evaluator.class_to_string(evaluator.get_rank_class(score))
	return json.dumps({"score": score, "hand_rank": rank})


def preflop_advice(card1, card2, position="BTN"):
	position = position.upper()
	return json.dumps({
		"hand": f"{card1}{card2}",
		"position": position,
		"action": "Raise (open 2.2x-2.5x BB)" if position in {"CO", "BTN"} else "Fold",
	})


def log_hand(hand, position=None, action=None, result=None, amount=None):
	return json.dumps({
		"hand": hand, "position": position, "action": action,
		"result": result, "amount": amount,
	})


def close_session(profit):
	return json.dumps({"closed": True, "profit": profit})


tools = []
available = {
	"evaluate_poker_hand": evaluate_poker_hand,
	"preflop_advice": preflop_advice,
	"log_hand": log_hand,
	"close_session": close_session,
}


@app.post("/api/chat")
async def chat_endpoint(req: Request):
	if not startup_ok:
		return {"reply": f"Startup failed: {startup_error}"}
	try:
		body = await req.json()
		user_input = body.get("message", "")
		response = groq_client.chat.completions.create(
			model="openai/gpt-oss-120b",
			messages=[
				{"role": "system", "content": "You are a concise poker coach."},
				{"role": "user", "content": user_input},
			],
		)
		return {"reply": response.choices[0].message.content, "parsed": {}}
	except Exception as exc:
		return {"reply": f"AI error: {exc}"}


@app.get("/api/sessions")
async def sessions_endpoint(req: Request):
	return {"sessions": []}


@app.post("/api/result")
async def result_endpoint(req: Request):
	return {"ok": True}


@app.get("/api/history")
async def history_endpoint(req: Request):
	return {"history": []}

app = FastAPI()

app.add_middleware(
	CORSMiddleware,
	allow_origins=["*"],
	allow_credentials=True,
	allow_methods=["*"],
	allow_headers=["*"],
)

try:
	groq_client = Groq(api_key=os.environ.get("GROQ_API_KEY"))
	supabase: Client = create_client(
		os.environ.get("SUPABASE_URL"),
		os.environ.get("SUPABASE_SERVICE_KEY"),
	)
	evaluator = Evaluator()
	startup_ok = True
	startup_error = ""
except Exception as exc:
	startup_ok = False
	startup_error = str(exc)


def evaluate_poker_hand(hero_cards, board_cards):
	hero = [Card.new(card) for card in hero_cards]
	board = [Card.new(card) for card in board_cards]
	score = evaluator.evaluate(board, hero)
	rank = evaluator.class_to_string(evaluator.get_rank_class(score))
	return json.dumps({"score": score, "hand_rank": rank})


def preflop_advice(card1, card2, position="BTN"):
	position = position.upper()
	return json.dumps({
		"hand": f"{card1}{card2}",
		"position": position,
		"action": "Raise (open 2.2x-2.5x BB)" if position in {"CO", "BTN"} else "Fold",
	})


def log_hand(hand, position=None, action=None, result=None, amount=None):
	return json.dumps({
		"hand": hand,
		"position": position,
		"action": action,
		"result": result,
		"amount": amount,
	})


def close_session(profit):
	return json.dumps({"closed": True, "profit": profit})


tools = []

available = {
	"evaluate_poker_hand": evaluate_poker_hand,
	"preflop_advice": preflop_advice,
	"log_hand": log_hand,
	"close_session": close_session,
}


@app.post("/api/chat")
async def chat_endpoint(req: Request):
	if not startup_ok:
		return {"reply": f"Startup failed: {startup_error}"}
	try:
		body = await req.json()
		user_input = body.get("message", "")
		response = groq_client.chat.completions.create(
			model="openai/gpt-oss-120b",
			messages=[
				{"role": "system", "content": "You are a concise poker coach."},
				{"role": "user", "content": user_input},
			],
		)
		return {"reply": response.choices[0].message.content, "parsed": {}}
	except Exception as exc:
		return {"reply": f"AI error: {exc}"}


@app.get("/api/sessions")
async def sessions_endpoint(req: Request):
	return {"sessions": []}


@app.post("/api/result")
async def result_endpoint(req: Request):
	return {"ok": True}


@app.get("/api/history")
async def history_endpoint(req: Request):
	return {"history": []}
def build_system(mode, session=None):
	base = "You are a concise poker coach."
	if session and session.get("previous"):
		base += f". original: '{session['previous']}'."
	streets = session.get("streets", []) if session else []
	if streets:
		for s in streets:
			if s:
				base += f" then: '{s}'."
		base += " Continuation - if they describe a board, use evaluate_poker_hand with hole cards plus ALL cards mentioned."
	elif session and session.get("hand") and mode == "track":
		hand = session["hand"]
		pos = session.get("position", "")
		base += f" CONTEXT - holding {hand}"
		if pos:
			base += f" from {pos}"
		base += ". New message is about this same hand - call log_hand with this hand and what they say."
	return {"role": "system", "content": base}

def format_track(parsed, session=None, closed=False):
	if closed and parsed.get("profit") is not None:
		p = parsed["profit"]
		return f"Session closed - {'+' if p >= 0 else ''}{p}."
	hand = parsed.get("hand") or (session.get("hand") if session else None) or "?"
	parts = [hand]
	if parsed.get("position"):
		parts.append(parsed["position"])
	if parsed.get("action"):
		parts.append(parsed["action"])
	if parsed.get("result"):
		parts.append("won" if parsed["result"].lower() == "won" else "lost")
	if parsed.get("amount"):
		parts.append(f"${parsed['amount']}")
	return "Logged - " + ", ".join(parts) + "."


def get_session_context(user_id):
	try:
		result = (supabase.table("sessions")
			.select("id, hand, position, created_at")
			.eq("user_id", user_id)
			.eq("status", "open")
			.order("created_at", desc=True)
			.limit(1)
			.execute())
		if not result.data:
			return None
		session = result.data[0]
		messages = (supabase.table("messages")
			.select("input")
			.eq("user_id", user_id)
			.eq("session_id", session["id"])
			.order("created_at")
			.execute()).data or []
		session["streets"] = [item["input"] for item in messages if item.get("input")]
		return session
	except Exception:
		return None


def get_or_create_session(user_id):
	result = (supabase.table("sessions")
		.select("id")
		.eq("user_id", user_id)
		.eq("status", "open")
		.order("created_at", desc=True)
		.limit(1)
		.execute())
	if result.data:
		return result.data[0]["id"]
	created = supabase.table("sessions").insert({
		"user_id": user_id,
		"status": "open",
	}).execute()
	return created.data[0]["id"] if created.data else None


def run_pipeline(user_input, mode, user_id=None):
	session = None
	if user_id:
		session = get_session_context(user_id)
	system_msg = build_system(mode, session)
	messages = [system_msg, {"role": "user", "content": user_input}]
	try:
		response = groq_client.chat.completions.create(model="openai/gpt-oss-120b", messages=messages, tools=tools, tool_choice="auto")
	except Exception as e:
		return f"AI error: {str(e)}", {}, session, False
	msg = response.choices[0].message
	parsed = {}
	tool_called = False
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
			if tc.function.name in ("preflop_advice", "evaluate_poker_hand", "log_hand", "close_session"):
				try:
					parsed = json.loads(result)
				except:
					pass
			if tc.function.name == "close_session":
				closed = True
		if mode == "track":
			reply = format_track(parsed, session, closed)
			if closed and user_id:
				try:
					open_s = supabase.table("sessions").select("id").eq("user_id", user_id).eq("status", "open").order("created_at", desc=True).limit(1).execute()
					if open_s.data and open_s.data[0]:
						supabase.table("sessions").update({"status": "closed", "profit": parsed.get("profit"), "closed_at": "now()"}).eq("id", open_s.data[0]["id"]).execute()
				except:
					pass
			return reply, parsed, session, tool_called
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
		{"role": "user", "content": f"Asked: {user_input}\nData: {eval_data.strip()}"},
	]
	try:
		second = groq_client.chat.completions.create(model="openai/gpt-oss-120b", messages=clean)
		return second.choices[0].message.content, parsed, session, tool_called
	except Exception as e:
		return format_track(parsed, session), parsed, session, tool_called
	return msg.content, parsed, session, tool_called
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
	reply, parsed, session, tool_called = run_pipeline(user_input, mode, user_id)
	if user_id and tool_called:
		try:
			session_id = get_or_create_session(user_id) if mode == "track" else None
			row_hand = parsed.get("hand") or (session.get("hand") if session else None)
			row = {"user_id": user_id, "input": user_input, "reply": reply, "hand": row_hand, "position": parsed.get("position"), "player_action": parsed.get("action"), "result": parsed.get("result"), "amount": parsed.get("amount"), "session_id": session_id}
			if mode == "coach" and parsed.get("tier"):
				row["tier"] = parsed["tier"]
			if session and session.get("hand") and parsed.get("hand") == session.get("hand"):
				last = supabase.table("messages").select("id").eq("user_id", user_id).eq("hand", session["hand"]).order("created_at", desc=True).limit(1).execute()
				if last.data and last.data[0]:
					update = {"reply": reply}
					if parsed.get("action"): update["player_action"] = parsed["action"]
					if parsed.get("result"): update["result"] = parsed["result"]
					if parsed.get("amount"): update["amount"] = parsed["amount"]
					supabase.table("messages").update(update).eq("id", last.data[0]["id"]).execute()
				else:
					supabase.table("messages").insert(row).execute()
			else:
				supabase.table("messages").insert(row).execute()
		except Exception as e:
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
	result = supabase.table("sessions").select("id, created_at, closed_at, profit, status").eq("user_id", user_id).order("created_at", desc=True).execute()
	return {"sessions": result.data}

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
		return {"error": str(e)}