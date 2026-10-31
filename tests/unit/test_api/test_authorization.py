"""Identity and real parameterized membership SQL, without Firebase/network services."""

from __future__ import annotations

import sqlite3
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import Mock

import pytest
from fastapi import HTTPException
from sqlalchemy.sql import Select

from heliotelligence.api import auth

SITE_A = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
SITE_B = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
UID = "test-user"


class Result:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows

    def scalar_one_or_none(self) -> Any:
        assert len(self.rows) <= 1
        return self.rows[0][0] if self.rows else None

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


class TrackedAlert:
    def __init__(self, database: Database, site_id: str = SITE_A) -> None:
        self.database = database
        self.id = 7
        self.site_id = site_id
        self.rule_name = "test_rule"
        self.message = "test alert"
        self._acknowledged = False

    @property
    def acknowledged(self) -> bool:
        return self._acknowledged

    @acknowledged.setter
    def acknowledged(self, value: bool) -> None:
        self.database.events.append(("mutate_alert", self.id))
        self._acknowledged = value


class Database:
    def __init__(self) -> None:
        self.connection = sqlite3.connect(":memory:", check_same_thread=False)
        self.connection.executescript("""
            CREATE TABLE sites (site_id TEXT PRIMARY KEY);
            CREATE TABLE user_site_access (
                uid TEXT, site_id TEXT, role TEXT, PRIMARY KEY(uid, site_id)
            );
        """)
        self.connection.executemany("INSERT INTO sites VALUES (?)", [(SITE_A,), (SITE_B,)])
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.events: list[tuple[Any, ...]] = []
        self.commits = 0
        self.alert = TrackedAlert(self)

    def grant(self, role: Any, site_id: str = SITE_A, uid: str = UID) -> None:
        self.connection.execute(
            "INSERT OR REPLACE INTO user_site_access VALUES (?, ?, ?)", (uid, site_id, role)
        )

    async def execute(self, statement: Any, parameters: Any = None) -> Result:
        sql = str(statement)
        bindings = dict(parameters if parameters is not None else statement.compile().params)
        self.calls.append((sql, bindings))
        if isinstance(statement, Select):
            assert "FROM alerts" in sql
            self.events.append(("locate_alert", bindings["id_1"]))
            return Result([(self.alert,)] if bindings["id_1"] == self.alert.id else [])
        self.events.append(("sql", sql, bindings))
        cursor = self.connection.execute(sql, bindings)
        return Result([tuple(row) for row in cursor.fetchall()])

    async def commit(self) -> None:
        self.events.append(("commit",))
        self.commits += 1
        self.connection.commit()

    async def refresh(self, alert: Any) -> None:
        self.events.append(("refresh", alert.id))

    @asynccontextmanager
    async def session(self) -> AsyncIterator[Database]:
        yield self


@pytest.fixture
def db(monkeypatch: pytest.MonkeyPatch) -> Iterator[Database]:
    database = Database()
    monkeypatch.setattr(auth, "get_session_factory", lambda: database.session)
    yield database
    database.connection.close()


