"""Tests for ZenOS memory modules."""

import pytest
import time


class TestWorkingMemory:
    def test_add_get(self):
        from memory.working import WorkingMemory, WorkingMemoryEntry
        wm = WorkingMemory(capacity=100)
        entry = WorkingMemoryEntry(id="key1", content="value1")
        wm.add(entry)
        result = wm.get("key1")
        assert result is not None
        assert result.content == "value1"

    def test_eviction(self):
        from memory.working import WorkingMemory, WorkingMemoryEntry
        wm = WorkingMemory(capacity=3)
        for i in range(5):
            wm.add(WorkingMemoryEntry(id=f"k{i}", content=f"v{i}"))
        assert len(wm) == 3
        assert wm.get("k0") is None  # evicted

    def test_ttl_expiry(self):
        from memory.working import WorkingMemory, WorkingMemoryEntry
        wm = WorkingMemory(capacity=100)
        wm.add(WorkingMemoryEntry(id="temp", content="data", ttl=0.1))
        assert wm.get("temp") is not None
        time.sleep(0.15)
        assert wm.get("temp") is None

    def test_priority(self):
        from memory.working import WorkingMemory, WorkingMemoryEntry
        wm = WorkingMemory(capacity=100)
        wm.add(WorkingMemoryEntry(id="low", content="val", priority=1))
        wm.add(WorkingMemoryEntry(id="high", content="val", priority=10))
        high = wm.get_by_priority(min_priority=5)
        assert len(high) == 1
        assert high[0].id == "high"

    def test_stats(self):
        from memory.working import WorkingMemory, WorkingMemoryEntry
        wm = WorkingMemory(capacity=100)
        wm.add(WorkingMemoryEntry(id="a", content="1"))
        wm.add(WorkingMemoryEntry(id="b", content="2"))
        stats = wm.get_stats()
        assert stats['size'] == 2

    def test_remove(self):
        from memory.working import WorkingMemory, WorkingMemoryEntry
        wm = WorkingMemory(capacity=100)
        wm.add(WorkingMemoryEntry(id="x", content="y"))
        assert wm.remove("x") is True
        assert wm.get("x") is None

    def test_clear(self):
        from memory.working import WorkingMemory, WorkingMemoryEntry
        wm = WorkingMemory(capacity=100)
        wm.add(WorkingMemoryEntry(id="a", content="1"))
        wm.add(WorkingMemoryEntry(id="b", content="2"))
        count = wm.clear()
        assert count == 2
        assert len(wm) == 0

    def test_contains(self):
        from memory.working import WorkingMemory, WorkingMemoryEntry
        wm = WorkingMemory(capacity=100)
        wm.add(WorkingMemoryEntry(id="k", content="v"))
        assert "k" in wm
        assert "missing" not in wm


class TestEpisodicMemory:
    def test_add_episode(self):
        from memory.episodic import EpisodicMemory, Episode
        em = EpisodicMemory()
        ep = Episode(content="User asked about Python", importance=0.8)
        eid = em.add_episode(ep)
        assert eid != ""
        assert ep.content == "User asked about Python"

    def test_search(self):
        from memory.episodic import EpisodicMemory, Episode
        em = EpisodicMemory()
        em.add_episode(Episode(content="Python is great"))
        em.add_episode(Episode(content="JavaScript is also nice"))
        em.add_episode(Episode(content="Rust is fast"))
        results = em.search("Python")
        assert len(results) >= 1

    def test_get_episodes(self):
        from memory.episodic import EpisodicMemory, Episode
        em = EpisodicMemory()
        em.add_episode(Episode(content="event 1"))
        em.add_episode(Episode(content="event 2"))
        episodes = em.get_episodes()
        assert len(episodes) == 2

    def test_forget(self):
        from memory.episodic import EpisodicMemory, Episode
        em = EpisodicMemory()
        ep = Episode(content="to forget")
        eid = em.add_episode(ep)
        assert em.forget(eid) is True
        assert len(em) == 0

    def test_timeline(self):
        from memory.episodic import EpisodicMemory, Episode
        from datetime import datetime
        em = EpisodicMemory()
        today = datetime.now().strftime("%Y-%m-%d")
        em.add_episode(Episode(content="today's event"))
        timeline = em.get_timeline(today)
        assert len(timeline) >= 1


class TestSemanticMemory:
    def test_add_knowledge(self):
        from memory.semantic import SemanticMemory, Knowledge
        sm = SemanticMemory()
        k = Knowledge(content="Python is a programming language", importance=0.9)
        kid = sm.add_knowledge(k)
        assert kid != ""

    def test_get_by_id(self):
        from memory.semantic import SemanticMemory, Knowledge
        sm = SemanticMemory()
        k = Knowledge(content="test fact")
        kid = sm.add_knowledge(k)
        retrieved = sm.get_by_id(kid)
        assert retrieved is not None
        assert retrieved.content == "test fact"

    def test_update(self):
        from memory.semantic import SemanticMemory, Knowledge
        sm = SemanticMemory()
        k = Knowledge(content="old content")
        kid = sm.add_knowledge(k)
        sm.update(kid, content="new content")
        updated = sm.get_by_id(kid)
        assert updated.content == "new content"

    def test_delete(self):
        from memory.semantic import SemanticMemory, Knowledge
        sm = SemanticMemory()
        k = Knowledge(content="to delete")
        kid = sm.add_knowledge(k)
        assert sm.delete(kid) is True
        assert sm.get_by_id(kid) is None

    def test_keyword_search(self):
        from memory.semantic import SemanticMemory, Knowledge
        sm = SemanticMemory()
        sm.add_knowledge(Knowledge(content="Python programming"))
        sm.add_knowledge(Knowledge(content="Java programming"))
        results = sm.search(query_text="Python")
        assert len(results) >= 1


class TestProceduralMemory:
    def test_register_skill(self):
        from memory.procedural import ProceduralMemory, Skill
        pm = ProceduralMemory()
        skill = Skill(name="greet", func=lambda name: f"Hello {name}", description="Greets")
        sid = pm.register_skill(skill)
        assert skill.name == "greet"
        retrieved = pm.get_skill("greet")
        assert retrieved is not None

    def test_execute_skill(self):
        from memory.procedural import ProceduralMemory, Skill
        pm = ProceduralMemory()
        skill = Skill(name="add", func=lambda a, b: a + b)
        pm.register_skill(skill)
        result = pm.execute_skill("add", 2, 3)
        assert result == 5

    def test_list_skills(self):
        from memory.procedural import ProceduralMemory, Skill
        pm = ProceduralMemory()
        pm.register_skill(Skill(name="s1", func=lambda: None, metadata={"tags": ["math"]}))
        pm.register_skill(Skill(name="s2", func=lambda: None, metadata={"tags": ["text"]}))
        all_skills = pm.list_skills()
        assert len(all_skills) == 2


class TestMemoryCompressor:
    def test_should_compress(self):
        from memory.compression import MemoryCompressor, CompressionConfig
        comp = MemoryCompressor(config=CompressionConfig(threshold=0.8))
        assert comp.should_compress(current_size=80, capacity=100)
        assert not comp.should_compress(current_size=50, capacity=100)

    def test_summarize(self):
        from memory.compression import MemoryCompressor
        comp = MemoryCompressor()
        text = "This is a long text. " * 20
        summary = comp.summarize(text, max_length=100)
        assert len(summary) <= 100
