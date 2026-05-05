"""Local state tracking — started times, cached results."""

import time


class LocalState:
    def __init__(self):
        self.started_at = {}      # action_id → unix timestamp
        self.results_cache = {}   # action_id → last JSON result
        self.results_ts = {}      # action_id → timestamp of last result

    def on_action_start(self, action_id):
        self.started_at[action_id] = time.time()

    def on_action_stop(self, action_id):
        self.started_at.pop(action_id, None)

    def on_oneshot_complete(self, action_id, result):
        self.results_cache[action_id] = result
        self.results_ts[action_id] = time.time()
