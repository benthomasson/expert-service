"""Tests for SQLite backend — count helpers, init_db, connection pragmas."""

import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from uuid import UUID

import pytest


FAKE_PROJECT_ID = UUID("00000000-0000-0000-0000-000000000001")


# --- count_beliefs ---


class TestCountBeliefs:
    def _make_db(self, tmp_path, nodes=None):
        """Create a minimal reasons_lib-compatible SQLite database."""
        db_path = tmp_path / str(FAKE_PROJECT_ID) / "reasons.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE nodes ("
            "  id TEXT PRIMARY KEY, text TEXT NOT NULL,"
            "  truth_value TEXT NOT NULL DEFAULT 'IN')"
        )
        conn.execute(
            "CREATE TABLE nogoods ("
            "  id TEXT PRIMARY KEY, nodes_json TEXT NOT NULL DEFAULT '[]')"
        )
        if nodes:
            conn.executemany(
                "INSERT INTO nodes (id, text, truth_value) VALUES (?, ?, ?)",
                nodes,
            )
        conn.commit()
        conn.close()
        return tmp_path

    @patch("expert_service.rms.api.settings")
    def test_count_all_beliefs(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [
            ("b1", "Belief one", "IN"),
            ("b2", "Belief two", "OUT"),
            ("b3", "Belief three", "IN"),
        ])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from expert_service.rms.api import count_beliefs
        assert count_beliefs(FAKE_PROJECT_ID, None) == 3

    @patch("expert_service.rms.api.settings")
    def test_count_in_beliefs(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [
            ("b1", "Belief one", "IN"),
            ("b2", "Belief two", "OUT"),
            ("b3", "Belief three", "IN"),
        ])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from expert_service.rms.api import count_beliefs
        assert count_beliefs(FAKE_PROJECT_ID, "IN") == 2

    @patch("expert_service.rms.api.settings")
    def test_count_out_beliefs(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [
            ("b1", "Belief one", "IN"),
            ("b2", "Belief two", "OUT"),
        ])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from expert_service.rms.api import count_beliefs
        assert count_beliefs(FAKE_PROJECT_ID, "OUT") == 1

    @patch("expert_service.rms.api.settings")
    def test_count_empty_db(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from expert_service.rms.api import count_beliefs
        assert count_beliefs(FAKE_PROJECT_ID, "IN") == 0
        assert count_beliefs(FAKE_PROJECT_ID, None) == 0

    @patch("expert_service.rms.api.settings")
    def test_count_nonexistent_db(self, mock_settings, tmp_path):
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = tmp_path

        from expert_service.rms.api import count_beliefs
        assert count_beliefs(FAKE_PROJECT_ID, "IN") == 0


# --- count_nogoods ---


class TestCountNogoods:
    def _make_db(self, tmp_path, nogoods=None):
        db_path = tmp_path / str(FAKE_PROJECT_ID) / "reasons.db"
        db_path.parent.mkdir(parents=True)
        conn = sqlite3.connect(str(db_path))
        conn.execute(
            "CREATE TABLE nodes ("
            "  id TEXT PRIMARY KEY, text TEXT NOT NULL,"
            "  truth_value TEXT NOT NULL DEFAULT 'IN')"
        )
        conn.execute(
            "CREATE TABLE nogoods ("
            "  id TEXT PRIMARY KEY, nodes_json TEXT NOT NULL DEFAULT '[]')"
        )
        if nogoods:
            conn.executemany(
                "INSERT INTO nogoods (id, nodes_json) VALUES (?, ?)",
                nogoods,
            )
        conn.commit()
        conn.close()
        return tmp_path

    @patch("expert_service.rms.api.settings")
    def test_count_nogoods(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [
            ("ng-001", '["b1", "b2"]'),
            ("ng-002", '["b3", "b4"]'),
        ])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from expert_service.rms.api import count_nogoods
        assert count_nogoods(FAKE_PROJECT_ID) == 2

    @patch("expert_service.rms.api.settings")
    def test_count_nogoods_empty(self, mock_settings, tmp_path):
        data_dir = self._make_db(tmp_path, [])
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = data_dir

        from expert_service.rms.api import count_nogoods
        assert count_nogoods(FAKE_PROJECT_ID) == 0

    @patch("expert_service.rms.api.settings")
    def test_count_nogoods_nonexistent_db(self, mock_settings, tmp_path):
        mock_settings.db_backend = "sqlite"
        mock_settings.data_dir = tmp_path

        from expert_service.rms.api import count_nogoods
        assert count_nogoods(FAKE_PROJECT_ID) == 0


# --- init_db ---


class TestInitDb:
    @patch("expert_service.db.connection._is_sqlite", False)
    def test_init_db_noop_for_postgresql(self):
        from expert_service.db.connection import init_db
        # Should return without doing anything
        init_db()

    @patch("expert_service.db.connection._is_sqlite", True)
    @patch("expert_service.db.connection.settings")
    @patch("expert_service.db.connection.get_sync_engine")
    def test_init_db_creates_tables_for_sqlite(self, mock_engine, mock_settings, tmp_path):
        from expert_service.db.connection import init_db
        mock_settings.data_dir = tmp_path / "data"
        mock_engine_obj = MagicMock()
        mock_engine.return_value = mock_engine_obj

        # Mock Base.metadata.create_all
        with patch("expert_service.db.models.Base") as mock_base:
            init_db()
            mock_base.metadata.create_all.assert_called_once_with(mock_engine_obj)

        # data_dir should be created
        assert (tmp_path / "data").exists()
