import assert from 'node:assert/strict';
import test from 'node:test';

import {
  SettingsContractError,
  createProviderSettingsRequest,
  parseLLMSettingsResponse,
  parseProviderSettings,
} from '../src/api/settingsContract.ts';

test('parses the supported provider settings response', () => {
  const response = parseLLMSettingsResponse({
    providers: [
      {
        provider: 'ollama',
        display_name: '本地模型（Ollama）',
        configured: false,
        is_default: false,
        key_hint: null,
        model: '',
        base_url: 'http://host.docker.internal:11434',
        models: [],
        updated_at: null,
      },
      {
        provider: 'deepseek',
        display_name: 'DeepSeek',
        configured: true,
        is_default: true,
        key_hint: 'sk-****9x2a',
        model: 'deepseek-v4-flash',
        models: ['deepseek-v4-flash', 'deepseek-v4-pro'],
        updated_at: '2026-07-29T08:00:00Z',
      },
      {
        provider: 'gemini',
        display_name: 'Google Gemini',
        configured: false,
        is_default: false,
        key_hint: null,
        model: 'gemini-3.6-flash',
        models: [
          'gemini-3.6-flash',
          'gemini-3.5-flash',
          'gemini-3.5-flash-lite',
          'gemini-3.1-flash-lite',
        ],
        updated_at: null,
      },
      {
        provider: 'openai',
        display_name: 'OpenAI / ChatGPT',
        configured: false,
        is_default: false,
        key_hint: null,
        model: 'gpt-5.5',
        models: ['gpt-5.5', 'gpt-5.4', 'gpt-5.4-mini', 'gpt-5.4-nano'],
        updated_at: null,
      },
      {
        provider: 'anthropic',
        display_name: 'Anthropic Claude',
        configured: false,
        is_default: false,
        key_hint: null,
        model: 'claude-fable-5',
        models: [
          'claude-fable-5',
          'claude-opus-4-8',
          'claude-sonnet-5',
          'claude-haiku-4-5-20251001',
        ],
        updated_at: null,
      },
      {
        provider: 'doubao',
        display_name: '豆包（火山方舟）',
        configured: false,
        is_default: false,
        key_hint: null,
        model: 'doubao-seed-2-0-pro-260215',
        models: [
          'doubao-seed-2-0-pro-260215',
          'doubao-seed-2-0-lite-260215',
          'doubao-seed-2-0-mini-260215',
        ],
        updated_at: null,
      },
    ],
    default_provider: 'deepseek',
  });

  assert.equal(response.providers.length, 6);
  assert.equal(response.providers[1].provider, 'deepseek');
  assert.deepEqual(response.providers[1].models, [
    'deepseek-v4-flash',
    'deepseek-v4-pro',
  ]);
  assert.equal(response.providers[2].configured, false);
  assert.equal(response.default_provider, 'deepseek');
});

test('drops unexpected secret fields from a provider response', () => {
  const provider = parseProviderSettings({
    provider: 'deepseek',
    display_name: 'DeepSeek',
    configured: true,
    is_default: true,
    key_hint: 'last-four',
    model: 'deepseek-v4-flash',
    models: ['deepseek-v4-flash'],
    updated_at: null,
    api_key: 'must-not-reach-the-ui-model',
  });

  assert.equal('api_key' in provider, false);
});

test('creates the exact provider update request without empty model values', () => {
  assert.deepEqual(
    createProviderSettingsRequest('  secret-key  ', '  deepseek-v4-flash  '),
    {
      api_key: 'secret-key',
      model: 'deepseek-v4-flash',
    },
  );
  assert.deepEqual(
    createProviderSettingsRequest('secret-key', '   '),
    { api_key: 'secret-key' },
  );
  assert.deepEqual(
    createProviderSettingsRequest('', 'deepseek-v4-pro'),
    { model: 'deepseek-v4-pro' },
  );
  assert.deepEqual(
    createProviderSettingsRequest('', 'qwen3.8:latest', 'http://host.docker.internal:11434'),
    { model: 'qwen3.8:latest', base_url: 'http://host.docker.internal:11434' },
  );
});

test('rejects unsupported providers and invalid API keys', () => {
  assert.throws(
    () => parseProviderSettings({
      provider: 'unsupported',
      display_name: 'Unsupported',
      configured: false,
      is_default: false,
      key_hint: null,
      model: '',
      models: [],
      updated_at: null,
    }),
    SettingsContractError,
  );
  assert.throws(
    () => createProviderSettingsRequest('   ', ''),
    SettingsContractError,
  );
  assert.throws(
    () => createProviderSettingsRequest('short', 'deepseek-v4-flash'),
    SettingsContractError,
  );
});
