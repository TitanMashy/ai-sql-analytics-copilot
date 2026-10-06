import { describe, expect, it } from "vitest";

import contract from "@/contracts/api-contract.json";
import { buildMockAskResponse } from "@/lib/mock-data";
import type {
  AskResponse,
  BusinessDefinition,
  BusinessDefinitionsResponse,
  ConversationResponse,
  ConversationTurn,
  FeedbackRequest,
  KPIResponse,
  VisualizationAxisResponse,
  VisualizationResponse,
} from "@/types/api";

/**
 * `Record<keyof T, true>` makes the compiler demand an entry for every field of the interface, so
 * adding or removing a field in `types/api.ts` is a type error until this list (and therefore the
 * contract shared with the backend) is updated. The backend has the matching check in
 * `backend/tests/test_api_contract.py`.
 */
const askResponseFields: Record<keyof AskResponse, true> = {
  question: true,
  sql: true,
  explanation: true,
  tables_used: true,
  schema_context: true,
  provider: true,
  confidence: true,
  request_id: true,
  columns: true,
  rows: true,
  row_count: true,
  execution_time_ms: true,
  truncated: true,
  summary: true,
  kpi: true,
  visualization: true,
  warnings: true,
};
const visualizationFields: Record<keyof VisualizationResponse, true> = {
  type: true,
  title: true,
  x_axis: true,
  y_axis: true,
  series: true,
};
const axisFields: Record<keyof VisualizationAxisResponse, true> = { field: true, format: true };
const kpiFields: Record<keyof KPIResponse, true> = { label: true, value: true, format: true };
const conversationFields: Record<keyof ConversationResponse, true> = {
  conversation_id: true,
  turns: true,
  context: true,
};
const turnFields: Record<keyof ConversationTurn, true> = {
  conversation_id: true,
  role: true,
  content: true,
};
const definitionsFields: Record<keyof BusinessDefinitionsResponse, true> = {
  definitions: true,
  examples: true,
};
const definitionFields: Record<keyof BusinessDefinition, true> = { name: true, definition: true };
const feedbackFields: Record<keyof FeedbackRequest, true> = {
  request_id: true,
  helpful: true,
  conversation_id: true,
};

function sorted(values: string[]) {
  return [...values].sort();
}

describe("API contract shared with the backend", () => {
  it.each([
    ["AskResponse", askResponseFields],
    ["VisualizationResponse", visualizationFields],
    ["VisualizationAxisResponse", axisFields],
    ["KPIResponse", kpiFields],
    ["ConversationResponse", conversationFields],
    ["ConversationTurnResponse", turnFields],
    ["BusinessDefinitionsResponse", definitionsFields],
    ["BusinessDefinitionResponse", definitionFields],
    ["FeedbackRequest", feedbackFields],
  ] as const)("%s has the fields the backend serves", (name, fields) => {
    const expected = (contract as Record<string, string[]>)[name];

    expect(sorted(Object.keys(fields))).toEqual(sorted(expected));
  });

  it("the mock response carries every required AskResponse field", () => {
    const mock = buildMockAskResponse("How many active vehicles do we have?");
    const optional = new Set(["series", "confidence", "summary", "kpi", "visualization"]);
    const required = (contract as Record<string, string[]>).AskResponse.filter(
      (field) => !optional.has(field),
    );

    for (const field of required) {
      expect(mock).toHaveProperty(field);
    }
  });
});
