import rules as rules


class Game:
    def __init__(self):
        self.players = []
        self.started = False
        self.current_player_index = 0
        self.case_file = None

    def add_player(self, player):
        if len(self.players) >= rules.MAX_PLAYERS:
            return False
        self.players.append(player)
        return True

    def get_player(self, player_id):
        for player in self.players:
            if player.player_id == player_id:
                return player
        return None

    def get_current_player(self):
        if not self.players:
            return None
        return self.players[self.current_player_index]

    def character_taken(self, character):
        return any(player.character == character for player in self.players)

    def initialize(self):
        player_ids = [player.player_id for player in self.players]
        self.case_file, hands = rules.deal(player_ids)

        starts = rules.starting_positions()
        for player in self.players:
            player.cards = hands[player.player_id]
            player.location = starts[player.character]
            player.moved_by_suggestion = False

        self.started = True
        self.current_player_index = 0
        self.get_current_player().reset_turn(rules.HALLWAYS)

    def occupied_hallways(self, exclude_player=None):
        return {
            player.location
            for player in self.players
            if player is not exclude_player and player.location in rules.HALLWAYS
        }

    def move_player(self, player, destination):
        if destination is None:
            return False, "Destination required.", None

        if player.location not in rules.ADJACENCY:
            return False, "Invalid current location.", None

        error = rules.move_error(
            player.location,
            destination,
            self.occupied_hallways(exclude_player=player),
            player.has_moved,
        )
        if error:
            return False, error, None

        old_location = player.location
        player.location = destination
        player.has_moved = True
        player.moved_by_suggestion = False
        return True, "", old_location

    def end_turn_error(self, player):
        return rules.end_turn_error(
            player.started_in_hallway,
            player.has_moved,
            player.has_suggested,
        )

    def suggestion_error(self, player, suspect, weapon):
        return rules.suggestion_error(
            player.location,
            player.has_moved,
            player.moved_by_suggestion,
            player.has_suggested,
            suspect,
            weapon,
        )

    def make_suggestion(self, player, suspect, weapon):
        error = self.suggestion_error(player, suspect, weapon)
        if error:
            return False, error

        player.has_suggested = True
        room = player.location

        # Move the suggested character into the current room.
        for other in self.players:
            if other.character == suspect:
                other.location = room
                other.moved_by_suggestion = True
                break

        return True, ""

    def next_turn(self):
        order = [player.player_id for player in self.players]
        active_ids = {
            player.player_id
            for player in self.players
            if not player.eliminated
        }

        next_index = rules.next_turn_index(
            order,
            self.current_player_index,
            active_ids,
        )
        if next_index is None:
            return None

        self.current_player_index = next_index
        player = self.get_current_player()
        player.reset_turn(rules.HALLWAYS)
        return player

    def public_state(self):
        current = self.get_current_player()
        return {
            "started": self.started,
            "currentPlayerId": current.player_id if current else None,
            "players": [player.public_data() for player in self.players],
        }
