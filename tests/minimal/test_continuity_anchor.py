from __future__ import annotations

from core.cognition import build_cognitive_frame
from core.session import Session
from services.cognition.reconciler import CognitiveReconciler


def test_session_continuity_anchor_preserves_objective_across_conversational_turns():
    session = Session("continuity-anchor-test")
    session.update_continuity_anchor(
        user_input="escreva um arquivo de teste.txt com conteudo 123 na minha pasta videos",
        objective_override="escreva um arquivo de teste.txt com conteudo 123 na minha pasta videos",
        objective_state="active",
    )

    session.update_continuity_anchor(
        user_input="oi",
    )

    anchor = session.get_continuity_anchor()
    assert anchor["objective"] == "escreva um arquivo de teste.txt com conteudo 123 na minha pasta videos"
    assert anchor["last_user_input"] == "oi"
    assert anchor["last_substantive_user_input"] == "escreva um arquivo de teste.txt com conteudo 123 na minha pasta videos"
    assert anchor["objective_state"] == "active"


def test_build_cognitive_frame_uses_continuity_anchor_for_greeting_turn():
    session = Session("continuity-frame-test")
    session.state_summary["goal"] = "Standby/Listening"
    session.update_continuity_anchor(
        user_input="escreva um arquivo de teste.txt com conteudo 123 na minha pasta videos",
        objective_override="escreva um arquivo de teste.txt com conteudo 123 na minha pasta videos",
        objective_state="active",
    )

    frame = build_cognitive_frame(session, "oi")

    assert frame.objective == "escreva um arquivo de teste.txt com conteudo 123 na minha pasta videos"
    assert "continuity_anchor" in frame.context_sources


def test_reconciler_preserves_anchor_on_short_follow_up_but_replaces_for_new_request():
    session = Session("continuity-reconciler-test")
    session.update_continuity_anchor(
        user_input="escreva um arquivo de teste.txt com conteudo 123 na minha pasta videos",
        objective_override="escreva um arquivo de teste.txt com conteudo 123 na minha pasta videos",
        objective_state="active",
    )

    reconciler = CognitiveReconciler()

    preserved_state = reconciler.reconcile(
        session=session,
        user_input="oi",
        previous_state=None,
        broker_snapshot=None,
    )
    assert preserved_state.mission.objective == "escreva um arquivo de teste.txt com conteudo 123 na minha pasta videos"

    replaced_state = reconciler.reconcile(
        session=session,
        user_input="mostre a previsão do tempo agora para minha cidade",
        previous_state=None,
        broker_snapshot=None,
    )
    assert replaced_state.mission.objective == "mostre a previsão do tempo agora para minha cidade"
