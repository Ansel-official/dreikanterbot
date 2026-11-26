using System;
using System.Drawing;
using System.IO;
using System.Windows.Forms;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

namespace Dreikanterbot.Desktop
{
    internal static class ConfigStore
    {
        private static string ConfigPath
        {
            get
            {
                // 便携版：配置放在 exe 同目录，避免受限账户对 %LOCALAPPDATA% 的写入限制。
                var dir = AppDomain.CurrentDomain.BaseDirectory;
                return Path.Combine(dir, "desktop.config");
            }
        }

        public static string ServerUrl
        {
            get
            {
                try
                {
                    if (!File.Exists(ConfigPath)) return "";
                    return File.ReadAllText(ConfigPath).Trim();
                }
                catch { }
                return "";
            }
            set
            {
                try
                {
                    File.WriteAllText(ConfigPath, value ?? "");
                }
                catch { }
            }
        }

        public static string Normalize(string value)
        {
            var text = (value ?? "").Trim();
            if (text.Length == 0) return "";
            if (!text.StartsWith("http://", StringComparison.OrdinalIgnoreCase)
                && !text.StartsWith("https://", StringComparison.OrdinalIgnoreCase))
                text = "https://" + text;
            Uri uri;
            if (!Uri.TryCreate(text, UriKind.Absolute, out uri)) return "";
            if (uri.Scheme != "http" && uri.Scheme != "https") return "";
            return text.TrimEnd('/');
        }
    }

    internal sealed class SetupForm : Form
    {
        private readonly TextBox _input;
        public string ServerUrl { get; private set; }

        public SetupForm(string current)
        {
            Text = "连接 Dreikanterbot";
            Width = 560;
            Height = 300;
            StartPosition = FormStartPosition.CenterScreen;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            BackColor = Color.FromArgb(242, 240, 234);

            var title = new Label
            {
                Text = "先连上你的服务器",
                Font = new Font("Microsoft YaHei", 18F, FontStyle.Regular),
                ForeColor = Color.FromArgb(31, 29, 25),
                AutoSize = true,
                Left = 34,
                Top = 30,
            };
            var hint = new Label
            {
                Text = "桌面端只是工作台外壳。填写你部署好的 Dreikanterbot 地址，\n登录后即可使用对话、记忆库和插件。",
                Font = new Font("Microsoft YaHei", 9.5F),
                ForeColor = Color.FromArgb(122, 116, 105),
                AutoSize = true,
                Left = 36,
                Top = 76,
            };
            _input = new TextBox
            {
                Left = 36,
                Top = 132,
                Width = 470,
                Height = 32,
                Font = new Font("Microsoft YaHei", 10F),
                Text = current ?? "",
                BorderStyle = BorderStyle.FixedSingle,
            };
            var button = new Button
            {
                Text = "连接",
                Left = 36,
                Top = 182,
                Width = 470,
                Height = 40,
                BackColor = Color.FromArgb(180, 71, 47),
                ForeColor = Color.White,
                FlatStyle = FlatStyle.Flat,
                Font = new Font("Microsoft YaHei", 10F, FontStyle.Bold),
            };
            button.FlatAppearance.BorderSize = 0;
            button.Click += (s, e) => Accept();

            Controls.Add(title);
            Controls.Add(hint);
            Controls.Add(_input);
            Controls.Add(button);
            AcceptButton = button;
        }

        private void Accept()
        {
            var url = ConfigStore.Normalize(_input.Text);
            if (url.Length == 0)
            {
                MessageBox.Show(this, "请输入完整的 http(s) 地址。", "地址不正确", MessageBoxButtons.OK, MessageBoxIcon.Warning);
                return;
            }
            ServerUrl = url;
            DialogResult = DialogResult.OK;
            Close();
        }
    }

    internal sealed class MainForm : Form
    {
        private readonly WebView2 _web;
        private string _serverUrl;

