from pydantic import BaseModel


class ColumnMetadataResponse(BaseModel):
    name: str
    data_type: str
    nullable: bool


class RelationshipMetadataResponse(BaseModel):
    table: str
    column: str
    references_table: str
    references_column: str


class TableMetadataResponse(BaseModel):
    name: str
    description: str
    columns: list[ColumnMetadataResponse]
    relationships: list[RelationshipMetadataResponse]


class SchemaResponse(BaseModel):
    tables: list[TableMetadataResponse]


class TableListResponse(BaseModel):
    tables: list[str]
