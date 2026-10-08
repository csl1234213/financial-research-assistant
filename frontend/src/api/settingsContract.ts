import type {
  LLMProvider,
  LLMSettingsResponse,
  ProviderSettings,
  UpdateProviderSettingsRequest,
} from '../types/settings';

export class SettingsContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'SettingsContractError';
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function requireString(
  record: Record<string, unknown>,
  field: string,
): string {
  const value = record[field];
  if (typeof value !== 'string') {
    throw new SettingsContractError(`${field} must be a string.`);
  }
  return value;
}

function requireNullableString(
  record: Record<string, unknown>,
  field: string,
): string | null {
  const value = record[field];
  if (value !== null && typeof value !== 'string') {
    throw new SettingsContractError(`${field} must be a string or null.`);
  }
  return value;
}

function requireProvider(value: unknown): LLMProvider {
  if (
    value !== 'deepseek'
    && value !== 'gemini'
    && value !== 'openai'
    && value !== 'anthropic'
    && value !== 'doubao'
    && value !== 'ollama'
  ) {
    throw new SettingsContractError('provider is not supported.');
  }
  return value;
}

function requireStringArray(
  record: Record<string, unknown>,
  field: string,
): string[] {
  const value = record[field];
  if (!Array.isArray(value) || value.some((item) => typeof item !== 'string')) {
    throw new SettingsContractError(`${field} must be an array of strings.`);
  }
  return value;
}

export function parseProviderSettings(value: unknown): ProviderSettings {
  if (!isRecord(value)) {
    throw new SettingsContractError('Provider settings must be an object.');
  }

  if (typeof value.configured !== 'boolean') {
    throw new SettingsContractError('configured must be a boolean.');
  }
  if (typeof value.is_default !== 'boolean') {
    throw new SettingsContractError('is_default must be a boolean.');
  }

  return {
    provider: requireProvider(value.provider),
    display_name: requireString(value, 'display_name'),
    configured: value.configured,
    is_default: value.is_default,
    key_hint: requireNullableString(value, 'key_hint'),
    model: requireString(value, 'model'),
    base_url: value.base_url === undefined
      ? null
      : requireNullableString(value, 'base_url'),
    models: requireStringArray(value, 'models'),
    updated_at: requireNullableString(value, 'updated_at'),
  };
}

export function parseLLMSettingsResponse(value: unknown): LLMSettingsResponse {
  if (!isRecord(value) || !Array.isArray(value.providers)) {
    throw new SettingsContractError('providers must be an array.');
  }

  return {
    providers: value.providers.map(parseProviderSettings),
    default_provider: value.default_provider === null
      ? null
      : requireProvider(value.default_provider),
  };
}

export function createProviderSettingsRequest(
  apiKey: string,
  model: string,
  baseUrl?: string,
): UpdateProviderSettingsRequest {
  const normalizedKey = apiKey.trim();
  if (normalizedKey && normalizedKey.length < 8) {
    throw new SettingsContractError('api_key must be at least 8 characters.');
  }

  const normalizedModel = model.trim();
  const normalizedBaseUrl = baseUrl?.trim() ?? '';
  if (!normalizedKey && !normalizedModel && !normalizedBaseUrl) {
    throw new SettingsContractError('api_key, model, or base_url must be provided.');
  }
  return {
    ...(normalizedKey ? { api_key: normalizedKey } : {}),
    ...(normalizedModel ? { model: normalizedModel } : {}),
    ...(normalizedBaseUrl ? { base_url: normalizedBaseUrl } : {}),
  };
}
