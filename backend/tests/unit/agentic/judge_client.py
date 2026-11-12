"""A fake grading model for the bench tests: answers every judge call with one fixed grade (no API call)."""

import json
from types import SimpleNamespace


class JudgeClient:
    def __init__(self, grade: dict):
        self.grade = grade
        self.responses = SimpleNamespace(create=self.create)

    def create(self, **kwargs):
        return SimpleNamespace(output_text=json.dumps(self.grade), usage=SimpleNamespace(cost=0.001))
