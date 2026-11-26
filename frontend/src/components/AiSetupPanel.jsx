import Modal from './Modal'
import AiSettingsForm from './AiSettingsForm'
import Icon from './Icons'

export default function AiSetupPanel({ open, onClose, onSaved }) {
  return (
    <Modal
      open={open}
      onClose={onClose}
      title="连接模型"
      subtitle="V3.0 起使用你自己的 API Key；上下文可以拉满"
      size="lg"
    >
      <div className="ai-setup-intro">
        <div>
          <span className="eyebrow">BYOK · BRING YOUR OWN KEY</span>
          <h3>先接入，再开始</h3>
          <p>
            这里不代收模型费用。你的 Key 只用于调用你选择的模型服务；对话记录仍然保存在你自己的
            Dreikanterbot 数据库里。
          </p>
        </div>
        <div className="ai-setup-badge">
          <Icon name="shield" size={20} />
          <strong>加密存储</strong>
          <span>接口只返回末四位</span>
        </div>
      </div>
      <AiSettingsForm onSaved={onSaved} />
    </Modal>
  )
}
