class Player:
    def __init__(self, player_id, name):
        self.player_id = player_id
        self.name = name
        self.character = None
        self.location = None
        self.cards = []
        self.eliminated = False

        # Per-turn state used by Rules_20261114.py.
        self.started_in_hallway = False
        self.has_moved = False
        self.has_suggested = False
        self.moved_by_suggestion = False

    def reset_turn(self, hallways):
        self.started_in_hallway = self.location in hallways
        self.has_moved = False
        self.has_suggested = False

    def public_data(self):
        return {
            "playerId": self.player_id,
            "name": self.name,
            "character": self.character,
            "location": self.location,
            "eliminated": self.eliminated,
        }
