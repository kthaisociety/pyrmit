"""
The streamed answer must survive the client leaving: the generation runs in a background worker
that saves the assistant message (partial, then final) whatever happens to the HTTP connection.

Runs against a temporary SQLite database with a fake, slow LLM: no network, no Neon.
"""

import json
import os
import time
import types
import unittest

os.environ.setdefault("JWT_SECRET_KEY", "test-secret")
os.environ["RETRIEVAL_BACKEND"] = "pgvector"
os.environ["CHAT_MODE"] = "rag"
os.environ.pop("ACCESS_GATE_PASSWORD", None)
os.environ.pop("DEV_ACCESS_PASSWORD", None)

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def _jsonb_as_json(element, compiler, **kw):
    return "JSON"


import models  # noqa: E402
from agents.base import BaseRAGAgent  # noqa: E402
from db.database import get_db  # noqa: E402
from dependencies import get_current_user  # noqa: E402
from routers import chat  # noqa: E402

ANSWER_PARTS = [f"part{i} " for i in range(12)]


def fake_completion(client, **kwargs):
    if kwargs.get("stream"):
        def events():
            for part in ANSWER_PARTS:
                time.sleep(0.25)  # slow model: the client leaves in the middle
                yield types.SimpleNamespace(type="response.output_text.delta", delta=part)
            yield types.SimpleNamespace(type="response.completed", response=types.SimpleNamespace(usage=None))
        return events()
    return types.SimpleNamespace(output_text="What is the building permit process?", usage=None)


class BackgroundAnswerTest(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        tables = [models.User.__table__, models.ChatSession.__table__, models.ChatMessage.__table__]
        models.Base.metadata.create_all(engine, tables=tables)
        self.Session = sessionmaker(bind=engine)
        with self.Session() as db:
            db.add(models.User(id="u1", name="Test", email="test@example.com"))
            db.commit()

        self.patches = [
            (chat, "SessionLocal", self.Session),
            (chat, "create_chat_completion", fake_completion),
            (chat, "recorded_chat_completion", lambda recorder, client, **kw: fake_completion(client, **kw)),
            (chat, "get_openai_client", lambda: object()),
            (BaseRAGAgent, "_embed", lambda self, text: [0.0]),
            (BaseRAGAgent, "_retrieve_debug_rows_from_embedding",
             lambda self, embedding, k=5: [{"source": "PBL", "chunk_index": 0, "distance": 0.1,
                                            "content": "Det krävs bygglov för nybyggnad.", "preview": ""}]),
        ]
        self.originals = [(obj, name, getattr(obj, name)) for obj, name, _ in self.patches]
        for obj, name, value in self.patches:
            setattr(obj, name, value)

        app = FastAPI()
        app.include_router(chat.router, prefix="/api")

        def db_override():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = db_override
        app.dependency_overrides[get_current_user] = lambda: types.SimpleNamespace(id="u1")
        self.client = TestClient(app)

    def tearDown(self):
        for obj, name, value in self.originals:
            setattr(obj, name, value)

    def assistant_message(self):
        with self.Session() as db:
            return db.query(models.ChatMessage).filter(models.ChatMessage.role == "assistant").one()

    def wait_until_done(self, timeout=15):
        deadline = time.time() + timeout
        while time.time() < deadline:
            message = self.assistant_message()
            if message.status != "streaming":
                return message
            time.sleep(0.2)
        return self.assistant_message()

    def test_answer_saved_when_client_disconnects(self):
        body = {"messages": [{"role": "user", "content": "Hur söker man bygglov?"}], "session_id": None}
        with self.client.stream("POST", "/api/chat/stream", json=body) as response:
            seen = 0
            for line in response.iter_lines():
                if line.startswith("data:") and "output_text.delta" in line:
                    seen += 1
                    if seen == 2:
                        break  # leave in the middle of the answer
        # The message exists right away, marked as streaming, with partial text saved as it goes
        message = self.wait_until_done()
        self.assertEqual(message.status, "done")
        self.assertEqual(message.content.split("\n\n---")[0], "".join(ANSWER_PARTS))
        stages = [event["stage"] for event in (message.trace or [])]
        self.assertIn("retrieval", stages)

    def test_full_stream_still_works(self):
        body = {"messages": [{"role": "user", "content": "Hur söker man bygglov?"}], "session_id": None}
        events = []
        with self.client.stream("POST", "/api/chat/stream", json=body) as response:
            for line in response.iter_lines():
                if line.startswith("data:"):
                    events.append(json.loads(line[5:]))
        types_seen = [event["type"] for event in events]
        self.assertEqual(types_seen[0], "session_id")
        self.assertIn("done", types_seen)
        self.assertEqual(self.wait_until_done().status, "done")


if __name__ == "__main__":
    unittest.main()
