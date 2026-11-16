import rules as rules


class Game:
    def __init__(self):
        self.players = []
        self.started = False
        self.over = False  # set once someone wins; no more turns after that
        self.current_player_index = 0
        self.case_file = None
        # positions of characters no player controls; a played character's position
        # lives on its Player, so every character's location is stored exactly once
        self.unplayed_locations = {}
        # the suggestion waiting on a player to show a card, or None
        self.pending_disproof = None

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

        played = {player.character for player in self.players}
        self.unplayed_locations = {character: location
                                   for character, location in starts.items()
                                   if character not in played}

        self.started = True
        self.current_player_index = 0
        self.get_current_player().reset_turn(rules.HALLWAYS)

    def character_locations(self):
        """Location of all six characters, played or not."""
        locations = dict(self.unplayed_locations)
        for player in self.players:
            if player.character is not None:
                locations[player.character] = player.location
        return locations

    def active_players(self):
        return [player for player in self.players if not player.eliminated]

    def occupied_hallways(self, exclude_player=None):
        # only players' pawns block hallways; unplayed characters never do
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

        # Move the suggested character into the current room, whether or not anyone plays them.
        for other in self.players:
            if other.character == suspect:
                other.location = room
                other.moved_by_suggestion = True
                break
        else:
            self.unplayed_locations[suspect] = room

        # Being pulled into a room allows one suggestion there; once used, it's gone.
        # (Cleared after the loop, so suggesting your own character doesn't grant it.)
        player.moved_by_suggestion = False

        return True, ""

    def start_disproof(self, suggester, suspect, weapon, room):
        """Ask players in turn order, starting after the suggester, until one holds a
        matching card. Eliminated players still disprove. Returns (disprover, matching
        cards), or (None, []) when nobody can disprove."""
        order = [player.player_id for player in self.players]
        for player_id in rules.disproof_order(order, suggester.player_id):
            player = self.get_player(player_id)
            matches = rules.matching_cards(player.cards, suspect, weapon, room)
            if matches:
                self.pending_disproof = {
                    "suggester_id": suggester.player_id,
                    "disprover_id": player_id,
                    "suspect": suspect,
                    "weapon": weapon,
                    "room": room,
                    "cards": matches,
                }
                return player, matches
        return None, []

    def disprove_error(self, player, card):
        pending = self.pending_disproof
        if pending is None:
            return "There is no suggestion to disprove."
        if player.player_id != pending["disprover_id"]:
            return "It is not your turn to disprove."
        if card not in pending["cards"]:
            return "Show one of your cards that matches the suggestion."
        return None

    def waiting_on_disproof_error(self):
        """Error for any turn action taken while a suggestion is still being disproved."""
        if self.pending_disproof is None:
            return None
        disprover = self.get_player(self.pending_disproof["disprover_id"])
        return f"Waiting for {disprover.name} to disprove the suggestion."

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

        # A player pulled into a room may suggest there on their next turn only:
        # if they didn't, the chance ends with that turn.
        self.get_current_player().moved_by_suggestion = False

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
            # all six characters in card order; playerId is None for an unplayed one
            "characters": self.public_characters(),
        }

    def public_characters(self):
        controllers = {player.character: player.player_id for player in self.players}
        locations = self.character_locations()
        return [
            {
                "character": character,
                "location": locations.get(character),
                "playerId": controllers.get(character),
            }
            for character in rules.CHARACTERS
        ]
