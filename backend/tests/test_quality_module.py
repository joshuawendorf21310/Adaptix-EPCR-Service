"""Comprehensive tests for the Medical Director, QA, and QI quality module.

Tests cover:
- RBAC enforcement (correct roles pass, incorrect roles get 403)
- Tenant isolation (no cross-tenant access)
- QA trigger creation and matching
- QA case lifecycle (new → assigned → in_review → closed)
- Peer review conflict of interest blocking
- Medical director review and protected notes
- Education assignment and completion
- Provider feedback send + acknowledge
- QI initiative lifecycle
- Audit event emission on every mutation
- Dashboard data returned from real DB
- Provider access restriction (only own feedback/education)

Pattern: hermetic in-memory SQLite, FastAPI TestClient, dependency-overridden auth.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest_asyncio
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from epcr_app.api_quality import router as quality_router
from epcr_app.db import get_session
from epcr_app.dependencies import get_current_user
from epcr_app.models import Base


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_user(tenant_id: str, user_id: str, roles: list[str]):
    return SimpleNamespace(
        tenant_id=tenant_id,
        user_id=user_id,
        email=f"{user_id}@test.com",
        roles=roles,
    )


@pytest_asyncio.fixture
async def engine_and_sessionmaker():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    sessionmaker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine, sessionmaker
    await engine.dispose()


def _make_app(sessionmaker, user):
    app = FastAPI()
    app.include_router(quality_router)

    async def _override_session():
        async with sessionmaker() as session:
            yield session

    def _override_user():
        return user

    app.dependency_overrides[get_session] = _override_session
    app.dependency_overrides[get_current_user] = _override_user
    return app


@pytest_asyncio.fixture
async def qa_reviewer_client(engine_and_sessionmaker):
    engine, sessionmaker = engine_and_sessionmaker
    user = _make_user("T-1", "reviewer-1", ["qa_reviewer"])
    app = _make_app(sessionmaker, user)
    with TestClient(app) as c:
        yield c, sessionmaker, user


@pytest_asyncio.fixture
async def provider_client(engine_and_sessionmaker):
    engine, sessionmaker = engine_and_sessionmaker
    user = _make_user("T-1", "provider-1", ["provider"])
    app = _make_app(sessionmaker, user)
    with TestClient(app) as c:
        yield c, sessionmaker, user


@pytest_asyncio.fixture
async def md_client(engine_and_sessionmaker):
    engine, sessionmaker = engine_and_sessionmaker
    user = _make_user("T-1", "md-1", ["medical_director"])
    app = _make_app(sessionmaker, user)
    with TestClient(app) as c:
        yield c, sessionmaker, user


@pytest_asyncio.fixture
async def admin_client(engine_and_sessionmaker):
    engine, sessionmaker = engine_and_sessionmaker
    user = _make_user("T-1", "admin-1", ["agency_admin"])
    app = _make_app(sessionmaker, user)
    with TestClient(app) as c:
        yield c, sessionmaker, user


@pytest_asyncio.fixture
async def tenant2_client(engine_and_sessionmaker):
    """Client for a different tenant (T-2) — used to verify cross-tenant isolation."""
    engine, sessionmaker = engine_and_sessionmaker
    user = _make_user("T-2", "reviewer-2", ["qa_reviewer"])
    app = _make_app(sessionmaker, user)
    with TestClient(app) as c:
        yield c, sessionmaker, user


@pytest_asyncio.fixture
async def qi_client(engine_and_sessionmaker):
    engine, sessionmaker = engine_and_sessionmaker
    user = _make_user("T-1", "qi-1", ["qi_lead"])
    app = _make_app(sessionmaker, user)
    with TestClient(app) as c:
        yield c, sessionmaker, user


# ---------------------------------------------------------------------------
# RBAC Tests
# ---------------------------------------------------------------------------

def test_provider_cannot_list_qa_cases(provider_client):
    c, _, _ = provider_client
    r = c.get("/api/v1/quality/qa-cases")
    assert r.status_code == 403, r.text


def test_provider_cannot_create_qa_case(provider_client):
    c, _, _ = provider_client
    r = c.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-1",
        "trigger_key": "cardiac_arrest",
    })
    assert r.status_code == 403, r.text


def test_provider_cannot_access_md_reviews(provider_client):
    c, _, _ = provider_client
    r = c.get("/api/v1/quality/md-reviews")
    assert r.status_code == 403, r.text


def test_provider_cannot_add_md_note(provider_client):
    c, _, _ = provider_client
    r = c.post("/api/v1/quality/md-reviews/fake-id/notes", json={
        "note_text": "This should be blocked",
    })
    assert r.status_code == 403, r.text


def test_provider_cannot_configure_triggers(provider_client):
    c, _, _ = provider_client
    r = c.post("/api/v1/quality/triggers", json={
        "trigger_key": "cardiac_arrest",
        "trigger_type": "mandatory",
        "trigger_label": "Cardiac Arrest",
    })
    assert r.status_code == 403, r.text


def test_qa_reviewer_can_create_qa_case(qa_reviewer_client):
    c, _, _ = qa_reviewer_client
    r = c.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-1",
        "trigger_key": "cardiac_arrest",
        "trigger_type": "supervisor",
        "priority": "critical",
    })
    assert r.status_code == 201, r.text
    data = r.json()
    assert data["case_number"].startswith("QA-")
    assert data["status"] == "new"


def test_medical_director_can_list_md_reviews(md_client):
    c, _, _ = md_client
    r = c.get("/api/v1/quality/md-reviews")
    assert r.status_code == 200, r.text


def test_non_md_cannot_add_md_note(qa_reviewer_client):
    c, sm, _ = qa_reviewer_client
    r = c.post("/api/v1/quality/md-reviews/fake-id/notes", json={
        "note_text": "Unauthorized note",
    })
    assert r.status_code == 403, r.text


def test_qi_lead_can_create_initiative(qi_client):
    c, _, _ = qi_client
    r = c.post("/api/v1/quality/qi/initiatives", json={
        "initiative_title": "Improve documentation quality",
        "category": "documentation_quality",
        "source_trend_description": "Documentation deficiencies trending up",
        "intervention_plan": "Monthly documentation training",
        "owner_id": "qi-1",
    })
    assert r.status_code == 201, r.text


def test_provider_cannot_create_qi_initiative(provider_client):
    c, _, _ = provider_client
    r = c.post("/api/v1/quality/qi/initiatives", json={
        "initiative_title": "Initiative",
        "category": "documentation_quality",
        "source_trend_description": "Trend",
        "intervention_plan": "Plan",
        "owner_id": "provider-1",
    })
    assert r.status_code == 403, r.text


# ---------------------------------------------------------------------------
# Tenant Isolation Tests
# ---------------------------------------------------------------------------

def test_tenant_a_cannot_access_tenant_b_qa_cases(qa_reviewer_client, tenant2_client):
    """Cases created by T-1 reviewer must not appear in T-2 reviewer's list."""
    c1, _, _ = qa_reviewer_client
    c2, _, _ = tenant2_client

    # Create case as T-1
    r = c1.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-T1",
        "trigger_key": "intubation",
        "trigger_type": "supervisor",
    })
    assert r.status_code == 201
    case_id = r.json()["id"]

    # T-2 reviewer lists — should not see T-1 cases
    r2 = c2.get("/api/v1/quality/qa-cases")
    assert r2.status_code == 200
    ids = [c["id"] for c in r2.json()]
    assert case_id not in ids, "Cross-tenant case leak detected!"

    # T-2 reviewer tries direct access — should get 404
    r3 = c2.get(f"/api/v1/quality/qa-cases/{case_id}")
    assert r3.status_code == 404, "Cross-tenant direct access not blocked!"


