import json


def make_message(message_type, **payload):
    return json.dumps({"type": message_type, **payload})


def parse_message(raw):
    data = json.loads(raw)
    if not isinstance(data, dict) or "type" not in data:
        raise ValueError("Message must be a JSON object containing 'type'.")
    return data
