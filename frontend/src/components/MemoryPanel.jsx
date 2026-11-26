import { useCallback, useEffect, useRef, useState } from 'react'
import api, { downloadFromApi, errorMessage } from '../api/client'
import { useToast } from './Toast'
import Modal from './Modal'
import ConfirmDialog from './ConfirmDialog'
import Icon from './Icons'
import { formatRelativeTime, formatNumber } from '../utils'

const KIND_LABELS = {
  note: '笔记',
  data: '数据',
  code: '代码',
  image: '图片',
  document: '文档',
  file: '文件',
}

function formatSize(bytes) {
  if (!bytes) return '0 B'
  if (bytes >= 1024 * 1024 * 1024) return `${(bytes / 1024 / 1024 / 1024).toFixed(1)} GB`
  if (bytes >= 1024 * 1024) return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  if (bytes >= 1024) return `${Math.round(bytes / 1024)} KB`
  return `${bytes} B`
}

export default function MemoryPanel({ open, onClose }) {
  const toast = useToast()
  const fileRef = useRef(null)
  const importRef = useRef(null)
  const [items, setItems] = useState([])
  const [stats, setStats] = useState({ used_bytes: 0, limit_bytes: 0 })
  const [loading, setLoading] = useState(false)
  const [query, setQuery] = useState('')
  const [folder, setFolder] = useState('')
  const [uploading, setUploading] = useState(false)
  const [deleteTarget, setDeleteTarget] = useState(null)
  const [deleting, setDeleting] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [cloud, setCloud] = useState(null)
  const [cloudForm, setCloudForm] = useState({
    base_url: '',
    username: '',
    password: '',
    remote_path: 'dreikanterbot',
    enabled: true,
  })
  const [cloudBusy, setCloudBusy] = useState('')

  const load = useCallback(
    async (keyword = query) => {
      setLoading(true)
      try {
        const response = await api.get('/memory', {
          params: { q: keyword.trim() || undefined, folder: folder.trim() || undefined, limit: 100 },
        })
        setItems(response.data.items || [])
        setStats({ used_bytes: response.data.used_bytes || 0, limit_bytes: response.data.limit_bytes || 0 })
      } catch (error) {
        toast(errorMessage(error, '读取记忆库失败'), 'error')
      } finally {
        setLoading(false)
      }
    },
    [folder, query, toast]
  )

  const loadCloud = useCallback(async () => {
    try {
      const response = await api.get('/memory/cloud')
      setCloud(response.data)
      setCloudForm((current) => ({
        ...current,
        base_url: response.data.base_url || '',
        username: response.data.username || '',
        remote_path: response.data.remote_path || 'dreikanterbot',
        enabled: response.data.enabled !== false,
        password: '',
      }))
    } catch {
      /* 云端是可选功能，静默失败 */
    }
  }, [])

  useEffect(() => {
    if (!open) return
    load('')
    loadCloud()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open])

  async function uploadFiles(files) {
    const list = Array.from(files || [])
    if (!list.length) return
    setUploading(true)
    let ok = 0
    for (const file of list) {
      const form = new FormData()
      form.append('file', file)
      form.append('folder', folder.trim())
      form.append('tags', '')
      try {
        await api.post('/memory/upload', form, { timeout: 180000 })
        ok += 1
      } catch (error) {
        toast(errorMessage(error, `${file.name} 上传失败`), 'error')
      }
    }
    setUploading(false)
    if (ok) toast(`已加入 ${ok} 个文件`, 'success')
    await load('')
  }

  async function removeItem() {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await api.delete(`/memory/${deleteTarget.id}`)
      setItems((current) => current.filter((item) => item.id !== deleteTarget.id))
      setDeleteTarget(null)
      toast('已删除', 'success')
      load('')
    } catch (error) {
      toast(errorMessage(error, '删除失败'), 'error')
    } finally {
      setDeleting(false)
    }
  }

  async function exportAll() {
    setExporting(true)
    try {
      await downloadFromApi('/memory/export', 'dreikanterbot-memory.zip')
      toast('导出已开始下载', 'success')
    } catch (error) {
      toast(errorMessage(error, '导出失败'), 'error')
    } finally {
      setExporting(false)
    }
  }

  async function importZip(file) {
    if (!file) return
    const form = new FormData()
    form.append('file', file)
    try {
      const response = await api.post('/memory/import', form, { timeout: 180000 })
      toast(`导入 ${response.data.imported} 个文件，跳过 ${response.data.skipped} 个`, 'success')
      await load('')
    } catch (error) {
      toast(errorMessage(error, '导入失败'), 'error')
    }
  }

  async function saveCloud() {
    setCloudBusy('save')
    try {
      const response = await api.put('/memory/cloud', {
        ...cloudForm,
        password: cloudForm.password || undefined,
      })
      setCloud(response.data)
      setCloudForm((current) => ({ ...current, password: '' }))
      toast('云端配置已保存', 'success')
    } catch (error) {
      toast(errorMessage(error, '保存云端配置失败'), 'error')
    } finally {
      setCloudBusy('')
    }
  }

  async function cloudAction(action, label) {
    setCloudBusy(action)
    try {
      const response = await api.post(`/memory/cloud/${action}`, null, { timeout: 300000 })
      const detail =
        action === 'sync'
          ? `已上传 ${response.data.uploaded} 个文件`
          : action === 'pull'
            ? `已拉取 ${response.data.imported} 个，跳过 ${response.data.skipped} 个`
            : `连接正常，云端 ${response.data.files} 个条目`
      toast(detail, 'success')
      if (action !== 'test') load('')
    } catch (error) {
      toast(errorMessage(error, `${label}失败`), 'error')
    } finally {
      setCloudBusy('')
    }
  }

  const usedPercent = stats.limit_bytes ? Math.min(100, (stats.used_bytes / stats.limit_bytes) * 100) : 0

  return (
    <>
      <Modal
        open={open}
        onClose={onClose}
        title="记忆库"
        subtitle="把文件留在自己手里：本地保存、全文检索、随时下载，也可以同步到自己的 WebDAV"
        size="xl"
      >
        <div className="memory-head">
          <div className="memory-search">
            <Icon name="search" size={16} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') load(query)
              }}
              placeholder="搜索标题或全文…"
            />
            <button className="btn btn-sm btn-ghost" onClick={() => load(query)}>
              搜索
            </button>
          </div>
          <div className="memory-head-actions">
            <input
              value={folder}
              onChange={(event) => setFolder(event.target.value)}
              placeholder="文件夹（可选）"
              className="memory-folder-input"
            />
            <input
              ref={fileRef}
              type="file"
              multiple
              hidden
              onChange={(event) => uploadFiles(event.target.files)}
            />
            <button className="btn btn-primary" onClick={() => fileRef.current?.click()} disabled={uploading}>
              {uploading ? <span className="spinner spinner-sm" /> : <Icon name="upload" size={16} />}
              加入文件
            </button>
          </div>
        </div>

        <div className="memory-stats">
          <span>
            已用 {formatSize(stats.used_bytes)} / {formatSize(stats.limit_bytes)}
          </span>
          <div className="memory-track">
            <div className="memory-fill" style={{ width: `${usedPercent}%` }} />
          </div>
          <span>{formatNumber(items.length)} 个条目</span>
        </div>

        <div className="memory-list">
          {loading ? (
            <div className="settings-loading">
              <span className="spinner" /> 读取记忆库…
            </div>
          ) : items.length === 0 ? (
            <div className="empty-inline memory-empty">
              <Icon name="memory" size={23} />
              <p>还没有文件。把 PDF、表格、代码或笔记拖进来。</p>
            </div>
          ) : (
            items.map((item) => (
              <div className="memory-item" key={item.id}>
                <div className="memory-kind">
                  <Icon
                    name={
                      item.kind === 'code'
                        ? 'fileText'
                        : item.kind === 'document'
                          ? 'fileText'
                          : item.kind === 'image'
                            ? 'globe'
                            : 'memory'
                    }
                    size={17}
                  />
                </div>
                <div className="memory-main">
                  <div className="memory-title">
                    {item.title}
                    <span className="memory-tag">{KIND_LABELS[item.kind] || '文件'}</span>
                    {item.folder ? <span className="memory-tag ghost">{item.folder}</span> : null}
                  </div>
                  <div className="memory-meta">
                    <span>{formatSize(item.size)}</span>
                    <span>{formatNumber(item.text_chars)} 字可检索</span>
                    <span>{formatRelativeTime(item.created_at)}</span>
                  </div>
                </div>
                <div className="memory-actions">
                  <button
                    className="mini-icon-btn"
                    title="下载原文件"
                    onClick={() => downloadFromApi(item.download_url, item.title)}
                  >
                    <Icon name="download" size={15} />
                  </button>
                  <button className="mini-icon-btn danger" title="删除" onClick={() => setDeleteTarget(item)}>
                    <Icon name="trash" size={15} />
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        <div className="memory-toolbar">
          <button className="btn btn-ghost" onClick={exportAll} disabled={exporting}>
            {exporting ? <span className="spinner spinner-sm" /> : <Icon name="download" size={16} />}
            导出全部 ZIP
          </button>
          <input
            ref={importRef}
            type="file"
            accept=".zip,application/zip"
            hidden
            onChange={(event) => {
              importZip(event.target.files?.[0])
              event.target.value = ''
            }}
          />
          <button className="btn btn-ghost" onClick={() => importRef.current?.click()}>
            <Icon name="upload" size={16} />
            从 ZIP 导入
          </button>
        </div>

        <details className="cloud-section" open={Boolean(cloud?.base_url)}>
          <summary>
            <Icon name="cloud" size={16} />
            个人云端（WebDAV）
            <span className={`status-pill ${cloud?.enabled ? 'ok' : 'off'}`}>
              {cloud?.enabled ? '已启用' : '未配置'}
            </span>
          </summary>
          <p className="settings-desc">
            支持 Nextcloud、坚果云、群晖等 WebDAV。密码用服务端密钥加密；同步时只上传你的记忆库文件。
          </p>
          <div className="ai-form-grid">
            <label className="field field-span-2">
              <span>WebDAV 地址</span>
              <div className="input-wrap">
                <Icon name="globe" size={16} />
                <input
                  value={cloudForm.base_url}
                  onChange={(event) => setCloudForm((c) => ({ ...c, base_url: event.target.value }))}
                  placeholder="https://dav.jianguoyun.com/dav/"
                />
              </div>
            </label>
            <label className="field">
              <span>账号</span>
              <div className="input-wrap">
                <Icon name="user" size={16} />
                <input
                  value={cloudForm.username}
                  onChange={(event) => setCloudForm((c) => ({ ...c, username: event.target.value }))}
                />
              </div>
            </label>
            <label className="field">
              <span>应用密码 / 令牌</span>
              <div className="input-wrap">
                <Icon name="lock" size={16} />
                <input
                  type="password"
                  value={cloudForm.password}
                  onChange={(event) => setCloudForm((c) => ({ ...c, password: event.target.value }))}
                  placeholder={cloud?.has_password ? '已保存，留空不修改' : ''}
                />
              </div>
            </label>
            <label className="field">
              <span>远端目录</span>
              <div className="input-wrap">
                <Icon name="folder" size={16} />
                <input
                  value={cloudForm.remote_path}
                  onChange={(event) => setCloudForm((c) => ({ ...c, remote_path: event.target.value }))}
                />
              </div>
            </label>
            <label className="field field-inline">
              <span>启用</span>
              <input
                type="checkbox"
                checked={cloudForm.enabled}
                onChange={(event) => setCloudForm((c) => ({ ...c, enabled: event.target.checked }))}
              />
            </label>
          </div>
          <div className="button-row">
            <button className="btn btn-primary" onClick={saveCloud} disabled={Boolean(cloudBusy)}>
              {cloudBusy === 'save' ? <span className="spinner spinner-sm" /> : <Icon name="check" size={16} />}
              保存云端
            </button>
            <button className="btn btn-ghost" onClick={() => cloudAction('test', '测试')} disabled={Boolean(cloudBusy)}>
              测试连接
            </button>
            <button className="btn btn-ghost" onClick={() => cloudAction('sync', '同步')} disabled={Boolean(cloudBusy)}>
              上传到云端
            </button>
            <button className="btn btn-ghost" onClick={() => cloudAction('pull', '拉取')} disabled={Boolean(cloudBusy)}>
              从云端拉取
            </button>
          </div>
          {cloud?.last_sync_at ? (
            <p className="field-hint">上次同步：{formatRelativeTime(cloud.last_sync_at)}</p>
          ) : null}
        </details>
      </Modal>

      <ConfirmDialog
        open={Boolean(deleteTarget)}
        title="删除记忆文件"
        message={`确定删除「${deleteTarget?.title || ''}」吗？原文件会从服务器磁盘移除，无法恢复。`}
        confirmText="删除"
        danger
        loading={deleting}
        onConfirm={removeItem}
        onCancel={() => setDeleteTarget(null)}
      />
    </>
  )
}