        public MainForm(string serverUrl)
        {
            _serverUrl = serverUrl;
            Text = "Dreikanterbot";
            Width = 1320;
            Height = 860;
            MinimumSize = new Size(980, 640);
            StartPosition = FormStartPosition.CenterScreen;
            BackColor = Color.FromArgb(242, 240, 234);

            var menu = new MenuStrip();
            var file = new ToolStripMenuItem("文件");
            file.DropDownItems.Add("更换服务器地址", null, (s, e) => ChangeServer());
            file.DropDownItems.Add(new ToolStripSeparator());
            file.DropDownItems.Add("退出", null, (s, e) => Close());
            var view = new ToolStripMenuItem("视图");
            view.DropDownItems.Add("刷新", null, (s, e) => _web.Reload());
            view.DropDownItems.Add("放大", null, (s, e) => Zoom(0.1));
            view.DropDownItems.Add("缩小", null, (s, e) => Zoom(-0.1));
            view.DropDownItems.Add("实际大小", null, (s, e) => _web.ZoomFactor = 1.0);
            menu.Items.Add(file);
            menu.Items.Add(view);
            MainMenuStrip = menu;
            Controls.Add(menu);

            _web = new WebView2 { Dock = DockStyle.Fill };
            Controls.Add(_web);
            _web.BringToFront();
            Load += async (s, e) => await InitializeAsync();
        }

        private async System.Threading.Tasks.Task InitializeAsync()
        {
            try
            {
                var dataDir = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "WebView2Data");
                Directory.CreateDirectory(dataDir);
                var env = await CoreWebView2Environment.CreateAsync(null, dataDir);
                await _web.EnsureCoreWebView2Async(env);
                _web.CoreWebView2.Settings.AreDefaultContextMenusEnabled = true;
                _web.CoreWebView2.Settings.AreDevToolsEnabled = true;
                _web.CoreWebView2.Settings.IsStatusBarEnabled = false;
                _web.CoreWebView2.NewWindowRequested += (s, e) =>
                {
                    e.Handled = true;
                    try { System.Diagnostics.Process.Start(e.Uri); } catch { }
                };
                _web.CoreWebView2.NavigationCompleted += (s, e) =>
                {
                    if (!e.IsSuccess)
                    {
                        MessageBox.Show(this, "页面加载失败，请检查服务器地址或网络。", "无法连接",
                            MessageBoxButtons.OK, MessageBoxIcon.Warning);
                    }
                };
                Navigate();
            }
            catch (Exception ex)
            {
                MessageBox.Show(this, "WebView2 初始化失败：\n" + ex.Message, "启动失败",
                    MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private void Navigate()
        {
            if (_web.CoreWebView2 == null || string.IsNullOrWhiteSpace(_serverUrl)) return;
            _web.Source = new Uri(_serverUrl);
        }

        private void ChangeServer()
        {
            using (var dialog = new SetupForm(_serverUrl))
            {
                if (dialog.ShowDialog(this) == DialogResult.OK)
                {
                    _serverUrl = dialog.ServerUrl;
                    ConfigStore.ServerUrl = _serverUrl;
                    Navigate();
                }
            }
        }

        private void Zoom(double delta)
        {
            var next = _web.ZoomFactor + delta;
            _web.ZoomFactor = Math.Max(0.5, Math.Min(2.5, next));
        }
    }

    internal static class Program
    {
        [STAThread]
        private static void Main()
        {
            var log = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "desktop-start.log");
            try
            {
                File.WriteAllText(log, "start " + DateTime.Now.ToString("s") + Environment.NewLine);
                Application.ThreadException += (s, e) => Log(log, "thread: " + e.Exception);
                AppDomain.CurrentDomain.UnhandledException += (s, e) => Log(log, "domain: " + e.ExceptionObject);
                Application.EnableVisualStyles();
                Application.SetCompatibleTextRenderingDefault(false);
                var url = ConfigStore.ServerUrl;
                Log(log, "url=" + url);
                if (string.IsNullOrWhiteSpace(url))
                {
                    using (var setup = new SetupForm(""))
                    {
                        if (setup.ShowDialog() != DialogResult.OK) return;
                        url = setup.ServerUrl;
                        ConfigStore.ServerUrl = url;
                    }
                }
                Log(log, "run form");
                Application.Run(new MainForm(url));
            }
            catch (Exception ex)
            {
                Log(log, "fatal: " + ex);
                MessageBox.Show("启动失败：\n" + ex.Message, "Dreikanterbot", MessageBoxButtons.OK, MessageBoxIcon.Error);
            }
        }

        private static void Log(string path, string text)
        {
            try { File.AppendAllText(path, text + Environment.NewLine); } catch { }
        }
    }
}
