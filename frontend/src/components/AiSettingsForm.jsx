import { useEffect, useMemo, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useToast } from './Toast'
import Icon from './Icons'
import { formatContextWindow } from '../utils'

const CONTEXT_CHOICES = [
  { value: 131072, label: '128K' },
  { value: 262144, label: '256K' },
  { value: 1048576, label: '1M' },
  { value: 2000000, label: '2M' },
]

const FALLBACK_PROVIDERS = [
  {
    id: 'deepseek',
    label: 'DeepSeek',
    base_url: 'https://api.deepseek.com',
    key_placeholder: 'sk-...',
    description: 'DeepSeek 官方 API',
    models: [
      'deepseek-flash',
      'deepseek-v4-pro',
      'deepseek-v4-flash',
      'deepseek-v4-flash-vision-exp',
      'deepseek-chat',
      'deepseek-reasoner',
    ],
  },
  {
    id: 'moonshot',
    label: '月之暗面 Kimi',
    base_url: 'https://api.moonshot.cn/v1',
    key_placeholder: 'sk-...',
    description: 'Moonshot Kimi API',
    models: ['kimi-k2.6', 'kimi-k2.7-code', 'kimi-k2.7-code-highspeed', 'kimi-k3', 'kimi-k3.1-pro'],
  },
]

const FALLBACK_MODELS = [
  { id: 'deepseek-flash', label: 'DeepSeek V4.1 Flash', provider: 'deepseek', context_window: 1048576, max_output_tokens: 393216, reasoning: true },
  { id: 'deepseek-v4-pro', label: 'DeepSeek V4 Pro', provider: 'deepseek', context_window: 1048576, max_output_tokens: 393216, reasoning: true },
  { id: 'deepseek-v4-flash', label: 'DeepSeek V4 Flash（旧名）', provider: 'deepseek', context_window: 1048576, max_output_tokens: 393216, reasoning: true },
  { id: 'deepseek-v4-flash-vision-exp', label: 'DeepSeek V4 Flash Vision（旧名）', provider: 'deepseek', context_window: 1048576, max_output_tokens: 393216, reasoning: true },
  { id: 'deepseek-chat', label: 'DeepSeek V3.1 Chat', provider: 'deepseek', context_window: 131072, max_output_tokens: 8192, reasoning: false },
  { id: 'deepseek-reasoner', label: 'DeepSeek V3.1 Reasoner', provider: 'deepseek', context_window: 131072, max_output_tokens: 65536, reasoning: true },
  { id: 'kimi-k2.6', label: 'Kimi K2.6', provider: 'moonshot', context_window: 262144, max_output_tokens: 262144, reasoning: true },
  { id: 'kimi-k2.7-code', label: 'Kimi K2.7 Code', provider: 'moonshot', context_window: 262144, max_output_tokens: 262144, reasoning: true },
  { id: 'kimi-k2.7-code-highspeed', label: 'Kimi K2.7 Code HighSpeed', provider: 'moonshot', context_window: 262144, max_output_tokens: 262144, reasoning: true },
  { id: 'kimi-k3', label: 'Kimi K3', provider: 'moonshot', context_window: 1048576, max_output_tokens: 1048576, reasoning: true },
  { id: 'kimi-k3.1-pro', label: 'Kimi K3.1 Pro', provider: 'moonshot', context_window: 1000000, max_output_tokens: 128000, reasoning: true },
]

const emptyProviderKeys = () =>
  Object.fromEntries(
    FALLBACK_PROVIDERS.map((provider) => [
      provider.id,
      { api_key: '', base_url: provider.base_url, fallback: true },
    ])
  )

