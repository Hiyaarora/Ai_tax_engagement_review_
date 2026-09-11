// Mirrors backend Pydantic models in backend/app/api/health.py.
// Keep in sync by hand for now; may switch to openapi-typescript generation later.

export interface AzureConfigState {
  foundry: boolean
  search: boolean
  document_intelligence: boolean
}

export interface HealthResponse {
  status: string
  service: string
  version: string
  environment: string
  azure: AzureConfigState
}
