"""
Message format shared by server.py and the clients.

Every message, in both directions, is a JSON object of the form

    {"type": "MOVE_REQUEST", "data": {"destination": "Hall"}}

Field names inside "data" are camelCase (playerId, currentPlayerId, ...).
"""
import json


def make_message(message_type, **payload):
    return json.dumps({"type": message_type, "data": payload})


def parse_message(raw):
    message = json.loads(raw)
    if not isinstance(message, dict) or not isinstance(message.get("type"), str):
        raise ValueError("Message must be a JSON object containing a string 'type'.")
    data = message.get("data")
    if data is None:
        data = {}
    if not isinstance(data, dict):
        raise ValueError("Message 'data' must be a JSON object.")
    return {"type": message["type"], "data": data}
