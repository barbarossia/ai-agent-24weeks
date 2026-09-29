"""Bound complete conversation exchanges in memory, with no disk persistence."""

from collections import deque


class Conversation:
    def __init__(self, max_turns=3, max_chars=6000):
        if max_turns < 0 or max_chars < 0:
            raise ValueError("Context limits cannot be negative")
        self.max_turns = max_turns
        self.max_chars = max_chars
        self._turns = deque()

    def remember(self, question: str, answer: str):
        self._turns.append((question, answer))
        while self._turns and (len(self._turns) > self.max_turns or
                sum(len(q) + len(a) for q, a in self._turns) > self.max_chars):
            self._turns.popleft()

    def snapshot(self):
        return [{"question": q, "answer": a} for q, a in self._turns]
