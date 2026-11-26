# 插件格式（V3）

Dreikanterbot 的插件是**声明式提示词包**，不是可执行代码。这样可以上传、分享、启停，而不会让一个 ZIP 获得服务器权限。

## 目录结构

```text
my-plugin.zip
├── plugin.json
├── README.md          # 可选
└── prompts/
    └── notes.md       # 可选，仅作说明
```

也支持 ZIP 内只有一个顶层目录：

```text
my-plugin/
├── plugin.json
└── README.md
```

## plugin.json

```json
{
  "id": "my-plugin",
  "name": "我的工作流",
  "version": "1.0.0",
  "description": "这个插件解决什么问题",
  "author": "你的名字",
  "prompts": [
    {
      "title": "整理会议记录",
      "prompt": "把下面的会议记录整理成：结论、待办、负责人、截止时间、未决问题。\n\n",
      "mode": "chat"
    },
    {
      "title": "审查方案",
      "prompt": "请以审查者身份找出这个方案的前提、风险、缺失的验证步骤。\n\n方案：\n",
      "mode": "reasoner"
    }
  ]
}
```

限制：

- `id`：小写字母/数字/点/下划线/短横线，2–64 位；
- `prompts`：至少 1 个，最多 50 个；
- `title`：≤80 字；`prompt`：≤20,000 字；
- ZIP 只允许 `.json` / `.md` / `.txt`，最多 80 个文件，单文件 ≤2MB，ZIP ≤10MB；
- 拒绝 `..`、绝对路径、可执行文件。

## 安装与使用

1. 侧边栏 → 插件 → 安装插件 ZIP；
2. 在插件卡片里查看模板、启停或卸载；
3. Composer 左侧插件按钮可直接把模板插入输入框；
4. 模板只是文本，不会自动发送，也不会读取你的对话。

## 安全边界

- 服务端不会 `eval`、`exec`、`import` 插件内任何内容；
- 插件不能访问数据库、文件系统或网络；
- 这是有意的限制：如果你需要“工具型插件”（HTTP/代码执行），应单独设计权限、审计和沙箱，而不是放开任意 ZIP。
