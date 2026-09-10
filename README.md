# BiggerSpeed

一个给 Garmin Edge 码表用的 Connect IQ 数据字段（Data Field），用「左右分栏」的大字速度显示 + 「热到冷」的速度分区变色，让你一眼看清实时速度和所处速度区间。

支持设备：**Edge 840 / Edge 540**（均为 246×322 分辨率）。

## 显示布局

| 位置 | 内容 |
|------|------|
| 左半 | 实时速度整数（个位十位），超大显示，右对齐贴中线 |
| 右上 | 平均速度（无单位） |
| 右下 | 实时速度小数位 + 单位（如 `.5 km/h`） |

## 颜色分区（热到冷）

整格背景随当前速度区间变色，默认 7 档：

| 区间 (km/h) | 颜色 |
|------|------|
| 0-10 | 红 |
| 10-20 | 橙 |
| 20-30 | 黄 |
| 30-40 | 绿 |
| 40-50 | 青 |
| 50-60 | 蓝 |
| 60+ | 紫 |

文字颜色自适应：浅色背景用深字、深色背景用白字，任何区间都清晰可读。

## 自定义速度区间

6 个区间分界阈值（对应上表 7 档的边界）可以在码表上直接改，不用重新编译：

**骑行活动 → 数据页 → 长按该数据字段 → 进入设置 → Connect IQ 设置**

| 设置项 | 含义 | 默认 |
|--------|------|------|
| Zone 1 max | 第 1 档（红）上限 | 10 |
| Zone 2 max | 第 2 档（橙）上限 | 20 |
| Zone 3 max | 第 3 档（黄）上限 | 30 |
| Zone 4 max | 第 4 档（绿）上限 | 40 |
| Zone 5 max | 第 5 档（青）上限 | 50 |
| Zone 6 max | 第 6 档（蓝）上限 | 60 |

第 7 档（紫）自动覆盖 60 以上。阈值单位跟随码表当前单位（公制 km/h / 英制 mph）。

实现：`resources/settings/properties.xml` 定义属性默认值，`resources/settings/settings.xml` 定义设置 UI，源码 `View.mc` 里用 `Application.Properties.getValue()` 读取。

## 技术要点

- 语言：Monkey C（Garmin Connect IQ SDK）
- 类型：`WatchUi.DataField`（复杂数据字段，自定义 `onUpdate` 绘制）
- 单位自适应：公制 `km/h`，英制 `mph`
- 单位自适应：坡度 `%`，海拔 `m`（英制 `ft`）
- 坡度算法（α-β 滤波 + 垂直速度 + 双尺度融合，见下方）
- 底部对齐：`Graphics.getFontAscent/Descent` 按 baseline 对齐

## 坡度算法（α-β 垂直速度法）

对比传统"窗口差分求坡度"（等一段距离后算高度差，天然滞后半个窗口），本项目采用**实时估计垂直速度**的方式，响应更快：

```
海拔 h ──→ α-β 滤波 ──→ 垂直速度 dh/dt
                         │
水平速度 v ──────────────┤
                         ↓
                坡度% ≈ (dh/dt) / v × 100
```

- **α-β 滤波**维护状态 `[估计高度 ĥ, 垂直速度 vh]`，每帧 预测→更新，用残差修正 vh，不依赖"等窗口满"
- **坡度%** = `(vh / v) × 100`，即垂直速度除以水平速度（等价 Δalt/Δdist，但无需累积窗口）
- **双尺度融合**：快速坡度（α-β 的 vh，跟手）× 0.7 + 慢速坡度（段累计，稳定）× 0.3，既快又稳
- **起步阈值**防挡，**距离过短**（<1m/帧）忽略防除零

## 背景（跟随码表主题）

- **白天模式**：浅色背景（off-white），坡度数字用**加深版环法色**（琥珀/深橙/深红/深紫），中性文字深灰，海拔中灰
- **夜间模式**：黑色背景，坡度数字用**原版亮环法色**（黄/橙/红/紫），中性文字白，海拔浅灰

实现：`System.getDeviceSettings().isNightModeEnabled` 自动检测（运行时 `has :isNightModeEnabled` 守卫），`applyTheme()` 每帧切换整套配色，运行中切夜间模式即生效。白天浅底上黄色必须加深（`#FFFF00` 在浅底看不见），故昼夜两套环法色。

「坡度平滑」设置项三档映射到 α-β 响应参数：快速=高 β（更跟手）/ 平衡 / 平滑=低 β（更稳）。

## 项目结构

```
BiggerSpeed/
├── manifest.xml              # 应用清单（声明 Edge 840 / 540）
├── monkey.jungle             # 编译入口
├── source/
│   ├── App.mc                # 应用入口
│   └── View.mc               # 核心逻辑与绘制
├── resources/
│   ├── drawables/            # 图标
│   ├── settings/             # 自定义设置（速度区间阈值）
│   │   ├── properties.xml    # 属性默认值
│   │   └── settings.xml      # 设置 UI 定义
│   └── strings/              # 应用名 + 设置项标题
└── make_test_fit.py          # 生成测试 FIT（7 档各 10 秒递增）
```

## 编译

### 前置条件

1. 安装 Connect IQ SDK（本仓库基于 9.2.0）
2. 通过 SDK Manager 下载 Edge 840 / 540 设备数据
3. 生成开发者密钥 `developer_key.der`（VS Code Monkey C 插件生成）

### 编译命令

```bash
monkeyc -o BiggerSpeed-edge840.prg -y ~/Garmin/developer_key -f monkey.jungle -d edge840 -w
monkeyc -o BiggerSpeed-edge540.prg -y ~/Garmin/developer_key -f monkey.jungle -d edge540 -w
```

## 测试

生成 7 档速度递增的测试 FIT（每档 10 秒，5→65 km/h）：

```bash
python3 make_test_fit.py
```

在模拟器里回放该 FIT，即可看到背景依次走过红橙黄绿青蓝紫 7 档。

## 安装到码表

1. 码表 USB 连电脑（Edge 840 是 MTP 设备，Mac 需 OpenMTP / Android File Transfer 等工具）
2. 将对应设备的 `.prg` 复制到 `GARMIN/Apps/`
3. 断开 USB 重启码表
4. 骑行活动 → 数据页 → 添加数据字段 → Connect IQ → 选 BiggerSpeed

## License

MIT