@pytest.fixture
def claims(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    decoded = {
        "uid": UID,
        "email": "test@example.invalid",
        "platform_admin": False,
        "arbitrary": "must not escape",
    }
    monkeypatch.setattr(auth, "_get_firebase_app", lambda: None)
    monkeypatch.setattr(
        auth.firebase_auth, "verify_id_token", Mock(side_effect=lambda token: decoded)
    )
    return decoded


def user(admin: Any = False) -> dict[str, Any]:
    return {"uid": UID, "email": None, "platform_admin": admin}


@pytest.mark.parametrize("header", ["", "Basic abc", "Bearer", "Bearer ", "Bearer    "])
async def test_missing_or_empty_bearer_is_401(claims: Any, header: str) -> None:
    with pytest.raises(HTTPException) as error:
        await auth.get_current_user(header)
    assert error.value.status_code == 401
    auth.firebase_auth.verify_id_token.assert_not_called()


@pytest.mark.parametrize("failure", [ValueError("invalid"), RuntimeError("verification failed")])
async def test_verification_failure_is_401(
    claims: Any, monkeypatch: pytest.MonkeyPatch, failure: Exception
) -> None:
    monkeypatch.setattr(auth.firebase_auth, "verify_id_token", Mock(side_effect=failure))
    with pytest.raises(HTTPException) as error:
        await auth.get_current_user("Bearer invalid")
    assert error.value.status_code == 401


@pytest.mark.parametrize("value", [None, False, True, "true", 1, 1.0, "admin", [], {}])
async def test_only_exact_boolean_platform_claim_is_admitted(claims: Any, value: Any) -> None:
    claims["platform_admin"] = value
    result = await auth.get_current_user("Bearer verified-token")
    assert result == {"uid": UID, "email": "test@example.invalid", "platform_admin": value is True}
    assert set(result) == {"uid", "email", "platform_admin"}
    auth.firebase_auth.verify_id_token.assert_called_once_with("verified-token")


async def test_absent_platform_claim_and_email_do_not_grant_authority(claims: Any) -> None:
    del claims["platform_admin"]
    claims["email"] = "admin@administrator.example.invalid"
    claims["admin"] = True
    result = await auth.get_current_user("Bearer valid")
    assert not result["platform_admin"]


@pytest.mark.parametrize("uid", [None, "", 12])
async def test_invalid_verified_identity_fails_closed(claims: Any, uid: Any) -> None:
    claims["uid"] = uid
    with pytest.raises(HTTPException) as error:
        await auth.get_current_user("Bearer valid")
    assert error.value.status_code == 401


@pytest.mark.parametrize("value", [False, None, "true", 1, "admin"])
async def test_platform_gate_rejects_nonboolean_authority(value: Any) -> None:
    with pytest.raises(HTTPException) as error:
        await auth.require_platform_admin(user(value))
    assert error.value.status_code == 403


async def test_platform_admin_admitted() -> None:
    principal = user(True)
    assert await auth.require_platform_admin(principal) is principal


@pytest.mark.parametrize("role", ["viewer", "admin"])
async def test_admitted_site_read_roles(db: Database, role: str) -> None:
    db.grant(role)
    assert await auth.require_site_access(SITE_A, user()) == user()
    sql, params = db.calls[-1]
    assert ":uid" in sql and ":site_id" in sql
    assert params == {"uid": UID, "site_id": SITE_A}


@pytest.mark.parametrize(
    "role", [None, "", "owner", "platform_admin", "Admin", "admin ", " viewer", 1]
)
async def test_invalid_stored_roles_fail_closed_without_rewriting(db: Database, role: Any) -> None:
    db.grant(role)
    original = db.connection.execute("SELECT role FROM user_site_access").fetchone()
    for check in (auth.require_site_access, auth.require_site_admin):
        with pytest.raises(HTTPException) as error:
            await check(SITE_A, user())
        assert error.value.status_code == 403
    assert db.connection.execute("SELECT role FROM user_site_access").fetchone() == original
    assert db.commits == 0


async def test_admin_mutation_and_viewer_denial(db: Database) -> None:
    db.grant("viewer")
    with pytest.raises(HTTPException) as error:
        await auth.require_site_admin(SITE_A, user())
    assert error.value.status_code == 403
    db.grant("admin")
    assert await auth.require_site_admin(SITE_A, user()) == user()


@pytest.mark.parametrize(
    "site,uid",
    [
        (SITE_B, UID),
        (SITE_A, "another-user"),
        ("bracon-ash", UID),
        ("' OR 1=1 --", UID),
        (SITE_A, "' OR 1=1 --"),
    ],
)
async def test_exact_membership_and_no_site_inference(db: Database, site: str, uid: str) -> None:
    db.grant("admin")
    with pytest.raises(HTTPException) as error:
        await auth.require_site_access(site, {**user(), "uid": uid})
    assert error.value.status_code == 403
    assert db.calls[-1][1] == {"uid": uid, "site_id": site}


async def test_no_membership_denied(db: Database) -> None:
    with pytest.raises(HTTPException) as error:
        await auth.require_site_access(SITE_A, user())
    assert error.value.status_code == 403


async def test_platform_admin_bypass_does_not_query_membership(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def forbidden() -> Any:
        raise AssertionError("membership lookup on explicit platform bypass")

    monkeypatch.setattr(auth, "get_session_factory", forbidden)
    assert await auth.require_site_access(SITE_B, user(True)) == user(True)
    assert await auth.require_site_admin(SITE_B, user(True)) == user(True)


async def test_site_listing_excludes_invalid_roles_and_platform_lists_all(db: Database) -> None:
    db.grant("viewer")
    db.grant("owner", SITE_B)
    assert await auth.get_user_sites(user()) == [SITE_A]
    assert await auth.get_user_sites(user(True)) == [SITE_A, SITE_B]
