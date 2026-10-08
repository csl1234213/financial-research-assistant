import { deleteJson, getJson, putJson } from './client';
import {
  createProviderSettingsRequest,
  parseLLMSettingsResponse,
  parseProviderSettings,
} from './settingsContract';
import type {
  LLMProvider,
  LLMSettingsResponse,
  ProviderSettings,
} from '../types/settings';

const llmSettingsEndpoint = '/v1/settings/llm';

function providerEndpoint(provider: LLMProvider): string {
  return `${llmSettingsEndpoint}/${provider}`;
}

export async function getLLMSettings(): Promise<LLMSettingsResponse> {
  const payload = await getJson(llmSettingsEndpoint);
  return parseLLMSettingsResponse(payload);
}

export async function updateLLMProvider(
  provider: LLMProvider,
  apiKey: string,
  model: string,
  baseUrl?: string,
): Promise<ProviderSettings> {
  const payload = await putJson(
    providerEndpoint(provider),
    createProviderSettingsRequest(apiKey, model, baseUrl),
  );
  return parseProviderSettings(payload);
}

export async function clearLLMProvider(
  provider: LLMProvider,
): Promise<ProviderSettings> {
  const payload = await deleteJson(providerEndpoint(provider));
  return parseProviderSettings(payload);
}

export async function setDefaultLLMProvider(
  provider: LLMProvider,
): Promise<LLMSettingsResponse> {
  const payload = await putJson(
    `${llmSettingsEndpoint}/default`,
    { provider },
  );
  return parseLLMSettingsResponse(payload);
}