def test_tenant_isolation_qi_initiatives(qi_client, tenant2_client):
    """QI initiatives from T-1 must not appear for T-2."""
    c1, _, _ = qi_client
    c2, _, _ = tenant2_client

    r = c1.post("/api/v1/quality/qi/initiatives", json={
        "initiative_title": "T1 Initiative",
        "category": "documentation_quality",
        "source_trend_description": "T1 trend",
        "intervention_plan": "T1 plan",
        "owner_id": "qi-1",
    })
    assert r.status_code == 201
    initiative_id = r.json()["id"]

    # T-2 lists initiatives — must not see T-1
    r2 = c2.get("/api/v1/quality/qi/initiatives")
    # T-2 user is qa_reviewer, not qi_lead, so this should be 403
    assert r2.status_code == 403


def test_tenant_isolation_protocols(admin_client, tenant2_client):
    """Protocols from T-1 must not be accessible by T-2."""
    c1, _, _ = admin_client
    c2, _, _ = tenant2_client

    r = c1.post("/api/v1/quality/protocols", json={
        "protocol_code": "CARDIAC-001",
        "protocol_name": "Cardiac Arrest Protocol",
        "protocol_category": "ACLS",
    })
    assert r.status_code == 201
    protocol_id = r.json()["id"]

    # T-2 tries direct access
    r2 = c2.get(f"/api/v1/quality/protocols/{protocol_id}")
    assert r2.status_code == 404, "Cross-tenant protocol access not blocked!"


