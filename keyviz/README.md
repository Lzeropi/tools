# keyviz — KDE Wayland 实时按键显示浮窗

录屏教学 / 快捷键演示用的按键可视化工具：按键按下即在屏幕底部浮现键帽组合，全部松开后保持 2.5 秒再淡出。单文件 Python 脚本，零编译。

## 为什么写它

KDE Plasma Wayland 会话下**没有可用的按键可视化工具**：

| 现有方案 | 问题 |
|---|---|
| screenkey | 纯 X11（XRecord），Wayland 下原生应用按键不可见 |
| key-mon | AUR 包过时，无实时组合键模式 |
| input-visualizer | AUR 中不存在 |

本工具直读内核输入层（evdev），与显示服务器无关，Wayland / X11 通用。

## 特性

- 按下即显示，组合实时更新（Ctrl + C 式键帽条，底部居中）
- keyviz 语义：松开任一键后组合保持不变，全部松手冻结 2.5s → 0.3s 渐隐
- 修饰键固定排序：Ctrl → Alt → Super → Shift，深色键帽高亮
- 标点键显示真实字符（`. , / ; ' - = [ ] \`）
- `--mouse` 模式：鼠标按键以图标键帽参与组合（左/右键半边高亮、中键、侧键、滚轮箭头）
- 单文件 ~370 行，无构建、无多余依赖

## 依赖与安装

```bash
# Arch Linux
sudo pacman -S python-evdev python-pyqt5
```

其余发行版安装对应 Python 包 `evdev` 与 `PyQt5` 即可。

## 用法

```bash
sudo python3 keyviz.py          # 仅键盘
sudo python3 keyviz.py --mouse  # 键盘 + 鼠标指示
```

> 读取 `/dev/input/event*` 需要 root 权限，或把用户加入 `input` 组后免 sudo：
> `sudo usermod -aG input $USER`（注销重登生效）。

## 退出

- 在启动它的终端按 `Ctrl+C`（前台运行，浮窗立即消失）
- 原终端已关闭时，另开终端执行 `sudo pkill -f keyviz.py`
  （工具以 root 运行，pkill 不加 sudo 会报 `Operation not permitted`）
- 确认已退出：`pgrep -f keyviz.py`，无任何输出即已结束

## 可调参数

脚本头部集中定义：

| 参数 | 默认 | 说明 |
|---|---|---|
| `HOLD_MS` | 2500 | 全部松开后组合保持时长（毫秒） |
| `FADE_MS` | 300 | 渐隐动画时长 |
| `FONT_SIZE` | 24 | 键帽字号 |
| `BOTTOM_MARGIN` | 56 | 距屏幕底边距离（px） |

键帽配色见 `CAP_STYLE` 字典。

## 原理

```
/dev/input/event* ──evdev──▶ 事件线程（select 多路读）
                                   │ queue
                                   ▼
                              PyQt5 主线程 30ms 轮询
                                   │
                    无边框置顶半透明浮窗（QSS 键帽 + 渐隐动画）
```

- 键盘 / 鼠标设备通过 capabilities 自动识别（`is_keyboard` / `is_mouse`）
- 鼠标图标由 QPainter 自绘：半截鼠标轮廓 + 左右键半边高亮 + 侧键块 + 滚轮箭头

## 致谢

显示风格灵感来自 [mulaRahul/keyviz](https://github.com/mulaRahul/keyviz)（组合键保持/冻结语义），
代码为本项目从零实现，无代码引用。

## 许可

MIT

> AI生成
