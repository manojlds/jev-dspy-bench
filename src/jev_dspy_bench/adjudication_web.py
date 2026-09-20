from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field

from .adjudication import AdjudicationStore, ComparisonAnnotation, ReferenceAnnotation


class ReferenceRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    annotator: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.@-]+$")
    actor_type: str = Field(pattern=r"^(human|agent)$")
    submit: bool = False
    reference: ReferenceAnnotation


class ComparisonRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    annotator: str = Field(min_length=1, max_length=80, pattern=r"^[a-zA-Z0-9_.@-]+$")
    submit: bool = False
    comparison: ComparisonAnnotation


def create_app(database: Path) -> FastAPI:
    store = AdjudicationStore(database)
    app = FastAPI(title="Jev / DSPy Adjudication", docs_url=None, redoc_url=None)
    index = Path(__file__).with_name("adjudication_ui") / "index.html"

    @app.get("/", include_in_schema=False)
    def home() -> FileResponse:
        return FileResponse(index)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/studies")
    def studies() -> list[dict[str, object]]:
        return store.list_studies()

    @app.get("/api/studies/{study_id}/cases")
    def cases(study_id: str, annotator: str = Query(min_length=1)) -> list[dict[str, object]]:
        return store.list_cases(study_id, annotator)

    @app.get("/api/studies/{study_id}/cases/{case_id}")
    def case(
        study_id: str, case_id: str, annotator: str = Query(min_length=1)
    ) -> dict[str, object]:
        result = store.get_case(study_id, case_id, annotator)
        if not result:
            raise HTTPException(404, "case not found")
        return result

    @app.put("/api/studies/{study_id}/cases/{case_id}/reference")
    def reference(study_id: str, case_id: str, request: ReferenceRequest) -> dict[str, str]:
        try:
            status = store.save_reference(
                study_id,
                case_id,
                request.annotator,
                request.actor_type,
                request.reference,
                request.submit,
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"status": status}

    @app.put("/api/studies/{study_id}/cases/{case_id}/comparison")
    def comparison(study_id: str, case_id: str, request: ComparisonRequest) -> dict[str, str]:
        try:
            status = store.save_comparison(
                study_id, case_id, request.annotator, request.comparison, request.submit
            )
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {"status": status}

    return app