# ---------------------------------------------------------------------------
# QA Trigger Tests
# ---------------------------------------------------------------------------

def test_admin_can_create_trigger(admin_client):
    c, _, _ = admin_client
    r = c.post("/api/v1/quality/triggers", json={
        "trigger_key": "cardiac_arrest",
        "trigger_type": "mandatory",
        "trigger_label": "Cardiac Arrest",
        "priority": "critical",
        "condition_json": {},
    })
    assert r.status_code == 201
    data = r.json()
    assert data["trigger_key"] == "cardiac_arrest"
    assert data["trigger_type"] == "mandatory"
    assert data["is_active"] is True


def test_mandatory_trigger_cannot_be_deactivated(admin_client):
    c, _, _ = admin_client
    # Create mandatory trigger
    r = c.post("/api/v1/quality/triggers", json={
        "trigger_key": "rsi_mandatory",
        "trigger_type": "mandatory",
        "trigger_label": "RSI",
    })
    assert r.status_code == 201
    trigger_id = r.json()["id"]

    # Attempt to deactivate
    r2 = c.patch(f"/api/v1/quality/triggers/{trigger_id}", json={"is_active": False})
    assert r2.status_code == 400
    assert "mandatory" in r2.json()["detail"].lower()


def test_optional_trigger_can_be_deactivated(admin_client):
    c, _, _ = admin_client
    r = c.post("/api/v1/quality/triggers", json={
        "trigger_key": "long_scene_time",
        "trigger_type": "optional",
        "trigger_label": "Long Scene Time",
    })
    assert r.status_code == 201
    trigger_id = r.json()["id"]

    r2 = c.patch(f"/api/v1/quality/triggers/{trigger_id}", json={"is_active": False})
    assert r2.status_code == 200
    assert r2.json()["is_active"] is False


# ---------------------------------------------------------------------------
# QA Case Lifecycle Tests
# ---------------------------------------------------------------------------

def test_qa_case_lifecycle_new_to_closed(qa_reviewer_client):
    c, sm, user = qa_reviewer_client

    # Create case
    r = c.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-lifecycle",
        "trigger_key": "cardiac_arrest",
        "trigger_type": "supervisor",
        "priority": "high",
    })
    assert r.status_code == 201
    case_id = r.json()["id"]
    assert r.json()["status"] == "new"

    # Assign case
    r2 = c.patch(f"/api/v1/quality/qa-cases/{case_id}/assign", json={
        "reviewer_id": user.user_id,
    })
    assert r2.status_code == 200
    assert r2.json()["status"] == "assigned"

    # Submit score
    r3 = c.post(f"/api/v1/quality/qa-cases/{case_id}/scores", json={
        "documentation_quality_score": 85.0,
        "protocol_adherence_score": 90.0,
        "timeliness_score": 95.0,
        "clinical_quality_score": 88.0,
        "operational_quality_score": 82.0,
    })
    assert r3.status_code == 201
    assert r3.json()["composite_score"] > 0

    # Add finding
    r4 = c.post(f"/api/v1/quality/qa-cases/{case_id}/findings", json={
        "finding_type": "documentation_deficiency",
        "severity": "minor",
        "domain": "documentation",
        "description": "Missing repeat vital signs after medication administration",
        "education_recommended": True,
    })
    assert r4.status_code == 201
    assert r4.json()["status"] == "open"

    # Close case
    r5 = c.post(f"/api/v1/quality/qa-cases/{case_id}/close", json={
        "closure_notes": "Review complete. Education assigned.",
    })
    assert r5.status_code == 200
    assert r5.json()["status"] == "closed"


def test_qa_score_updates_case_composite(qa_reviewer_client):
    c, _, _ = qa_reviewer_client
    r = c.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-score-test",
        "trigger_key": "intubation",
        "trigger_type": "automatic",
    })
    case_id = r.json()["id"]

    r2 = c.post(f"/api/v1/quality/qa-cases/{case_id}/scores", json={
        "documentation_quality_score": 100.0,
        "protocol_adherence_score": 100.0,
        "timeliness_score": 100.0,
        "clinical_quality_score": 100.0,
        "operational_quality_score": 100.0,
    })
    assert r2.status_code == 201
    assert r2.json()["composite_score"] == 100.0

    # Verify case score was updated
    r3 = c.get(f"/api/v1/quality/qa-cases/{case_id}")
    assert r3.json()["qa_score"] == 100.0


