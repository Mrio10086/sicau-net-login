# 川农校园网自动登录

四川农业大学校园网（WiFi 名 `i_sicau_wifi6`）的自动认证守护程序。
开机自启后常驻系统托盘：检测到没认证就自动登录，掉线自动重连，需要时还会自动把
无线网连回校园网。所有代码只做本地认证，不依赖任何服务器，密码用 Windows DPAPI 加密保存。

打包好的可执行文件在 **[Releases](https://github.com/Mrio10086/sicau-net-login/releases/latest)** 页面，不用装 Python。

## 它是怎么工作的

这套流程是 2026-09 在真实网络里抓出来的，不是猜的：

| 步骤 | 说明 |
| --- | --- |
| 在线判定 | `GET http://connect.rom.miui.com/generate_204` 返回 `204` 就是在网 |
| 未认证 | 华为 BRAS 会把请求拦成 `302`，`Location` 里带着 `wlanuserip` / `wlanacname` / `nasip` |
| 认证入口 | `/webdisconnweb.do` → `302 /index_auth.jsp?...` → `/webauth.do?<urlParameter>` |
| 登录 | `POST https://portal.sicau.edu.cn/webauth.do?<urlParameter>`，提交页面里 `#goLoginForm` 的字段 |
| 离线 | `POST https://portal.sicau.edu.cn/webdisconn.do?<urlParameter>` |

两个关键设计：

- **不硬编码表单字段。** 程序每次都先抓认证页，解析 `#goLoginForm` 里"有 name 且未 disabled"
  的字段原样回传，再覆盖 `userId` / `passwd` / `isRemind=0`。门户改版也不容易失效。
- **参数三级兜底。** 优先用探测时的 302 重定向参数；拿不到就请求 `/webdisconnweb.do`；
  再不行才用本机 IPv4 + 配置里的 BRAS 名拼装。

## 用法一：直接用打包好的 exe（不需要 Python）

到 [Releases](https://github.com/Mrio10086/sicau-net-login/releases/latest) 下载这两个文件：

| 文件 | 说明 |
| --- | --- |
| `sicau-net-login.exe` | 托盘版，**双击即用**，没有控制台黑框 |
| `sicau-net-login-cli.exe` | 命令行版，排错用（`sicau-net-login-cli.exe status`） |

第一次双击 `sicau-net-login.exe`，右下角会出现托盘图标并自动弹出设置窗口，
填好学号和密码点「保存」即可。退出请用托盘菜单里的「退出」。

想自己重新打包见下方[打包成 exe](#打包成-exe)。

## 用法二：直接用源码跑

```powershell
cd C:\Users\LENOVO\OneDrive\文档\ChatGPT\sicau-net-login
python -m pip install -r requirements.txt
```

需要 Python 3.10+（本机 3.13 已验证）。依赖只有 `requests`、`pystray`、`Pillow`。
两种方式共用同一份配置和凭据（都在 `%LOCALAPPDATA%\sicau-net-login\`）。

## 首次使用

```powershell
python run_tray.pyw      # 托盘程序；用 pythonw 运行不会弹黑框
```

托盘图标出现在右下角，右键菜单：

| 菜单项 | 作用 |
| --- | --- |
| 状态（灰显） | 实时状态：已认证 / 未认证 / 正在登录 / 非校园网… |
| 立即登录 | 手动认证一次，同时恢复被暂停的自动重连 |
| 立即离线 | 主动下线，**并暂停自动重连** |
| 查看日志 | 用默认程序打开日志文件 |
| 设置… | 学号密码、SSID 白名单、轮询间隔、开机自启等 |
| 清除已保存的密码 | 删除 `cred.dat` |
| 退出 | 停止守护并退出 |

第一次运行时因为没有保存密码，会自动弹出设置窗口，填好学号和密码点"保存"即可。
设置窗口里的"校验学号密码"会调用门户自己的 `checkUserPwdGeneral.do` 验证账号密码，不会真的登录。

> **关于"立即离线"**：手动离线后会进入暂停状态，不会立刻把你又登回去。
> 想恢复自动重连，点"立即登录"或重启程序。

## 命令行

```powershell
python cli.py status     # 查看是否已认证
python cli.py login      # 立即登录
python cli.py logout     # 立即离线
python cli.py check      # 校验已保存的学号密码
python cli.py status -v  # 附带调试输出
```

退出码：`0` 成功，`1` 失败，`2` 无需操作（已在线 / 已离线）。
用打包版的话把 `python cli.py` 换成 `sicau-net-login-cli.exe` 即可，参数完全一样。

命令行版和托盘版共用同一份配置与凭据。

## 打包成 exe

```powershell
.\build.ps1              # 托盘版 + 命令行版（默认）
.\build.ps1 -OneDir      # 托盘版输出成文件夹，启动更快
.\build.ps1 -SkipCli     # 只打托盘版
.\build.ps1 -Clean       # 打包前清掉 build/dist
.\build.ps1 -NoTest      # 跳过单元测试
```

产物在 `dist\`：

- `sicau-net-login.exe`（约 22 MB）— 托盘版，`--windowed` + `--onefile`
- `sicau-net-login-cli.exe`（约 12 MB）— 命令行版，`--console` + `--onefile`

脚本会自己装 `pyinstaller`、跑单元测试、用 `tools/make_icon.py` 生成和多尺寸图标
（和托盘图标同一套画法）。exe 图标就是右下角那个绿点。

几点说明：

- 单文件版每次启动会把自己解压到 `%TEMP%`，实测启动到完成一次状态检测约 0.5 秒，感知不到。
- exe 是 Window 子系统程序，双击不会出现黑框，所以**退出只能用托盘菜单的「退出」**。
- 未签名的 PyInstaller 产物偶尔会被杀毒软件误报，加个信任即可。

## 开机自启

设置窗口里勾选"开机自动启动"即可（在启动文件夹放一个快捷方式，**不需要管理员权限**）。
程序会自动判断自己是怎么运行的：源码方式指向 `pythonw.exe run_tray.pyw`，
exe 方式直接指向 exe 自己。

也可以用脚本（只对源码方式有意义）：

```powershell
.\install.ps1                # 装依赖 + 创建开机自启快捷方式
.\install.ps1 -NoAutostart   # 只装依赖
.\install.ps1 -Remove        # 删除开机自启快捷方式
```

## 数据放在哪

全部在 `%LOCALAPPDATA%\sicau-net-login\`（故意不放 OneDrive，避免把密码同步到云端）：

| 文件 | 内容 |
| --- | --- |
| `config.json` | 非敏感配置（学号、SSID、间隔、门户地址…） |
| `cred.dat` | DPAPI 加密的密码，**只有本机当前用户能解开** |
| `logs\app.log` | 滚动日志，单文件 1 MB × 5 份 |

换电脑或重装系统后 `cred.dat` 解不开，重新在设置里填一次密码就行。

## 排错

1. **先看日志**：托盘菜单 →"查看日志"，或 `%LOCALAPPDATA%\sicau-net-login\logs\app.log`。
2. **看当前状态**：`python cli.py status -v`（或 `sicau-net-login-cli.exe status -v`），会打印探测结果和拿到的认证参数。
3. **认证被拒但不知道原因**：程序会把门户返回的错误（如"密码错误"）原样显示出来。
4. **门户改版导致失败**：用浏览器登录一次，F12 → Network → 右键那条认证请求 →
   "Copy as cURL"，把请求里的字段名和程序日志里的对比（最可能是多了新字段或改了 Referer）。
   因为程序是照页面表单提交的，通常只需确认页面结构变化。

常见状态含义：

| 状态 | 含义 |
| --- | --- |
| 已认证 | 正常在线 |
| 未认证 + 错误信息 | 认证被拒，看错误信息（密码错误 / 帐号不存在 / 余额不足…） |
| 非校园网，已跳过 | 当前连的是别的 WiFi，且不在白名单里，故意不折腾 |
| 未配置账号密码 | 去设置里填 |
| 已手动离线（自动登录已暂停） | 你点过"立即离线"，点"立即登录"可恢复 |

## 测试

```powershell
python -m pytest -q
```

74 个用例，全部离线运行：用真实页面快照（已脱敏，`tests/fixtures/`）验证表单解析，
用桩对象验证登录/离线请求的地址与字段、参数兜底、退避重试、暂停逻辑。
不会真的发起认证请求。

## 已知限制

- 只支持 Windows（依赖 DPAPI、`netsh`、`NotifyAddrChange`）。
- 单账号；不做修改密码、套餐变更等门户上其他功能。
- BRAS 名和门户 IP 会随校区（雅安 / 成都 / 都江堰）不同；程序优先自动获取，
  配置里的值只是兜底，可在设置里改。



