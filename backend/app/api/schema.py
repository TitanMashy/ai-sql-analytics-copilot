from fastapi import APIRouter, HTTPException, status

from app.db.schema_metadata import TableMetadata, get_schema_metadata
from app.schemas.schema import (
    ColumnMetadataResponse,
    RelationshipMetadataResponse,
    SchemaResponse,
    TableListResponse,
    TableMetadataResponse,
)

router = APIRouter(prefix="/schema", tags=["schema"])


def _to_response(table: TableMetadata) -> TableMetadataResponse:
    return TableMetadataResponse(
        name=table.name,
        description=table.description,
        columns=[ColumnMetadataResponse(**column.__dict__) for column in table.columns],
        relationships=[
            RelationshipMetadataResponse(**relationship.__dict__)
            for relationship in table.relationships
        ],
    )


@router.get(
    "",
    response_model=SchemaResponse,
    summary="Get analytics schema metadata",
    description=(
        "Return table, column, type, and relationship metadata without credentials or "
        "infrastructure details."
    ),
)
def get_schema() -> SchemaResponse:
    return SchemaResponse(tables=[_to_response(table) for table in get_schema_metadata()])


@router.get(
    "/tables",
    response_model=TableListResponse,
    summary="List analytics tables",
    description="Return the names of tables available to the analytics query layer.",
)
def list_tables() -> TableListResponse:
    return TableListResponse(tables=[table.name for table in get_schema_metadata()])


@router.get(
    "/tables/{table_name}",
    response_model=TableMetadataResponse,
    summary="Get one table's metadata",
    description="Return columns and relationships for one known analytics table.",
    responses={404: {"description": "Table metadata not found"}},
)
def get_table(table_name: str) -> TableMetadataResponse:
    table = next((item for item in get_schema_metadata() if item.name == table_name), None)
    if table is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Table not found")
    return _to_response(table)