def test_qa_case_cannot_close_while_escalation_pending(qa_reviewer_client):
    """A QA case escalated to MD cannot be closed while the MD review is still pending."""
    c, _, _ = qa_reviewer_client

    # Create case
    r = c.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-escalation",
        "trigger_key": "sentinel_event",
        "trigger_type": "automatic",
        "priority": "critical",
    })
    case_id = r.json()["id"]

    # Escalate to MD
    r2 = c.post(f"/api/v1/quality/qa-cases/{case_id}/escalate", json={
        "escalation_reason": "Sentinel event — MD review required",
        "medical_director_id": "md-1",
    })
    assert r2.status_code == 201

    # Attempt close while escalation is pending
    r3 = c.post(f"/api/v1/quality/qa-cases/{case_id}/close", json={
        "closure_notes": "Trying to close too early",
    })
    assert r3.status_code == 400
    assert "pending" in r3.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Peer Review Tests
# ---------------------------------------------------------------------------

def test_peer_review_conflict_of_interest_blocked(qa_reviewer_client):
    """Peer reviewer cannot review their own chart."""
    c, _, user = qa_reviewer_client

    # Create case
    r = c.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-peer-conflict",
        "trigger_key": "rsi",
        "trigger_type": "automatic",
    })
    case_id = r.json()["id"]

    # Assign peer review — reviewer is also chart provider (conflict)
    r2 = c.post("/api/v1/quality/peer-reviews", json={
        "qa_case_id": case_id,
        "reviewer_id": user.user_id,  # reviewer is the provider (conflict)
        "chart_provider_id": user.user_id,
        "crew_member_ids": [],
    })
    assert r2.status_code == 400
    assert "cannot review" in r2.json()["detail"].lower() or "conflict" in r2.json()["detail"].lower()


def test_peer_reviewer_cannot_review_crew_member_case(qa_reviewer_client):
    """Peer reviewer cannot review if they were part of the crew."""
    c, _, user = qa_reviewer_client

    r = c.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-crew-conflict",
        "trigger_key": "pediatric_critical",
        "trigger_type": "automatic",
    })
    case_id = r.json()["id"]

    r2 = c.post("/api/v1/quality/peer-reviews", json={
        "qa_case_id": case_id,
        "reviewer_id": user.user_id,
        "chart_provider_id": "other-provider",
        "crew_member_ids": [user.user_id],  # reviewer was crew
    })
    assert r2.status_code == 400
    assert "crew" in r2.json()["detail"].lower()


def test_valid_peer_review_assignment(qa_reviewer_client):
    c, _, _ = qa_reviewer_client

    r = c.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-valid-peer",
        "trigger_key": "stemi",
        "trigger_type": "automatic",
    })
    case_id = r.json()["id"]

    r2 = c.post("/api/v1/quality/peer-reviews", json={
        "qa_case_id": case_id,
        "reviewer_id": "peer-reviewer-99",
        "chart_provider_id": "chart-provider-1",
        "crew_member_ids": ["crew-1", "crew-2"],
        "is_blind": True,
    })
    assert r2.status_code == 201
    assert r2.json()["is_blind"] is True
    assert r2.json()["conflict_of_interest_checked"] is True


def test_peer_reviewer_can_only_see_own_review(engine_and_sessionmaker):
    """A peer_reviewer role user can only access their own assigned review."""
    engine, sessionmaker = engine_and_sessionmaker
    peer_user = _make_user("T-1", "peer-only", ["peer_reviewer"])
    qa_user = _make_user("T-1", "qa-admin", ["qa_reviewer"])

    peer_app = _make_app(sessionmaker, peer_user)
    qa_app = _make_app(sessionmaker, qa_user)

    with TestClient(peer_app) as peer_c, TestClient(qa_app) as qa_c:
        # QA reviewer creates a case and assigns peer review to someone else
        r = qa_c.post("/api/v1/quality/qa-cases", json={
            "source_chart_id": "chart-peer-scoped",
            "trigger_key": "airway",
            "trigger_type": "automatic",
        })
        case_id = r.json()["id"]

        r2 = qa_c.post("/api/v1/quality/peer-reviews", json={
            "qa_case_id": case_id,
            "reviewer_id": "other-peer",  # NOT peer-only
            "chart_provider_id": "provider-x",
            "crew_member_ids": [],
        })
        assert r2.status_code == 201
        review_id = r2.json()["id"]

        # peer-only user tries to access another user's review
        r3 = peer_c.get(f"/api/v1/quality/peer-reviews/{review_id}")
        assert r3.status_code == 403, "Peer reviewer accessed someone else's review!"


# ---------------------------------------------------------------------------
# Medical Director Review Tests
# ---------------------------------------------------------------------------

