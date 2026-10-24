"""Removing a roommate, and one person in several flats."""

import uuid
from datetime import datetime

from conftest import Flat

from app import clock
from app.models import Member
from app.services import audit, contributions


def test_owner_removes_a_roommate_and_their_link_stops_working(client, db):
    flat = Flat(client)
    r = client.delete(f"/api/members/{flat.roommate_id}", headers=flat.owner)
    assert r.status_code == 200
    body = r.json()
    assert body["member_id"] == flat.roommate_id and body["month"] == "2026-10"
    assert body["final_balance_paise"] == 800_000  # topped up ₹8,000, nothing spent yet
    assert client.get("/api/me", headers=flat.roommate).status_code == 403
    # They still settle October (removed during it), but no longer vote.
    names = [m["name"] for m in flat.dashboard()["contributions"]]
    assert names == ["Asha", "Ravi"]
    rid = flat.ask("create_advance_request", "m1", amount_paise=60_000)["request_id"]
    vote_card = flat.dashboard()["open_votes"][0]
    assert vote_card["request_id"] == rid and vote_card["votes_needed"] == 1
    assert audit.verify(db)


def test_removal_settles_open_votes(client):
    flat = Flat(client, advance_monthly_limit_paise=80_000)
    flat.ask("create_advance_request", "m2", amount_paise=50_000)
    rid = flat.ask("create_advance_request", "m3", amount_paise=50_000)["request_id"]  # over the month: needs both
    client.post(f"/api/requests/{rid}/votes", headers=flat.owner, json={"decision": "approve"})
    client.delete(f"/api/members/{flat.roommate_id}", headers=flat.owner)
    requests_ = client.get(f"/api/households/{flat.hid}/requests", headers=flat.owner).json()
    assert next(r for r in requests_ if r["id"] == rid)["status"] == "executed"


def test_removed_members_pending_votes_are_withdrawn(client):
    flat = Flat(client, advance_monthly_limit_paise=80_000)
    flat.ask("create_advance_request", "m4", amount_paise=50_000)
    rid = flat.ask("create_advance_request", "m5", amount_paise=50_000)["request_id"]
    client.post(f"/api/requests/{rid}/votes", headers=flat.roommate, json={"decision": "approve"})
    client.delete(f"/api/members/{flat.roommate_id}", headers=flat.owner)
    (card,) = flat.dashboard()["open_votes"]
    assert card["request_id"] == rid and card["votes"] == [] and card["votes_needed"] == 1


def test_removal_rules(client):
    flat = Flat(client)
    r = client.delete(f"/api/members/{flat.owner_id}", headers=flat.owner)
    assert r.status_code == 403 and r.json()["error"]["code"] == "cannot_remove_owner"
    r = client.delete(f"/api/members/{flat.owner_id}", headers=flat.roommate)
    assert r.status_code == 403 and r.json()["error"]["code"] == "owner_only"
    assert client.delete(f"/api/members/{uuid.uuid4()}", headers=flat.owner).status_code == 404
    assert client.delete(f"/api/members/{flat.roommate_id}", headers=flat.owner).status_code == 200
    assert client.delete(f"/api/members/{flat.roommate_id}", headers=flat.owner).status_code == 404


def test_member_removed_before_a_month_does_not_share_it(client, db):
    flat = Flat(client)
    member = db.get(Member, uuid.UUID(flat.roommate_id))
    member.removed_at = datetime(2026, 9, 30, 12, 0, tzinfo=clock.IST)
    db.commit()
    month_members = contributions.members_for_month(db, uuid.UUID(flat.hid), "2026-10")
    assert [m.name for m in month_members] == ["Asha"]


def test_the_same_phone_cannot_join_a_flat_twice(client):
    flat = Flat(client)
    r = client.post(
        f"/api/households/{flat.hid}/members",
        headers=flat.owner,
        json={"name": "Ravi again", "phone": "+91 90000 00012"},
    )
    assert r.status_code == 409 and r.json()["error"]["code"] == "member_exists"


def _second_flat_with_asha(client) -> tuple[dict, str]:
    """Ravi owns a second flat and adds Asha (same phone as flat 1's owner). Returns (Asha's flat-2 headers, hid)."""
    r = client.post(
        "/api/households", json={"household_name": "Second Flat", "owner_name": "Ravi", "owner_phone": "9000000012"}
    ).json()
    other_owner = {"X-Roz-Token": r["token"]}
    m = client.post(
        f"/api/households/{r['household_id']}/members",
        headers=other_owner,
        json={"name": "Asha", "phone": "9000000011"},
    ).json()
    return {"X-Roz-Token": m["token"]}, r["household_id"]


def test_one_person_can_link_two_flats(client):
    flat = Flat(client)
    asha_in_flat2, hid2 = _second_flat_with_asha(client)
    # A matching phone alone never joins flats: the owner of flat 2 can't see Asha's flat 1.
    assert len(client.get("/api/me", headers=asha_in_flat2).json()["flats"]) == 1
    r = client.post("/api/me/link", headers=flat.owner, json={"other_token": asha_in_flat2["X-Roz-Token"]})
    assert r.status_code == 200
    flats = r.json()["flats"]
    assert {f["household_id"] for f in flats} == {flat.hid, hid2}
    assert [f["current"] for f in flats if f["household_id"] == flat.hid] == [True]
    from_flat2 = client.get("/api/me", headers=asha_in_flat2).json()
    assert {f["household_id"] for f in from_flat2["flats"]} == {flat.hid, hid2}
    # Each flat link still opens only its own flat's data.
    assert client.get(f"/api/households/{hid2}/dashboard", headers=flat.owner).status_code == 404
    switch = next(f for f in flats if f["household_id"] == hid2)
    assert client.get(f"/api/households/{hid2}/dashboard", headers={"X-Roz-Token": switch["token"]}).status_code == 200


def test_linking_is_idempotent_and_checked(client):
    flat = Flat(client)
    asha_in_flat2, _ = _second_flat_with_asha(client)
    client.post("/api/me/link", headers=flat.owner, json={"other_token": asha_in_flat2["X-Roz-Token"]})
    again = client.post("/api/me/link", headers=asha_in_flat2, json={"other_token": flat.owner["X-Roz-Token"]})
    assert again.status_code == 200 and len(again.json()["flats"]) == 2
    r = client.post("/api/me/link", headers=flat.owner, json={"other_token": flat.roommate["X-Roz-Token"]})
    assert r.status_code == 409 and r.json()["error"]["code"] == "same_household"
    r = client.post("/api/me/link", headers=flat.owner, json={"other_token": "not-a-real-token"})
    assert r.status_code == 404
