# Windows 一键安装包

只需要一个文件：[`Install-BeijingClock.cmd`](../dist/Install-BeijingClock.cmd)。
复制到另一台电脑，双击运行即可。无需 Python、pyserial、pywin32、联网或管理员权限。
安装完成后可删除安装包、移动或删除源码工程。

程序安装到当前用户的 `%LOCALAPPDATA%\STM32BeijingClock\BeijingClockSync.exe`，
登录启动项直接指向这个 EXE，不保存开发电脑的盘符、用户名、Python 路径或工程路径。
安装会替换旧版的同名启动项；重复运行可修复、更新。

## 使用

1. 在每台电脑上安装一次，看到 `Installed successfully` 和 `Completed` 即成功。
2. 将已烧录固件的开发板通过 USB-C 数据线插入电脑。
3. 后台自动寻找本项目设备，校到电脑当前时间一次，随后由板上 RTC 独立走钟。
4. 拔下再插入会重新校时，COM 号可以变化；持续连接期间不会反复校时。

日志：`%LOCALAPPDATA%\STM32BeijingClock\logs\clock-sync.log`。
`SYNC_OK` 是校时成功，`SYNC_RETRY` 表示设备尚未就绪或串口占用，程序会继续重试。
安装时如果运行着早期 Python 版后台，请先关闭旧后台或安装后重新登录一次。

## 兼容范围

- 面向普通桌面版 Windows 10/11，使用系统自带的 Windows PowerShell 和 .NET Framework 4.x。
- 安装时从随包 C# 源码编译 **AnyCPU** 程序，不固定为某台电脑的 Python 或某一种原生二进制架构。
- x86/x64 使用对应系统 CLR；ARM64 需要能运行 .NET Framework 4.x 程序的 Windows 环境。
- 已在当前 Windows x64 电脑测试；没有声称在全部 Windows 版本、ARM64 设备及企业策略环境实测。
- Windows 7/8、Windows S 模式及禁止编译/启动程序的受管环境，不保证一键可用。
  旧系统还可能需要手工安装 USB CDC 驱动；安装器不会修改系统安全策略或下载驱动。

[微软：Windows 自带的 .NET Framework](https://learn.microsoft.com/en-us/dotnet/framework/install/on-windows-and-server)
和 [Add-Type 编译接口](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/add-type?view=powershell-5.1)。

## 命令与卸载

```bat
Install-BeijingClock.cmd
Install-BeijingClock.cmd /uninstall
Install-BeijingClock.cmd /test /quiet
```

`/test` 只检查编译、协议和设备枚举，不安装、不校时。
`/uninstall` 停止新版后台并删除登录启动项，保留日志供检查。
整个安装过程不修改 PowerShell 的全局执行策略，不申请管理员权限。

## 构建与验证

```powershell
python tools/build_windows_package.py
python tools/test_windows_package.py
```

构建使用 Python 标准库，只把 `windows/BeijingClockSync.cs` 编码进 CMD；
最终用户不需要 Python。CMD 会用 Windows 自带编译器在临时目录编译程序，
复制到用户安装目录并核验启动项，再自动启动后台，最后清理本次临时文件。
源码未混淆，CMD 内 Base64 只是为了保持一个文件，可由构建脚本完整还原。

测试覆盖协议序列化/非法应答、AnyCPU 标志、中文/空格/单引号/`&` 路径、
安装/重复安装/卸载及在 PATH 中没有 Python 时独立运行 CMD。