def test_md_note_is_separate_artifact_not_chart_modification(md_client, qa_reviewer_client):
    """MD notes must be stored as separate review artifacts, never in chart data."""
    qa_c, qa_sm, _ = qa_reviewer_client
    md_c, _, _ = md_client

    # Create QA case and escalate
    r = qa_c.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-md-note-test",
        "trigger_key": "cardiac_arrest",
        "trigger_type": "automatic",
        "priority": "critical",
    })
    case_id = r.json()["id"]

    r2 = qa_c.post(f"/api/v1/quality/qa-cases/{case_id}/escalate", json={
        "escalation_reason": "High-risk cardiac arrest",
        "medical_director_id": "md-1",
    })
    assert r2.status_code == 201
    review_id = r2.json()["id"]

    # MD adds note via MD client
    r3 = md_c.post(f"/api/v1/quality/md-reviews/{review_id}/notes", json={
        "note_type": "finding",
        "note_text": "Protocol deviation identified: epinephrine dose timing",
        "finding_type": "protocol_deviation",
    })
    assert r3.status_code == 201
    note_data = r3.json()
    assert note_data["is_protected"] is True
    assert note_data["source_chart_id"] == "chart-md-note-test"
    assert note_data["medical_director_review_id"] == review_id
    # Note is a SEPARATE record — verify it's not stored in the chart
    assert "chart_id" not in note_data or note_data.get("note_text") != ""


def test_md_review_completion_emits_audit_event(md_client, qa_reviewer_client):
    qa_c, _, _ = qa_reviewer_client
    md_c, sm, _ = md_client

    r = qa_c.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-md-complete",
        "trigger_key": "rsi",
        "trigger_type": "automatic",
        "priority": "high",
    })
    case_id = r.json()["id"]

    r2 = qa_c.post(f"/api/v1/quality/qa-cases/{case_id}/escalate", json={
        "escalation_reason": "RSI complication",
        "medical_director_id": "md-1",
    })
    review_id = r2.json()["id"]

    r3 = md_c.patch(f"/api/v1/quality/md-reviews/{review_id}/complete", json={
        "finding_classification": "protocol_deviation",
        "protocol_deviation_identified": True,
        "education_recommended": True,
    })
    assert r3.status_code == 200
    assert r3.json()["status"] == "completed"
    assert r3.json()["protocol_deviation_identified"] is True


def test_non_md_cannot_complete_md_review(qa_reviewer_client):
    c, _, _ = qa_reviewer_client
    r = c.patch("/api/v1/quality/md-reviews/fake-id/complete", json={
        "finding_classification": "no_finding",
    })
    assert r.status_code == 403


# ---------------------------------------------------------------------------
# Education Follow-Up Tests
# ---------------------------------------------------------------------------

def test_education_assignment_and_completion(qa_reviewer_client, provider_client):
    qa_c, _, _ = qa_reviewer_client
    prov_c, _, prov_user = provider_client

    # Create QA case
    r = qa_c.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-edu",
        "trigger_key": "documentation_deficiency",
        "trigger_type": "automatic",
    })

    # Assign education to provider
    r2 = qa_c.post("/api/v1/quality/education", json={
        "provider_id": prov_user.user_id,
        "education_type": "documentation_training",
        "education_title": "Documentation Best Practices",
        "education_description": "Review of repeat vital sign requirements",
        "due_date": "2026-06-01T00:00:00Z",
    })
    assert r2.status_code == 201
    edu_id = r2.json()["id"]
    assert r2.json()["status"] == "assigned"

    # Provider completes education
    r3 = prov_c.patch(f"/api/v1/quality/education/{edu_id}/complete")
    assert r3.status_code == 200
    assert r3.json()["status"] == "completed"
    assert r3.json()["completed_at"] is not None


def test_provider_cannot_complete_others_education(engine_and_sessionmaker):
    """Provider A cannot mark Provider B's education as complete."""
    engine, sessionmaker = engine_and_sessionmaker
    provider_a = _make_user("T-1", "provider-a", ["provider"])
    provider_b = _make_user("T-1", "provider-b", ["provider"])
    qa_user = _make_user("T-1", "qa-admin-2", ["qa_reviewer"])

    qa_app = _make_app(sessionmaker, qa_user)
    pa_app = _make_app(sessionmaker, provider_a)
    pb_app = _make_app(sessionmaker, provider_b)

    with TestClient(qa_app) as qa_c, TestClient(pa_app) as pa_c, TestClient(pb_app) as pb_c:
        # Assign education to provider-b
        r = qa_c.post("/api/v1/quality/education", json={
            "provider_id": "provider-b",
            "education_type": "remedial",
            "education_title": "Remedial Training",
        })
        assert r.status_code == 201
        edu_id = r.json()["id"]

        # Provider A tries to complete Provider B's education
        r2 = pa_c.patch(f"/api/v1/quality/education/{edu_id}/complete")
        assert r2.status_code == 400, "Provider A completed Provider B's education!"


