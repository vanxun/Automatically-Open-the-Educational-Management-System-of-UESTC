# UESTC 教务系统自动打开脚本

这是一个用 Python + Playwright 编写的用来自动打开电子科技大学的 WebVPN，并进入教务系统页面脚本。

该脚本会自动打开电子科技大学WebVPN并模拟输入登录，然后跳转网上服务大厅→教务系统→课程管理，并自动关闭多余网页。

该脚本支持自动通过重复登录时踢出上次登录的功能。但第一次登陆可能需要手动过一下人机验证。

请注意网速过差可能导致脚本一直找不到页面并中断。

可能出现关闭浏览器窗口后终端没能自行关闭的情况，此时请手动关闭。

## 环境要求

需要安装：

- Python 3.10 或更新版本
- Playwright
- Playwright 的 Chromium 浏览器组件

## 安装依赖

在当前文件夹打开终端，执行：

```bash
pip install playwright
python -m playwright install chromium
```

## 配置账号

编辑 `config.json`：

```json
{
  "student_id": "你的学号",
  "password": "你的密码"
}
```

## 使用方法

双击：

```text
打开教务系统.bat
```

或者在终端中运行：

```bash
python uestc_jw.py
```

脚本会打开一个独立的 Chromium 浏览器窗口，不影响正在使用的 Chrome。
