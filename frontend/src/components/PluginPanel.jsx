import { useCallback, useEffect, useRef, useState } from 'react'
import api, { errorMessage } from '../api/client'
import { useToast } from './Toast'
import Modal from './Modal'
import ConfirmDialog from './ConfirmDialog'
import Icon from './Icons'
import { formatRelativeTime } from '../utils'

export default function PluginPanel({ open, onClose, onChanged }) {
  const toast = useToast()
  const fileRef = useRef(null)
  const [plugins, setPlugins] = useState([])
  const [loading, setLoading] = useState(false)
  const [installing, setInstalling] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [expanded, setExpanded] = useState(null)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const response = await api.get('/plugins')
      setPlugins(response.data || [])
      onChanged?.(response.data || [])
    } catch (error) {
      toast(errorMessage(error, '读取插件失败'), 'error')
    } finally {
      setLoading(false)
    }
  }, [onChanged, toast])

  useEffect(() => {
    if (open) load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  async function install(file) {
    if (!file) return
    if (!file.name.toLowerCase().endsWith('.zip')) {
      toast('插件必须打包成 ZIP', 'error')
      return
    }
    setInstalling(true)
    const form = new FormData()
    form.append('file', file)
    try {
      const response = await api.post('/plugins/install', form, { timeout: 120000 })
      toast(`已安装「${response.data.name}」`, 'success')
      await load()
    } catch (error) {
      toast(errorMessage(error, '安装失败'), 'error')
    } finally {
      setInstalling(false)
    }
  }

  async function toggle(plugin) {
    try {
      const response = await api.patch(`/plugins/${plugin.id}`, { enabled: !plugin.enabled })
      setPlugins((current) => current.map((item) => (item.id === plugin.id ? { ...item, ...response.data } : item)))
      toast(response.data.enabled ? '已启用' : '已停用', 'success')
    } catch (error) {
      toast(errorMessage(error, '操作失败'), 'error')
    }
  }

  async function remove() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await api.delete(`/plugins/${deleteTarget.id}`)
      setPlugins((current) => current.filter((item) => item.id !== deleteTarget.id))
      setDeleteTarget(null)
      toast('插件已卸载', 'success')
    } catch (error) {
      toast(errorMessage(error, '卸载失败'), 'error')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title="插件"
        subtitle="提示词包与工作流模板：上传、启停、删除；不执行第三方代码"
        size="xl"
      >
        <div className="plugin-intro">
          <div>
            <span className="eyebrow">DECLARATIVE PACKS</span>
            <h3>把常用工作流装进来</h3>
            <p>
              插件是一个 ZIP：<code>plugin.json</code> 描述名称与提示词模板，可附带
              <code>README.md</code>。它不会获得服务器执行权限，也不会读取你的对话。
            </p>
          </div>
          <input
            ref={fileRef}
            type="file"
            accept=".zip,application/zip"
            hidden
            onChange={(event) => {
              install(event.target.files?.[0])
              event.target.value = ''
            }}
          />
          <button className="btn btn-primary" onClick={() => fileRef.current?.click()} disabled={installing}>
            {installing ? <span className="spinner spinner-sm" /> : <Icon name="plug" size={16} />}
            安装插件 ZIP
          </button>
        </div>

        {loading ? (
          <div className="settings-loading">
            <span className="spinner" /> 读取插件…
          </div>
        ) : (
          <div className="plugin-grid">
            {plugins.map((plugin) => (
              <article className={`plugin-card ${plugin.enabled ? '' : 'is-off'}`} key={plugin.id}>
                <div className="plugin-card-head">
                  <div className="plugin-glyph">
                    <Icon name="plug" size={18} />
                  </div>
                  <div>
                    <h4>
                      {plugin.name}
                      {plugin.builtin ? <span className="plugin-badge">内置</span> : null}
                    </h4>
                    <span className="plugin-version">v{plugin.version} · {plugin.author}</span>
                  </div>
                </div>
                <p>{plugin.description || '没有描述'}</p>
                <div className="plugin-meta">
                  <span>{plugin.prompt_count || 0} 个模板</span>
                  {plugin.installed_at ? <span>{formatRelativeTime(plugin.installed_at)}</span> : <span>随应用提供</span>}
                </div>
                <div className="plugin-actions">
                  <button
                    className="btn btn-sm btn-ghost"
                    onClick={() => setExpanded((current) => (current === plugin.id ? null : plugin.id))}
                  >
                    {expanded === plugin.id ? '收起模板' : '查看模板'}
                  </button>
                  {plugin.builtin ? (
                    <span className="status-pill ok">可用</span>
                  ) : (
                    <>
                      <button className="btn btn-sm btn-ghost" onClick={() => toggle(plugin)}>
                        {plugin.enabled ? '停用' : '启用'}
                      </button>
                      <button className="mini-icon-btn danger" onClick={() => setDeleteTarget(plugin)} title="卸载">
                        <Icon name="trash" size={15} />
                      </button>
                    </>
                  )}
                </div>
                {expanded === plugin.id ? (
                  <div className="plugin-prompts">
                    {(plugin.prompts || []).map((prompt) => (
                      <div className="plugin-prompt" key={prompt.title}>
                        <strong>{prompt.title}</strong>
                        <span>{prompt.mode === 'reasoner' ? '推理模式' : '日常模式'}</span>
                        <p>{prompt.prompt.slice(0, 180)}{prompt.prompt.length > 180 ? '…' : ''}</p>
                      </div>
                    ))}
                  </div>
                ) : null}
              </article>
            ))}
          </div>
        )}
      </Modal>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="卸载插件"
        message={`确定卸载「${deleteTarget?.name || ''}」吗？插件目录会被删除。`}
        confirmText="卸载"
        danger
        loading={deleting}
        onConfirm={remove}
        onCancel={() => setDeleteTarget(null)}
      />
    </>
  )
}