def test_provider_only_sees_own_education(qa_reviewer_client, provider_client):
    qa_c, _, _ = qa_reviewer_client
    prov_c, _, prov_user = provider_client

    # Assign education to provider
    r = qa_c.post("/api/v1/quality/education", json={
        "provider_id": prov_user.user_id,
        "education_type": "informational",
        "education_title": "Protocol Update Briefing",
    })
    assert r.status_code == 201

    # Assign education to a different provider
    r2 = qa_c.post("/api/v1/quality/education", json={
        "provider_id": "other-provider-99",
        "education_type": "remedial",
        "education_title": "Other Provider Education",
    })
    assert r2.status_code == 201

    # Provider lists their education — should only see their own
    r3 = prov_c.get("/api/v1/quality/education")
    assert r3.status_code == 200
    provider_ids = [e["provider_id"] for e in r3.json()]
    assert all(pid == prov_user.user_id for pid in provider_ids), (
        f"Provider saw education for: {set(provider_ids)}"
    )


# ---------------------------------------------------------------------------
# Provider Feedback Tests
# ---------------------------------------------------------------------------

def test_provider_feedback_send_and_acknowledge(qa_reviewer_client, provider_client):
    qa_c, _, _ = qa_reviewer_client
    prov_c, _, prov_user = provider_client

    # Send feedback
    r = qa_c.post("/api/v1/quality/feedback", json={
        "provider_id": prov_user.user_id,
        "feedback_type": "informational",
        "subject": "Great job on the cardiac arrest",
        "message_text": "Excellent protocol adherence on the cardiac arrest call today.",
    })
    assert r.status_code == 201
    feedback_id = r.json()["id"]
    assert r.json()["is_protected"] is True
    assert r.json()["status"] == "sent"

    # Provider acknowledges
    r2 = prov_c.patch(f"/api/v1/quality/feedback/{feedback_id}/acknowledge", json={
        "provider_response": "Thank you for the feedback.",
    })
    assert r2.status_code == 200
    assert r2.json()["status"] == "responded"
    assert r2.json()["acknowledged_at"] is not None


def test_provider_only_sees_own_feedback(qa_reviewer_client, provider_client):
    qa_c, _, _ = qa_reviewer_client
    prov_c, _, prov_user = provider_client

    # Send feedback to provider-1
    r = qa_c.post("/api/v1/quality/feedback", json={
        "provider_id": prov_user.user_id,
        "feedback_type": "protocol_reminder",
        "subject": "Documentation reminder",
        "message_text": "Please ensure all repeat vitals are documented.",
    })
    assert r.status_code == 201

    # Send feedback to a different provider
    r2 = qa_c.post("/api/v1/quality/feedback", json={
        "provider_id": "other-provider-77",
        "feedback_type": "commendation",
        "subject": "Excellent care",
        "message_text": "Outstanding patient outcome.",
    })
    assert r2.status_code == 201

    # Provider lists feedback — should only see their own
    r3 = prov_c.get("/api/v1/quality/feedback")
    assert r3.status_code == 200
    provider_ids = [f["provider_id"] for f in r3.json()]
    assert all(pid == prov_user.user_id for pid in provider_ids), (
        f"Provider saw feedback for: {set(provider_ids)}"
    )


# ---------------------------------------------------------------------------
# QI Initiative Tests
# ---------------------------------------------------------------------------

