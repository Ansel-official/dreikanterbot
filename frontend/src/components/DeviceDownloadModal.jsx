import { useMemo } from 'react'
import Modal from './Modal'
import Icon from './Icons'
import { usePwaInstall } from '../hooks/usePwaInstall'
import { useToast } from './Toast'

const REPO_URL = 'https://github.com/Ansel-official/dreikanterbot'
const RELEASE_URL = `${REPO_URL}/releases/download/v3.1.0`
const WIN_ZIP = `${RELEASE_URL}/Dreikanterbot-3.1.0-win-x64.zip`
const APK_URL = `${RELEASE_URL}/Dreikanterbot-3.1.0.apk`

const DEVICES = [
  {
    id: 'iphone',
    icon: 'message',
    name: 'iPhone',
    recommend: 'iPhone 12 及以上',
    browser: 'iOS 16.4+ · Safari',
    detail: 'Safari 分享按钮 → 添加到主屏幕。麦克风需 HTTPS。',
  },
  {
    id: 'ipad',
    icon: 'fileText',
    name: 'iPad',
    recommend: 'iPadOS 16.4+',
    browser: 'Safari 17+',
    detail: '横屏使用体验最佳；添加到主屏幕后可全屏运行。',
  },
  {
    id: 'android',
    icon: 'globe',
    name: 'Android 手机 / 平板',
    recommend: '4GB RAM 及以上',
    browser: 'Chrome 120+ / Edge',
    detail: 'Chrome 菜单 → 添加到主屏幕；支持安装为 PWA。',
  },
  {
    id: 'desktop',
    icon: 'database',
    name: 'Windows / macOS / Linux',
    recommend: '8GB RAM 及以上',
    browser: 'Chrome / Edge / Safari 17+',
    detail: '地址栏右侧安装图标即可获得独立窗口；也可直接使用浏览器。',
  },
]

function detectPlatform() {
  const ua = navigator.userAgent || ''
  if (/iPhone/i.test(ua)) return 'iphone'
  if (/iPad/i.test(ua) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1)) return 'ipad'
  if (/Android/i.test(ua)) return 'android'
  return 'desktop'
}

export default function DeviceDownloadModal({ open, onClose }) {
  const platform = useMemo(detectPlatform, [])
  const { canPrompt, installed, promptInstall } = usePwaInstall()
  const toast = useToast()

  const install = async () => {
    if (installed) {
      toast('已经安装到当前设备', 'success')
      return
    }
    if (canPrompt) {
      const result = await promptInstall()
      if (result === 'accepted') toast('正在安装 Dreikanterbot', 'success')
      else if (result === 'dismissed') toast('已取消安装', 'info')
      return
    }
    const tips = {
      iphone: '请用 Safari 打开，点击底部「分享」→「添加到主屏幕」。',
      ipad: '请用 Safari 打开，点击「分享」→「添加到主屏幕」。',
      android: '请用 Chrome 打开，点击右上角菜单 →「添加到主屏幕 / 安装应用」。',
      desktop: '请用 Chrome / Edge 打开，点击地址栏右侧的安装图标。',
    }
    toast(tips[platform] || tips.desktop, 'info')
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="下载与设备"
      subtitle="Dreikanterbot 支持 iPhone、iPad、Android、Windows、macOS 与 Linux"
      size="lg"
    >
      <section className="download-hero">
        <div>
          <span className="eyebrow">PWA · 无需应用商店</span>
          <h3>安装到当前设备</h3>
          <p>安装后拥有独立图标和全屏窗口，历史对话仍然保存在你的服务器。</p>
        </div>
        <button className="btn btn-primary" onClick={install} disabled={installed}>
          <Icon name="download" size={17} />
          {installed ? '已安装' : '安装 Dreikanterbot'}
        </button>
      </section>

      <div className="download-actions">
        <a className="download-card" href={WIN_ZIP} target="_blank" rel="noreferrer">
          <Icon name="download" size={20} />
          <div>
            <strong>Windows 便携版</strong>
            <span>EXE + WebView2，首次填写服务器地址</span>
          </div>
          <Icon name="chevronRight" size={16} />
        </a>
        <a className="download-card" href={APK_URL} target="_blank" rel="noreferrer">
          <Icon name="download" size={20} />
          <div>
            <strong>Android APK</strong>
            <span>侧载安装，测试签名；Android 7+</span>
          </div>
          <Icon name="chevronRight" size={16} />
        </a>
        <a className="download-card" href={`${REPO_URL}/releases`} target="_blank" rel="noreferrer">
          <Icon name="database" size={20} />
          <div>
            <strong>Web / 部署包</strong>
            <span>静态前端 ZIP 与完整 Docker 部署包</span>
          </div>
          <Icon name="chevronRight" size={16} />
        </a>
      </div>

      <h3 className="download-heading">设备建议</h3>
      <div className="device-grid">
        {DEVICES.map((device) => (
          <div className={`device-card ${platform === device.id ? 'current' : ''}`} key={device.id}>
            <div className="device-card-head">
              <span className="device-icon">
                <Icon name={device.icon} size={18} />
              </span>
              <strong>{device.name}</strong>
              {platform === device.id ? <span className="current-tag">当前</span> : null}
            </div>
            <div className="device-meta">{device.recommend}</div>
            <div className="device-browser">{device.browser}</div>
            <p>{device.detail}</p>
          </div>
        ))}
      </div>

      <div className="download-note">
        <Icon name="info" size={16} />
        <p>
          语音输入和安装 PWA 需要 HTTPS；建议使用 5GHz Wi-Fi 或 4G/5G。EXE/APK 只是工作台外壳，
          需要先部署服务器；APK 为测试签名，正式上架请换自己的 keystore。
        </p>
      </div>
      <p className="download-footnote">
        <a href={REPO_URL} target="_blank" rel="noreferrer">
          查看 GitHub 仓库
        </a>
        <span> · </span>
        <a href={`${REPO_URL}/releases`} target="_blank" rel="noreferrer">
          全部版本
        </a>
      </p>
    </Modal>
  )
}
