"""The backend response models must match the contract file the frontend is built against.

``frontend/contracts/api-contract.json`` lists the fields of every response the dashboard reads.
The frontend test ``types/contract.test.ts`` checks its TypeScript types against the same file, so a
change to a response model on either side fails CI until the contract and both sides agree.
"""

import json
from pathlib import Path

import pytest

from app.schemas.analytics import ErrorBody
from app.schemas.conversation import ConversationResponse, ConversationTurnResponse
from app.schemas.feedback import (
    BusinessDefinitionResponse,
    BusinessDefinitionsResponse,
    FeedbackRequest,
)
from app.schemas.generation import (
    AskResponse,
    KPIResponse,
    VisualizationAxisResponse,
    VisualizationResponse,
)

CONTRACT_PATH = Path(__file__).resolve().parents[2] / "frontend" / "contracts" / "api-contract.json"

MODELS = {
    "AskResponse": AskResponse,
    "VisualizationResponse": VisualizationResponse,
    "VisualizationAxisResponse": VisualizationAxisResponse,
    "KPIResponse": KPIResponse,
    "ConversationResponse": ConversationResponse,
    "ConversationTurnResponse": ConversationTurnResponse,
    "BusinessDefinitionsResponse": BusinessDefinitionsResponse,
    "BusinessDefinitionResponse": BusinessDefinitionResponse,
    "FeedbackRequest": FeedbackRequest,
    "ErrorBody": ErrorBody,
}


@pytest.fixture(scope="module")
def contract() -> dict:
    return json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))


def test_the_contract_covers_exactly_the_models_checked_here(contract: dict) -> None:
    assert set(contract) - {"$comment"} == set(MODELS)


@pytest.mark.parametrize("name", sorted(MODELS))
def test_model_fields_match_the_contract(name: str, contract: dict) -> None:
    fields = set(MODELS[name].model_fields)

    assert fields == set(contract[name]), (
        f"{name} changed. Update frontend/contracts/api-contract.json and the TypeScript types in "
        f"frontend/types/api.ts together. Backend only: {sorted(fields - set(contract[name]))}; "
        f"contract only: {sorted(set(contract[name]) - fields)}"
    )


def test_the_openapi_document_exposes_the_ask_contract() -> None:
    from app.main import app

    schema = app.openapi()["components"]["schemas"]["AskResponse"]

    assert set(schema["properties"]) == set(json.loads(CONTRACT_PATH.read_text())["AskResponse"])