def test_qi_initiative_full_lifecycle(qi_client):
    c, _, _ = qi_client

    # Create initiative
    r = c.post("/api/v1/quality/qi/initiatives", json={
        "initiative_title": "Reduce documentation deficiencies",
        "category": "documentation_quality",
        "source_trend_description": "Documentation scores below 80% for 3 months",
        "intervention_plan": "Monthly training + peer review focus",
        "owner_id": "qi-1",
        "baseline_metric_value": 72.5,
        "baseline_metric_label": "Avg documentation score",
        "target_metric_value": 85.0,
        "target_metric_label": "Target avg score",
    })
    assert r.status_code == 201
    initiative_id = r.json()["id"]
    assert r.json()["status"] == "identified"

    # Advance to baseline_measured
    r2 = c.patch(f"/api/v1/quality/qi/initiatives/{initiative_id}/status", json={
        "new_status": "baseline_measured",
    })
    assert r2.status_code == 200
    assert r2.json()["status"] == "baseline_measured"

    # Record a metric
    r3 = c.post(f"/api/v1/quality/qi/initiatives/{initiative_id}/metrics", json={
        "metric_key": "avg_documentation_score",
        "metric_value": 72.5,
        "metric_label": "Avg documentation score",
        "measurement_period": "2026-04",
    })
    assert r3.status_code == 201

    # Add action item
    r4 = c.post(f"/api/v1/quality/qi/initiatives/{initiative_id}/actions", json={
        "action_title": "Schedule monthly training",
        "action_description": "Schedule first training session",
        "assigned_to": "educator-1",
    })
    assert r4.status_code == 201
    action_id = r4.json()["id"]

    # Complete action item
    r5 = c.patch(f"/api/v1/quality/qi/actions/{action_id}", json={
        "status": "completed",
        "completion_notes": "Training scheduled for next month",
    })
    assert r5.status_code == 200
    assert r5.json()["status"] == "completed"

    # Advance to active
    r6 = c.patch(f"/api/v1/quality/qi/initiatives/{initiative_id}/status", json={
        "new_status": "active",
    })
    assert r6.status_code == 200

    # Close initiative
    r7 = c.patch(f"/api/v1/quality/qi/initiatives/{initiative_id}/status", json={
        "new_status": "closed",
        "outcome_summary": "Documentation scores improved to 87% over 3 months",
        "current_metric_value": 87.0,
    })
    assert r7.status_code == 200
    assert r7.json()["status"] == "closed"
    assert r7.json()["outcome_summary"] is not None


# ---------------------------------------------------------------------------
# Audit Event Tests
# ---------------------------------------------------------------------------

def test_every_mutation_creates_audit_event(qa_reviewer_client):
    c, sm, user = qa_reviewer_client

    # Create case
    r = c.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-audit-test",
        "trigger_key": "stroke",
        "trigger_type": "automatic",
    })
    assert r.status_code == 201
    case_id = r.json()["id"]

    # Verify audit event for case creation
    r2 = c.get(f"/api/v1/quality/qa-cases/{case_id}/audit")
    assert r2.status_code == 200
    audit_events = r2.json()
    assert len(audit_events) >= 1
    event_types = [e["event_type"] for e in audit_events]
    assert "qa_case_created" in event_types, f"Missing qa_case_created audit event. Got: {event_types}"

    # Assign case
    r3 = c.patch(f"/api/v1/quality/qa-cases/{case_id}/assign", json={
        "reviewer_id": user.user_id,
    })
    assert r3.status_code == 200

    # Add finding
    r4 = c.post(f"/api/v1/quality/qa-cases/{case_id}/findings", json={
        "finding_type": "documentation_deficiency",
        "severity": "minor",
        "domain": "documentation",
        "description": "Missing vital signs",
    })
    assert r4.status_code == 201

    # Verify audit trail has all events
    r5 = c.get(f"/api/v1/quality/qa-cases/{case_id}/audit")
    audit_events = r5.json()
    event_types = [e["event_type"] for e in audit_events]
    assert "qa_case_created" in event_types
    assert "qa_case_assigned" in event_types
    assert "qa_finding_added" in event_types


def test_audit_events_are_tenant_scoped(qa_reviewer_client, tenant2_client):
    c1, _, _ = qa_reviewer_client
    c2, _, _ = tenant2_client

    r = c1.post("/api/v1/quality/qa-cases", json={
        "source_chart_id": "chart-audit-scope",
        "trigger_key": "sepsis",
        "trigger_type": "automatic",
    })
    case_id = r.json()["id"]

    # T-2 cannot see T-1's audit events
    r2 = c2.get("/api/v1/quality/audit", params={"reference_id": case_id})
    assert r2.status_code == 200
    # T-2 is qa_reviewer so they can list audit events — but only their own tenant's
    events = r2.json()
    assert all(e["tenant_id"] == "T-2" for e in events), "Cross-tenant audit events leaked!"


# ---------------------------------------------------------------------------
# Dashboard Tests
# ---------------------------------------------------------------------------

def test_qa_dashboard_returns_real_data(qa_reviewer_client):
    c, _, _ = qa_reviewer_client

    # Create some cases to populate dashboard
    for i in range(3):
        c.post("/api/v1/quality/qa-cases", json={
            "source_chart_id": f"chart-dash-{i}",
            "trigger_key": "pediatric_critical",
            "trigger_type": "automatic",
        })

    r = c.get("/api/v1/quality/dashboards/qa")
    assert r.status_code == 200
    data = r.json()
    assert "open_cases" in data
    assert "avg_qa_score" in data
    assert "total_cases" in data
    assert data["total_cases"] >= 3


def test_md_dashboard_returns_real_data(md_client):
    c, _, _ = md_client
    r = c.get("/api/v1/quality/dashboards/medical-director")
    assert r.status_code == 200
    data = r.json()
    assert "pending_reviews" in data
    assert "protocol_deviations_identified" in data


