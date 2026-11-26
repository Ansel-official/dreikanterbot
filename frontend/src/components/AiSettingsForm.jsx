import { useEffect, useMemo, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useToast } from './Toast'
import Icon from './Icons'

const CONTEXT_CHOICES = [
  { value: 32768, label: '32K' },
  { value: 128000, label: '128K' },
  { value: 262144, label: '256K' },
  { value: 1000000, label: '1M' },
  { value: 2000000, label: '2M' },
]

function NumberField({ label, hint, value, onChange, min, max, step = 1, suffix }) {
  return (
    <label className="field">
      <span>{label}</span>
      <div className="input-wrap">
        <Icon name="sliders" size={16} />
        <input
          type="number"
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(event) => onChange(event.target.value)}
        />
        {suffix ? <span className="input-suffix">{suffix}</span> : null}
      </div>
      {hint ? <small className="field-hint">{hint}</small> : null}
    </label>
  )
}

export default function AiSettingsForm({ onSaved, compact = false }) {
  const toast = useToast()
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [testing, setTesting] = useState(false)
  const [config, setConfig] = useState(null)
  const [form, setForm] = useState({
    api_key: '',
    base_url: 'https://api.deepseek.com',
    model_chat: 'deepseek-chat',
    model_reasoner: 'deepseek-reasoner',
    context_window: 128000,
    max_output_tokens: 8192,
    temperature: 1,
  })

  const presets = config?.presets || []
  const maxContext = config?.max_context_window || 2000000

  const modelOptions = useMemo(() => {
    const items = presets.map((item) => ({ value: item.id, label: `${item.label} · ${Math.round(item.context_window / 1000)}K` }))
    if (!items.some((item) => item.value === form.model_chat)) {
      items.push({ value: form.model_chat, label: `${form.model_chat}（自定义）` })
    }
    return items
  }, [presets, form.model_chat])

  useEffect(() => {
    let cancelled = false
    async function load() {
      setLoading(true)
      try {
        const response = await api.get('/settings/ai')
        if (cancelled) return
        const data = response.data
        setConfig(data)
        setForm((current) => ({
          ...current,
          base_url: data.base_url || current.base_url,
          model_chat: data.model_chat || current.model_chat,
          model_reasoner: data.model_reasoner || current.model_reasoner,
          context_window: data.context_window || current.context_window,
          max_output_tokens: data.max_output_tokens || current.max_output_tokens,
          temperature: data.temperature ?? current.temperature,
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

  async function save(clearKey = false) {
    setSaving(true)
    try {
      const response = await api.put('/settings/ai', {
        ...form,
        context_window: Number(form.context_window),
        max_output_tokens: Number(form.max_output_tokens),
        temperature: Number(form.temperature),
        clear_key: clearKey,
        api_key: form.api_key.trim() || undefined,
      })
      setConfig(response.data)
      setForm((current) => ({ ...current, api_key: '' }))
      onSaved?.(response.data)
      toast(clearKey ? '已移除 API Key' : '模型接入已保存', 'success')
    } catch (error) {
      toast(errorMessage(error, '保存失败'), 'error')
    } finally {
      setSaving(false)
    }
  }

  async function test() {
    setTesting(true)
    try {
      const response = await api.post('/settings/ai/test', {
        ...form,
        api_key: form.api_key.trim() || undefined,
        context_window: Number(form.context_window),
        max_output_tokens: Number(form.max_output_tokens),
        temperature: Number(form.temperature),
      })
      toast(`连接正常 · ${response.data.latency_ms}ms · ${response.data.model}`, 'success')
    } catch (error) {
      toast(errorMessage(error, '连接失败'), 'error')
    } finally {
      setTesting(false)
    }
  }

  if (loading) {
    return (
      <div className="settings-loading">
        <span className="spinner" /> 读取接入配置…
      </div>
    )
  }

  const configured = config?.configured

  return (
    <div className={`ai-form ${compact ? 'ai-form-compact' : ''}`}>
      <div className={`ai-status ${configured ? 'ok' : 'warn'}`}>
        <span className="ai-status-icon">
          <Icon name={configured ? 'check' : 'key'} size={17} />
        </span>
        <div>
          <strong>{configured ? '模型已接入' : '还没有可用的 API Key'}</strong>
          <p>
            {configured
              ? `当前使用${config.source === 'server' ? '服务端兜底 Key' : '你自己的 Key'} ${config.key_hint || ''} · ${Math.round((config.context_window || 0) / 1000)}K 上下文`
              : 'V3.0 起对话必须使用自己的模型 Key；密钥加密保存在服务端，接口只返回末四位。'}
          </p>
        </div>
      </div>

      <div className="ai-form-grid">
        <label className="field field-span-2">
          <span>API Key</span>
          <div className="input-wrap">
            <Icon name="key" size={16} />
            <input
              type="password"
              value={form.api_key}
              onChange={(event) => update('api_key', event.target.value)}
              placeholder={configured ? `已保存 ${config.key_hint || '••••'}，留空表示不修改` : 'sk-...'}
              autoComplete="off"
              spellCheck="false"
            />
          </div>
          <small className="field-hint">
            支持 DeepSeek 官方 Key 或兼容 OpenAI 协议的网关 Key。保存后只显示末四位。
          </small>
        </label>

        <label className="field field-span-2">
          <span>接口地址</span>
          <div className="input-wrap">
            <Icon name="globe" size={16} />
            <input
              value={form.base_url}
              onChange={(event) => update('base_url', event.target.value)}
              placeholder="https://api.deepseek.com"
              spellCheck="false"
            />
          </div>
          <small className="field-hint">官方地址不变；第三方网关通常以 /v1 结尾。</small>
        </label>

        <label className="field">
          <span>日常模型</span>
          <div className="input-wrap">
            <Icon name="zap" size={16} />
            <select value={form.model_chat} onChange={(event) => update('model_chat', event.target.value)}>
              {modelOptions.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
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
              onChange={(event) => update('model_reasoner', event.target.value)}
            >
              {modelOptions.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
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
            DeepSeek 官方模型上限 128K；自定义网关可拉到 {Math.round(maxContext / 1000)}K。历史消息按 token 预算自动保留，不会截断当前问题。
          </small>
        </div>

        <NumberField
          label="单次输出上限"
          hint="推理模型可设更高；实际仍受模型能力限制。"
          value={form.max_output_tokens}
          onChange={(value) => update('max_output_tokens', value)}
          min={256}
          max={131072}
          step={256}
          suffix="tokens"
        />
        <NumberField
          label="温度"
          hint="0 更稳定，1 更发散；推理模型会忽略此项。"
          value={form.temperature}
          onChange={(value) => update('temperature', value)}
          min={0}
          max={2}
          step={0.1}
        />
      </div>

      <div className="ai-form-actions">
        <button className="btn btn-primary" onClick={() => save(false)} disabled={saving || testing}>
          {saving ? <span className="spinner spinner-sm" /> : <Icon name="check" size={16} />}
          保存接入
        </button>
        <button className="btn btn-ghost" onClick={test} disabled={saving || testing || (!form.api_key.trim() && !configured)}>
          {testing ? <span className="spinner spinner-sm" /> : <Icon name="refresh" size={16} />}
          测试连接
        </button>
        {configured && config.source === 'user' ? (
          <button className="btn btn-danger-ghost" onClick={() => save(true)} disabled={saving}>
            移除 Key
          </button>
        ) : null}
      </div>

      <p className="ai-privacy">
        <Icon name="lock" size={13} />
        密钥使用服务端 SECRET_KEY 派生密钥加密存储；更换 SECRET_KEY 会导致旧 Key 需要重新填写。
      </p>
    </div>
  )
}
