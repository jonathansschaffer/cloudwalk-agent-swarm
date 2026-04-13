"""
Manual integration test script.
Sends all example scenarios from the challenge README and prints results.

Usage:
    python scripts/test_agents.py
"""

import sys
import json
import time

sys.path.insert(0, ".")

from app.utils.logger import setup_logging
from app.config import validate_config
from app.agents.router_agent import process_message

setup_logging()

TEST_SCENARIOS = [
    {
        "id": 1,
        "description": "Product fee question (EN)",
        "message": "What are the fees of the Maquininha Smart",
        "user_id": "client789",
        "expected_intent": "KNOWLEDGE_PRODUCT",
        "expected_agent": "knowledge_agent",
    },
    {
        "id": 2,
        "description": "Product cost question (EN)",
        "message": "What is the cost of the Maquininha Smart?",
        "user_id": "client789",
        "expected_intent": "KNOWLEDGE_PRODUCT",
        "expected_agent": "knowledge_agent",
    },
    {
        "id": 3,
        "description": "Transaction rates question (EN)",
        "message": "What are the rates for debit and credit card transactions?",
        "user_id": "client789",
        "expected_intent": "KNOWLEDGE_PRODUCT",
        "expected_agent": "knowledge_agent",
    },
    {
        "id": 4,
        "description": "Tap-to-pay question (EN)",
        "message": "How can I use my phone as a card machine?",
        "user_id": "client789",
        "expected_intent": "KNOWLEDGE_PRODUCT",
        "expected_agent": "knowledge_agent",
    },
    {
        "id": 5,
        "description": "General knowledge question (PT-BR)",
        "message": "Quando foi o último jogo do Palmeiras?",
        "user_id": "client789",
        "expected_intent": "KNOWLEDGE_GENERAL",
        "expected_agent": "knowledge_agent",
    },
    {
        "id": 6,
        "description": "General news question (PT-BR)",
        "message": "Quais as principais notícias de São Paulo hoje?",
        "user_id": "client789",
        "expected_intent": "KNOWLEDGE_GENERAL",
        "expected_agent": "knowledge_agent",
    },
    {
        "id": 7,
        "description": "Transfer issue (EN)",
        "message": "Why I am not able to make transfers?",
        "user_id": "client789",
        "expected_intent": "CUSTOMER_SUPPORT",
        "expected_agent": "support_agent",
    },
    {
        "id": 8,
        "description": "Login issue (EN)",
        "message": "I can't sign in to my account.",
        "user_id": "client789",
        "expected_intent": "CUSTOMER_SUPPORT",
        "expected_agent": "support_agent",
    },
]

SEPARATOR = "=" * 70


def run_test(scenario: dict) -> dict:
    print(f"\n{SEPARATOR}")
    print(f"TEST {scenario['id']}: {scenario['description']}")
    print(f"  Message : {scenario['message']}")
    print(f"  User ID : {scenario['user_id']}")
    print(f"  Expected: intent={scenario['expected_intent']} | agent={scenario['expected_agent']}")

    start = time.time()
    state = process_message(scenario["message"], scenario["user_id"])
    elapsed = time.time() - start

    intent_ok = state["intent"] == scenario["expected_intent"]
    agent_ok = state["agent_used"] == scenario["expected_agent"]
    passed = intent_ok and agent_ok

    print(f"  Result  : intent={state['intent']} ({'✓' if intent_ok else '✗'}) | "
          f"agent={state['agent_used']} ({'✓' if agent_ok else '✗'})")
    print(f"  Language: {state['language']} | Elapsed: {elapsed:.2f}s")
    print(f"  Response: {state['response'][:200]}...")
    if state.get("ticket_id"):
        print(f"  Ticket  : {state['ticket_id']}")
    print(f"  STATUS  : {'PASS ✓' if passed else 'FAIL ✗'}")

    return {"id": scenario["id"], "passed": passed, "elapsed": elapsed}


def main():
    validate_config()
    print(f"\n{SEPARATOR}")
    print("InfinitePay Agent Swarm — Integration Test Suite")
    print(f"{SEPARATOR}")
    print(f"Running {len(TEST_SCENARIOS)} test scenarios...\n")

    results = []
    for scenario in TEST_SCENARIOS:
        result = run_test(scenario)
        results.append(result)

    passed = sum(1 for r in results if r["passed"])
    total = len(results)
    total_time = sum(r["elapsed"] for r in results)

    print(f"\n{SEPARATOR}")
    print(f"RESULTS: {passed}/{total} tests passed | Total time: {total_time:.2f}s")
    print(SEPARATOR)

    if passed < total:
        sys.exit(1)


if __name__ == "__main__":
    main()
