# STM32F103 北京时间 OLED 时钟

STM32F103C8T6 + 0.91 英寸 SSD1306 OLED，24 小时制显示北京时间。
无 Wi-Fi、无备用电池：每次通过 USB 数据线连接电脑时校时一次，随后由硬件 RTC 独立走钟。

## Windows 用户：只需要一个 CMD

下载 [`dist/Install-BeijingClock.cmd`](dist/Install-BeijingClock.cmd)，双击安装。
也可以使用根目录同内容的 [`install_usb_autosync.cmd`](install_usb_autosync.cmd)。

- 不用安装 Python、pyserial 或 pywin32，不联网下载依赖，不需要管理员权限。
- 安装到当前用户的 `%LOCALAPPDATA%\STM32BeijingClock`，启动项直接指向本机安装的 EXE。
- 安装完成后，可以删除 CMD、移动或删除源码工程；以后登录自动启动。
- 自动识别本项目设备及串口号，插入时只校一次，持续连接时不反复校时。
- 首次安装需要本地编译；窗口会显示三个阶段，请等到 `Installed successfully`。

面向 Windows 10/11 桌面系统，生成 AnyCPU 程序。已测试当前电脑的 64 位与 32 位 CLR；
未在第二台实体电脑和 ARM64 实机测试，不承诺所有历史 Windows 或受限企业环境一键可用。
详细安装、卸载与兼容说明见 [Windows 使用说明](windows/README.md)，实测范围见 [验证记录](docs/VALIDATION.md)。

## 接线

| OLED / 调试器 | STM32 |
|---|---|
| OLED SDA | PB10 |
| OLED SCK / SCL | PB11 |
| OLED VCC | 3.3 V（按模块额定供电） |
| OLED GND | GND |
| ST-Link SWDIO | PA13 |
| ST-Link SWCLK | PA14 |
| ST-Link GND | GND |

采用软件 I²C，按照 SDA=PB10、SCL=PB11 驱动，自动探测 `0x3C` / `0x3D`。
OLED 为 128×32，显示日期和 `HH:MM:SS`。`BJT` 表示北京时间，左下角 `L` / `H` 表示 RTC 时钟源。
USB-C 数据线使用 MCU 的 PA11(D-) / PA12(D+)；仅供电接口不能传输时间。

## 固件与走钟

优先用 32.768 kHz LSE 晶振驱动硬件 RTC；5 秒内未就绪时后备使用 8 MHz HSE /128 /62500。
不使用 OLED 刷新延时计秒。系统保存 UTC，显示时加 8 小时，支持闰年、跨日、跨月、跨年。
校时包含毫秒及分频器相位处理，运行中校时不停 CPU、不重复烧录 Flash。

完全断电且无 VBAT 后备电源时，时间会丢失；下次接电脑自动重新校时。
复位保留有效 RTC，不将“最后保存时间”冒充断电后的当前时间。

当前板有按芯片 UID 匹配的初步硬件频率校准：`CAL=77`，
用于补偿本机参考下测得的约 73.5 ppm 快偏。温度变化后误差仍可能改变；
121 秒校准后检查的相对偏差约 4 ms，不能据此保证长期零误差。
原理参考 [ST AN2604](https://www.st.com/resource/en/application_note/an2604-stm32f101xx-and-stm32f103xx-rtc-calibration-stmicroelectronics.pdf)。
开源 RTC 保时实现可参考 [STM32duino/STM32RTC](https://github.com/stm32duino/STM32RTC)。

## 开发与构建

发布的固件在 `dist/firmware/clock.hex` 和 `clock.bin`，源码在 `firmware/`。
Windows 端源码在 `windows/BeijingClockSync.cs`，单文件 CMD 可完整重建：

```powershell
python tools/build_windows_package.py
python tools/test_windows_package.py
```

构建安装包只用 Python 标准库；最终用户不需要 Python。
Windows 工具用系统自带 .NET 编译，未捆绑第三方 Python 运行环境。

固件构建需要 STM32CubeIDE 的 ARM GCC 或 PATH 中的 `arm-none-eabi-gcc`：

```powershell
python tools/build.py
python tools/flash.py
python tools/stlink_clock.py --sync --verify 30
```

`tools/flash.py` 通过 ST-Link 烧录并校时。仅 USB 校时不需要 ST-Link、CubeIDE 或开发工具。
固件限定 64 KB Flash、20 KB RAM。libopencm3 的源码与预编译库保存在 `vendor/libopencm3-clock`，许可证保留。
重新标定本块板可用 `python tools/calibrate.py --seconds 300`，然后重建固件并烧录。

Windows 程序通过 SetupAPI 只枚举 `1209:B103` 设备，必须收到 `BJT1` 应答才写时间。
该 VID/PID 是此原型的识别值，量产应使用正式分配的标识。
旧 Python 校时脚本保留给开发调试，一键安装包不依赖它。

## 许可证

本项目自有代码为 MIT。libopencm3 保留原 LGPL/GPL 许可证，见 [第三方说明](vendor/README.md)。