export default function AiSettingsForm({ onSaved, compact = false }) {
  const toast = useToast()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [config, setConfig] = useState(null)
  const [providers, setProviders] = useState(FALLBACK_PROVIDERS)
  const [presets, setPresets] = useState(FALLBACK_MODELS)
  const [form, setForm] = useState({
    model_chat: 'deepseek-flash',
    model_reasoner: 'deepseek-v4-pro',
    context_window: 1048576,
    max_output_tokens: 393216,
    temperature: 1,
    provider_keys: emptyProviderKeys(),
  })

  const modelMap = useMemo(() => new Map(presets.map((item) => [item.id, item])), [presets])
  const maxContext = config?.max_context_window || 2000000

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const response = await api.get('/settings/ai')
        if (cancelled) return
        const data = response.data
        setConfig(data)
        const nextProviders = data.providers?.length ? data.providers : FALLBACK_PROVIDERS
        const nextPresets = data.presets?.length ? data.presets : FALLBACK_MODELS
        setProviders(nextProviders)
        setPresets(nextPresets)
        const keys = {}
        for (const provider of nextProviders) {
          const status = data.provider_status?.[provider.id] || {}
          keys[provider.id] = {
            api_key: '',
            base_url: status.base_url || provider.base_url,
            hint: status.hint || '',
            configured: Boolean(status.configured),
          }
        }
        setForm((current) => ({
          ...current,
          model_chat: data.model_chat || current.model_chat,
          model_reasoner: data.model_reasoner || current.model_reasoner,
          context_window: data.context_window || current.context_window,
          max_output_tokens: data.max_output_tokens || current.max_output_tokens,
          temperature: data.temperature ?? current.temperature,
          provider_keys: keys,
        }))
      } catch (error) {
        if (!cancelled) toast(errorMessage(error, '读取模型配置失败'), 'error')
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    load()
    return () => {
      cancelled = true
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const update = (key, value) => setForm((current) => ({ ...current, [key]: value }))
  const updateProvider = (providerId, key, value) =>
    setForm((current) => ({
      ...current,
      provider_keys: {
        ...current.provider_keys,
        [providerId]: { ...(current.provider_keys?.[providerId] || {}), [key]: value },
      },
    }))

  function selectModel(field, modelId) {
    const preset = modelMap.get(modelId)
    setForm((current) => ({
      ...current,
      [field]: modelId,
      ...(preset
        ? {
            context_window: preset.context_window,
            max_output_tokens: preset.max_output_tokens,
          }
        : {}),
    }))
  }

  function payload(clearProvider = null) {
    const keys = {}
    for (const provider of providers) {
      const item = form.provider_keys?.[provider.id] || {}
      keys[provider.id] = {
        base_url: item.base_url || provider.base_url,
        ...(item.api_key?.trim() ? { api_key: item.api_key.trim() } : {}),
        ...(clearProvider === provider.id ? { clear_key: true } : {}),
      }
    }
    return {
      model_chat: form.model_chat,
      model_reasoner: form.model_reasoner,
      context_window: Number(form.context_window),
      max_output_tokens: Number(form.max_output_tokens),
      temperature: Number(form.temperature),
      provider_keys: keys,
    }
  }

  async function save(clearProvider = null) {
    setSaving(true)
    try {
      const response = await api.put('/settings/ai', payload(clearProvider))
      const data = response.data
      setConfig(data)
      setForm((current) => {
        const keys = { ...current.provider_keys }
        for (const provider of providers) {
          const status = data.provider_status?.[provider.id] || {}
          keys[provider.id] = {
            ...(keys[provider.id] || {}),
            api_key: '',
            hint: status.hint || '',
            configured: Boolean(status.configured),
            base_url: status.base_url || provider.base_url,
          }
        }
        return { ...current, provider_keys: keys }
      })
      onSaved?.(data)
      toast(clearProvider ? '已移除该 Provider 的 Key' : '模型接入已保存', 'success')
    } catch (error) {
      toast(errorMessage(error, '保存失败'), 'error')
    } finally {
      setSaving(false)
    }
  }

  async function test() {
    setTesting(true)
    try {
      const response = await api.post('/settings/ai/test', payload())
      toast(
        `连接正常 · ${response.data.latency_ms}ms · ${response.data.model}（${response.data.provider}）`,
        'success'
      )
    } catch (error) {
      toast(errorMessage(error, '连接失败'), 'error')
    } finally {
      setTesting(false)
    }
  }

  const modelOptions = (selected) => {
    const groups = providers.map((provider) => ({
      provider,
      models: presets.filter((item) => item.provider === provider.id),
    }))
    if (!groups.some((group) => group.models.some((model) => model.id === selected))) {
      groups[0]?.models.push({ id: selected, label: `${selected}（自定义）`, context_window: 0, max_output_tokens: 0 })
    }
    return groups
  }

  if (loading) {
    return (
      <div className="settings-loading">
        <span className="spinner" /> 读取接入配置…
      </div>
    )
  }

  const chatPreset = modelMap.get(form.model_chat)
  const reasonerPreset = modelMap.get(form.model_reasoner)
  const chatReady = Boolean(config?.chat_ready)
  const reasonerReady = Boolean(config?.reasoner_ready)

  return (
    <div className={`ai-form ${compact ? 'ai-form-compact' : ''}`}>
      <div className={`ai-status ${chatReady ? 'ok' : 'warn'}`}>
        <span className="ai-status-icon">
          <Icon name={chatReady ? 'check' : 'key'} size={17} />
        </span>
        <div>
          <strong>{chatReady ? '日常模型已接入' : '日常模型还缺 API Key'}</strong>
          <p>
            日常：{chatPreset?.label || form.model_chat} · 推理：{reasonerPreset?.label || form.model_reasoner}
            {' · '}
            {chatReady ? '可以开始对话' : '填写下方对应 Provider 的 Key'}
            {!reasonerReady ? ' · 推理模型尚未配置 Key' : ''}
          </p>
        </div>
      </div>

      <div className="provider-grid">
        {providers.map((provider) => {
          const item = form.provider_keys?.[provider.id] || {}
          const status = config?.provider_status?.[provider.id] || {}
          return (
            <section className={`provider-card ${status.configured ? 'is-ready' : ''}`} key={provider.id}>
              <div className="provider-card-head">
                <div>
                  <h4>{provider.label}</h4>
                  <span>{provider.description || provider.base_url}</span>
                </div>
                <span className={`status-pill ${status.configured ? 'ok' : 'off'}`}>
                  {status.configured ? `已接入 ${status.hint || ''}` : '未接入'}
                </span>
              </div>
              <label className="field">
                <span>API Key</span>
                <div className="input-wrap">
                  <Icon name="key" size={16} />
                  <input
                    type="password"
                    value={item.api_key || ''}
                    onChange={(event) => updateProvider(provider.id, 'api_key', event.target.value)}
                    placeholder={status.configured ? `已保存 ${status.hint || '••••'}，留空不修改` : provider.key_placeholder}
                    autoComplete="off"
                    spellCheck="false"
                  />
                </div>
              </label>
              <label className="field">
                <span>接口地址</span>
                <div className="input-wrap">
                  <Icon name="globe" size={16} />
                  <input
                    value={item.base_url || provider.base_url}
                    onChange={(event) => updateProvider(provider.id, 'base_url', event.target.value)}
                    spellCheck="false"
                  />
                </div>
              </label>
              {status.configured ? (
                <button
                  className="btn btn-sm btn-danger-ghost provider-clear"
                  onClick={() => save(provider.id)}
                  disabled={saving}
                >
                  移除 {provider.label} Key
                </button>
              ) : null}
            </section>
          )
        })}
      </div>

      <div className="ai-form-grid">
        <label className="field">
          <span>日常模型</span>
          <div className="input-wrap">
            <Icon name="zap" size={16} />
            <select value={form.model_chat} onChange={(event) => selectModel('model_chat', event.target.value)}>
              {modelOptions(form.model_chat).map((group) => (
                <optgroup key={group.provider.id} label={group.provider.label}>
                  {group.models.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label} · {formatContextWindow(item.context_window)}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
        </label>

        <label className="field">
          <span>推理模型</span>
          <div className="input-wrap">
            <Icon name="brain" size={16} />
            <select
              value={form.model_reasoner}
              onChange={(event) => selectModel('model_reasoner', event.target.value)}
            >
              {modelOptions(form.model_reasoner).map((group) => (
                <optgroup key={group.provider.id} label={group.provider.label}>
                  {group.models.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.label} · {formatContextWindow(item.context_window)}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
        </label>

        <div className="field field-span-2">
          <span>上下文窗口</span>
          <div className="context-choice-row">
            {CONTEXT_CHOICES.map((item) => (
              <button
                type="button"
                key={item.value}
                className={`context-choice ${Number(form.context_window) === item.value ? 'active' : ''}`}
                onClick={() => update('context_window', item.value)}
              >
                {item.label}
              </button>
            ))}
            <div className="context-custom">
              <input
                type="number"
                value={form.context_window}
                min={4096}
                max={maxContext}
                onChange={(event) => update('context_window', event.target.value)}
              />
              <span>tokens</span>
            </div>
          </div>
          <small className="field-hint">
            DeepSeek V4 / Kimi K3 官方窗口 1M；DeepSeek V3.1 为 128K。历史按 token 预算保留，不截断当前问题。
          </small>
        </div>

        <label className="field">
          <span>单次输出上限</span>
          <div className="input-wrap">
            <Icon name="sliders" size={16} />
            <input
              type="number"
              value={form.max_output_tokens}
              min={256}
              max={1048576}
              step={256}
              onChange={(event) => update('max_output_tokens', event.target.value)}
            />
            <span className="input-suffix">tokens</span>
          </div>
          <small className="field-hint">V4 官方输出上限 384K；实际仍受模型能力限制。</small>
        </label>

        <label className="field">
          <span>温度</span>
          <div className="input-wrap">
            <Icon name="sliders" size={16} />
            <input
              type="number"
              value={form.temperature}
              min={0}
              max={2}
              step={0.1}
              onChange={(event) => update('temperature', event.target.value)}
            />
          </div>
          <small className="field-hint">推理模型可能忽略采样参数。</small>
        </label>
      </div>

      <div className="ai-form-actions">
        <button className="btn btn-primary" onClick={() => save()} disabled={saving || testing}>
          {saving ? <span className="spinner spinner-sm" /> : <Icon name="check" size={16} />}
          保存接入
        </button>
        <button
          className="btn btn-ghost"
          onClick={test}
          disabled={saving || testing}
        >
          {testing ? <span className="spinner spinner-sm" /> : <Icon name="refresh" size={16} />}
          测试连接
        </button>
      </div>

      <p className="ai-privacy">
        <Icon name="lock" size={13} />
        DeepSeek 与 Kimi 的 Key 分别加密存储；接口只返回末四位。更换 SECRET_KEY 会导致旧 Key 需要重新填写。
      </p>
    </div>
  )
}