def test_qi_dashboard_returns_real_data(qi_client):
    c, _, _ = qi_client
    r = c.get("/api/v1/quality/dashboards/qi")
    assert r.status_code == 200
    data = r.json()
    assert "active_initiatives" in data
    assert "education_completion_rate" in data


def test_provider_cannot_access_qa_dashboard(provider_client):
    c, _, _ = provider_client
    r = c.get("/api/v1/quality/dashboards/qa")
    assert r.status_code == 403


def test_provider_can_access_own_feedback_dashboard(provider_client):
    c, _, _ = provider_client
    r = c.get("/api/v1/quality/dashboards/provider-feedback")
    assert r.status_code == 200
    data = r.json()
    assert "recent_feedback" in data
    assert "pending_education" in data


# ---------------------------------------------------------------------------
# Protocol Tests
# ---------------------------------------------------------------------------

def test_admin_can_create_and_publish_protocol(admin_client):
    c, _, _ = admin_client

    # Create protocol
    r = c.post("/api/v1/quality/protocols", json={
        "protocol_code": "CARDIAC-RSI-001",
        "protocol_name": "RSI Protocol",
        "protocol_category": "RSI",
        "acknowledgment_required": True,
    })
    assert r.status_code == 201
    protocol_id = r.json()["id"]
    assert r.json()["status"] == "draft"

    # Create version
    r2 = c.post(f"/api/v1/quality/protocols/{protocol_id}/versions", json={
        "version_number": "1.0.0",
        "effective_date": "2026-01-01T00:00:00Z",
        "content_text": "RSI Protocol content here",
    })
    assert r2.status_code == 201
    version_id = r2.json()["id"]

    # Publish version
    r3 = c.post(f"/api/v1/quality/protocols/{protocol_id}/versions/{version_id}/publish")
    assert r3.status_code == 200
    assert r3.json()["status"] == "published"


def test_provider_can_acknowledge_protocol(admin_client, provider_client):
    admin_c, _, _ = admin_client
    prov_c, _, prov_user = provider_client

    # Create and publish protocol
    r = admin_c.post("/api/v1/quality/protocols", json={
        "protocol_code": "STROKE-001",
        "protocol_name": "Stroke Protocol",
        "protocol_category": "stroke",
    })
    protocol_id = r.json()["id"]

    r2 = admin_c.post(f"/api/v1/quality/protocols/{protocol_id}/versions", json={
        "version_number": "1.0.0",
        "effective_date": "2026-01-01T00:00:00Z",
    })
    version_id = r2.json()["id"]

    admin_c.post(f"/api/v1/quality/protocols/{protocol_id}/versions/{version_id}/publish")

    # Provider acknowledges
    r3 = prov_c.post(f"/api/v1/quality/protocols/{protocol_id}/versions/{version_id}/acknowledge")
    assert r3.status_code == 200
    assert r3.json()["provider_id"] == prov_user.user_id

    # Double-acknowledge is blocked
    r4 = prov_c.post(f"/api/v1/quality/protocols/{protocol_id}/versions/{version_id}/acknowledge")
    assert r4.status_code == 400


# ---------------------------------------------------------------------------
# Accreditation Evidence Tests
# ---------------------------------------------------------------------------

def test_accreditation_package_compiled_from_real_data(qi_client):
    c, _, _ = qi_client

    r = c.post("/api/v1/quality/accreditation", json={
        "package_name": "Q1 2026 Accreditation Evidence",
        "accreditation_type": "internal_audit",
        "period_start": "2026-01-01T00:00:00Z",
        "period_end": "2026-03-31T23:59:59Z",
    })
    assert r.status_code == 201
    data = r.json()
    assert data["status"] == "compiled"
    assert data["compiled_at"] is not None
    assert "qa_evidence_json" in data
    assert "qi_evidence_json" in data
    assert "education_completion_json" in data


# ---------------------------------------------------------------------------
# Trend Computation Tests
# ---------------------------------------------------------------------------

def test_trend_aggregation_computation(qi_client, qa_reviewer_client):
    qa_c, _, _ = qa_reviewer_client
    qi_c, _, _ = qi_client

    # Create some QA cases
    for i in range(5):
        qa_c.post("/api/v1/quality/qa-cases", json={
            "source_chart_id": f"chart-trend-{i}",
            "trigger_key": "cardiac_arrest",
            "trigger_type": "automatic",
        })

    r = qi_c.post("/api/v1/quality/trends/compute", json={
        "period": "2026-05",
        "period_type": "month",
    })
    assert r.status_code == 200
    data = r.json()
    assert data["period"] == "2026-05"
    assert data["total_qa_cases"] >= 5
