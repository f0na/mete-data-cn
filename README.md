# mete-data-cn

《mete》使用的 FGO 国服（CN）游戏数据包，包含从者、概念礼装、御主礼装与指令纹章。

数据按 id 拆分存放。发布时 JSON 合并进一个数据包，图片则按数据集分别打成资源包：
从者、礼装、御主礼装、指令纹章各一个资源包，客户端可以只下载需要的部分。

## 仓库结构

```
servants/<id>.json        # 每个从者一个 Servant 对象，文件名即从者 id
crafts/<id>.json          # 每个概念礼装一个对象
mystic/<id>.json          # 每个御主礼装一个对象
cmdcodes/<id>.json        # 每个指令纹章一个对象
asset_sources.json        # 本地资源路径 → 源 URL 的显式映射（入库）
scripts/fetch.py          # 从 Atlas 导出转换并补齐 servants/<id>.json
scripts/fetch_crafts.py   # 转换 crafts/<id>.json
scripts/fetch_mystic.py   # 转换 mystic/<id>.json
scripts/fetch_cmdcodes.py # 转换 cmdcodes/<id>.json
scripts/dataset_assets.py # 各数据集 Atlas URL → 本地资源路径的映射规则
scripts/assets.py         # 按 asset_sources.json 下载全部资源到 assets/（不入库）
scripts/version.py        # 解析 / 校验 data-YYYY.MM.DD[.NNN] 版本号
scripts/migrate_assets.py # 一次性目录迁移脚本（已执行，保留用于追溯）
scripts/split.py          # 一次性拆分脚本（已执行，保留用于追溯）
scripts/build.py          # 校验 + 合并 + 数据包 / 分类型资源包构建 + 生成 manifest
.github/workflows/        # JSON 校验与 Release 发布
assets/                   # 本地资源缓存（不入库，发版时打进资源包）
dist/                     # 构建产物（不入库）
```

## 获取数据

固定下载地址（始终指向最新正式 Release）：

- 清单（体积小，建议先取它检查版本 / 哈希）：
  `https://github.com/f0na/mete-data-cn/releases/latest/download/manifest.json`
- 数据包 zip（全部 JSON）：
  `https://github.com/f0na/mete-data-cn/releases/latest/download/mete-data-cn.zip`
- 资源包 zip（按数据集拆分）：
  - 从者图与技能图标（约 1.6 GB）：`mete-data-cn-servant.zip`
  - 概念礼装图与技能图标：`mete-data-cn-craft.zip`
  - 御主礼装图与技能图标：`mete-data-cn-mystic.zip`
  - 指令纹章图与技能图标：`mete-data-cn-cmdcode.zip`

数据包 `mete-data-cn.zip` 内包含：

| 文件 | 说明 |
| --- | --- |
| `servant.json` | 合并后的顶层数组，可直接按 `Servant[]` 反序列化 |
| `craft.json` | 合并后的概念礼装数组 |
| `mystic.json` | 合并后的御主礼装数组 |
| `cmdcode.json` | 合并后的指令纹章数组 |
| `manifest.json` | 版本、生成时间、各 JSON 与各资源包的文件名 / 大小 / SHA-256 |

每个资源包解压后的根目录直接是它自己的资源目录，不带 `assets/` 或 `images/` 包装层：

| 资源包 | 根目录 |
| --- | --- |
| `mete-data-cn-servant.zip` | `Servant/`、`SkillIcons/` |
| `mete-data-cn-craft.zip` | `Craft/` |
| `mete-data-cn-mystic.zip` | `Mystic/` |
| `mete-data-cn-cmdcode.zip` | `Cmdcodes/` |

`manifest.json` 示例：

```json
{
    "version": "data-2026.11.26.001",
    "generated_at": "2026-11-26T07:27:31Z",
    "base": "2026.11.26",
    "patch": 1,
    "revision": 20261126001,
    "resources": {
        "servant": {
            "root": ".",
            "archive": "mete-data-cn-servant.zip",
            "bytes": 1604104974,
            "sha256": "...",
            "patches": [
                {"from": 0, "to": 1, "archive": "patch-2026.11.26-000-001.zip", "bytes": 0, "sha256": "..."}
            ]
        },
        "craft": {
            "root": ".",
            "archive": "mete-data-cn-craft.zip",
            "bytes": 0,
            "sha256": "..."
        },
        "mystic": {"root": ".", "archive": "mete-data-cn-mystic.zip", "bytes": 0, "sha256": "..."},
        "cmdcode": {"root": ".", "archive": "mete-data-cn-cmdcode.zip", "bytes": 0, "sha256": "..."}
    },
    "assets": {
        "root": ".",
        "archive": "mete-data-cn-servant.zip",
        "bytes": 1604104974,
        "sha256": "..."
    },
    "files": [
        {"name": "servant.json", "bytes": 25442259, "sha256": "..."},
        {"name": "craft.json", "bytes": 2794093, "sha256": "..."},
        {"name": "mystic.json", "bytes": 109288, "sha256": "..."},
        {"name": "cmdcode.json", "bytes": 176369, "sha256": "..."}
    ],
    "patches": [
        {"from": 0, "to": 1, "archive": "patch-2026.11.26-000-001.zip", "bytes": 0, "sha256": "..."}
    ]
}
```

`resources` 按数据集列出资源包与增量补丁。顶层 `assets` / `patches` 仍然只表示从者资源包，
用于兼容旧客户端；新客户端应读取 `resources`。

> `/releases/latest/` 只匹配非草稿、非预发布的最新 Release。

## 数据格式

`servants/<id>.json` 是一个 `Servant` 对象：

- `id`、`no`、`class`、`cards[]`、`append_skills[]`
- `spirits[]`：各灵基阶段的 `BaseServant`
  - 基础：`spirit`、`name`、`battle_name`、`gender`、`attr1`、`attr2`、`sub_attr`、`cost`、`rarity`
  - `skills[]`、`class_skills[]`、`nobles[]`
  - `assets`：`chara_graph`、`faces`、`narrow_figure`、`command`、`status`，值为图片相对路径
- `Skill`：`slot`、`name`、`icon`、`strength`、`switch_cond`（可选）、`cool_down[]`、`effect`、`effects[]`、`target`
- `Noble`：`name`、`icon`、`card`、`rank`、`type`、`strength`、`switch_cond`（可选）、`effect`、`effects[]`

`switch_cond` 表示该技能/宝具只在特定状态下生效（如 `普通时`、`圣剑装填时`、`苍崎青子时`），
同一槽位/同名宝具可以有多条带不同 `switch_cond` 的记录。再临阶段变化则直接拆分到对应 `spirits`。

同一技能/宝具的强化前后版本会同时保留，用 `strength` 区分：`0` 为强化前，`1` 为强化后；
强化版本从 Mooncell 标注的开放阶段开始出现。
- `Effect`：`effect`、`kind`、`values[]`、`script[]`、`target`

### 概念礼装 `crafts/<id>.json`

- 基础：`id`、`name`、`type`、`rarity`、`cost`、`atk`、`hp`
- `skills[]`：`name`、`icon`、`effect`；包含基础、最大解放以及事件限定效果
  （`groupOverwrites` 会展开成相邻的同名技能）
- `assets`：`chara_graph[]`、`faces[]`、`narrow_figure[]`，值为本地图片路径；
  部分情人节礼装的男性立绘会追加到同一数组

### 御主礼装 `mystic/<id>.json`

- 基础：`id`、`name`、`shortName`
- `skills[]`：`name`、`icon`、`effect`、`cool_down[]`、`target`、`effects[]`
  - `effects` 与从者技能同构；`cool_down` 按等级去重
- `assets`：`item`、`costumes`，各自包含 `male` / `female` 图片路径

### 指令纹章 `cmdcodes/<id>.json`

- 基础：`id`、`name`、`rarity`
- `assets`：`chara_graph`、`faces`，值为本地图片路径
- `skills[]`：`name`、`icon`、`effect`
- `comment`：游戏内说明文本

## 图片资源

**图片不进入 git 仓库。** 本地缓存目录是 `assets/`（已 gitignore），
`scripts/assets.py` 按 `asset_sources.json` 记录的源 URL 下载；
`scripts/build.py` 把它们按数据集打进各自的资源包：

```
mete-data-cn-servant.zip
├── Servant/
│   ├── CharaGraph/100100/100100a@1.png
│   ├── Faces/f_1001000.png
│   ├── NarrowFigure/100100/100100@0.png
│   ├── Commands/100100/card_servant_1.png
│   └── Status/100100/status_servant_1.png
└── SkillIcons/
    ├── skill_00100.png
    ├── 己阵防御.png
    └── 宝具威力提升.png

mete-data-cn-craft.zip
└── Craft/
    ├── CharaGraph/9408800/9408800a.png
    ├── Faces/f_94088000.png
    ├── EquipFaces/f_94088000.png
    └── SkillIcons/skill_00205.png

mete-data-cn-mystic.zip
└── Mystic/
    ├── Items/masterequip00001.png
    └── SkillIcons/skill_00600.png

mete-data-cn-cmdcode.zip
└── Cmdcodes/
    ├── CommandGraph/8402120a.png
    ├── CommandCodes/c_8402120.png
    └── SkillIcons/skill_00527.png
```

JSON 中的图片字段存的是相对 `assets/` 的路径，与对应资源包内的条目一一对应：

```json
"assets": {
    "chara_graph": "Servant/CharaGraph/100100/100100a@1.png",
    "faces": "Servant/Faces/f_1001000.png"
}
```

客户端解析规则：`<安装目录>/<manifest.resources.<dataset>.root>/<路径>`。当前
`root` 为 `"."`，即 `<安装目录>/Servant/CharaGraph/...` 或 `<安装目录>/Craft/...`。

### 资源来源映射

`asset_sources.json` 记录每个本地路径对应的原始下载地址，下载时只查这张表，
**不再从本地路径反推 URL**。缺少条目会直接报错，而不是猜一个地址。

- `scripts/fetch.py` 在把 Atlas / Mooncell URL 转成本地路径时会自动写入映射。
- `scripts/fetch_crafts.py` / `fetch_mystic.py` / `fetch_cmdcodes.py` 通过
  `scripts/dataset_assets.py` 的规则，把 Atlas URL 写入各自资源根目录并记录映射。
- 手工新增资源时，需要同时补充 `asset_sources.json` 的条目。
- 两张 Mooncell 技能图标（`己阵防御.png`、`宝具威力提升.png`）平铺在
  `SkillIcons/` 下，靠映射表指回 `media.fgo.wiki` 的原始路径。

`scripts/assets.py` 默认同步全部数据集，也可以用 `--dataset` 只同步一类：

```bash
# 下载缺失图片（已存在的会跳过）
python scripts/assets.py

# 只处理一个数据集
python scripts/assets.py --dataset crafts

# 只检查图片是否齐全、映射是否完整，不下载
python scripts/assets.py --check
```

> `data-*` 标签发布时，CI 会先下载全部资源再按数据集打包。

## 更新数据

### 从 Atlas / Mooncell 批量拉取

`scripts/fetch.py` 会读取国服 `nice_servant_lore` 导出，转换成 `servants/<id>.json`；
同时从 [Mooncell](https://fgo.wiki) 抓取从者页面。技能、职阶技能、宝具的数值，以及
各再临形态对应的技能/宝具，均以 Mooncell 为准。默认只补齐缺失的从者，不会覆盖已有文件：

```bash
# 直接下载导出（约 86 MB，下载到系统临时目录）
python scripts/fetch.py

# 使用已经下载好的导出文件
python scripts/fetch.py --source /path/to/nice_servant_lore.json

# 覆盖已有从者文件
python scripts/fetch.py --source /path/to/nice_servant_lore.json --overwrite

# 只转换指定从者
python scripts/fetch.py --source /path/to/nice_servant_lore.json --ids 100100 100200

# 不访问 Mooncell，只使用 Atlas 数据
python scripts/fetch.py --source /path/to/nice_servant_lore.json --no-mooncell

# 指定 Mooncell 页面缓存目录 / 强制重新抓取
python scripts/fetch.py --mooncell-cache /path/to/cache --refresh-mooncell

# 只记录资源映射，不下载图片
python scripts/fetch.py --source /path/to/nice_servant_lore.json --no-assets
```

转换规则：

- 只保留可玩从者（`type` 为 `normal` / `heroine`，且有正式图鉴编号）
- 按灵基再临阶段和已实装灵衣拆分为 `spirits`
- 跳过剧情 NPC、敌方单位和客户端职阶枚举不支持的单位
- 百分比类数值统一为百分比 ×100（如 20% → `2000`），固定值保持原样
- 技能、职阶技能、宝具的数值取自 Mooncell
- 技能/宝具按 Mooncell 的再临形态分组，灵基阶段只包含该阶段已解锁的技能与宝具
- 强化技能/宝具在 Mooncell 标注的开放阶段之后才出现，并用 `strength` 标记
- 图片会下载到本地 `assets/`（不入库），JSON 中写入相对路径，同时把源 URL 记录到 `asset_sources.json`

### 礼装 / 御主礼装 / 指令纹章

三类数据各自读取 Atlas 的一个 CN 导出，默认只补齐缺失文件：

```bash
python scripts/fetch_crafts.py      # nice_equip.json       → crafts/
python scripts/fetch_mystic.py      # nice_mystic_code.json → mystic/
python scripts/fetch_cmdcodes.py    # nice_command_code.json → cmdcodes/

# 使用已下载的导出 / 覆盖已有文件
python scripts/fetch_crafts.py --source nice_equip.json --overwrite
python scripts/fetch_mystic.py --source nice_mystic_code.json --overwrite
python scripts/fetch_cmdcodes.py --source nice_command_code.json --overwrite
```

转换规则：

- 图片写入各自根目录（`Craft/`、`Mystic/`、`Cmdcodes/`），并把 Atlas URL 记录到 `asset_sources.json`
- 概念礼装的事件限定效果会展开为相邻的同名技能
- 御主礼装技能的效果数值复用从者的 `Effect` 转换逻辑
- `ptselectOneSub` / `ptselectSub`（如 Order Change）的目标标记为 `Special`

### 手动新增或修改

1. 新增或修改对应目录下的 `<id>.json`（文件名必须等于该文件的 `id`）。
2. 提交并推送：
   ```bash
   git add servants crafts mystic cmdcodes
   git commit -m "Update game data"
   git push
   ```
3. 打 tag 并推送，触发 Release：
   ```bash
   # 基座版本（首次发布或破坏性变更）
   git tag data-2026.11.26
   git push origin data-2026.11.26

   # 同一基座下的补丁版本
   git tag data-2026.11.26.001
   git push origin data-2026.11.26.001
   ```

CI 会先校验 tag，再下载资源、校验全部 JSON，合并成 `servant.json` / `craft.json` /
`mystic.json` / `cmdcode.json`，生成 `manifest.json`，并发布数据包、四个资源包、
`manifest.json` 以及各资源包的增量补丁。

本地校验（不写文件；加 `--check-images` 同时检查资源是否齐全）：

```bash
python scripts/build.py --version test --check --check-sources
```

本地完整构建（产物在 `dist/`，需要先下载资源）：

```bash
python scripts/assets.py
python scripts/build.py --version test
```

用真实补丁版本构建时，会同时生成增量补丁（需要本地已有对应的基座/上一补丁 tag）：

```bash
python scripts/build.py --version data-2026.11.27.001
python scripts/patches.py --version data-2026.11.27.001 --check   # 只看变更数量
```

只构建全量包、跳过补丁：

```bash
python scripts/build.py --version data-2026.11.27.001 --no-patches
```

只构建数据包、不打包资源：

```bash
python scripts/build.py --version test --no-images
```

## 版本号规则

版本 tag 分两级：

- 基座：`data-YYYY.MM.DD`，例如 `data-2026.11.26`
- 补丁：`data-YYYY.MM.DD.NNN`，NNN 为三位零填充，从 `001` 起，例如 `data-2026.11.26.001`

manifest 会同时写入派生字段：

| 字段 | 说明 |
| --- | --- |
| `base` | 基座日期，如 `2026.11.26` |
| `patch` | 补丁号，基座为 `0` |
| `revision` | 单调可比较的整数，`YYYYMMDD * 1000 + patch` |

规则：

- 同一基座内可以持续发布补丁；数据增量更新只在该基座内进行。
- 发生破坏性变更（目录布局、数据格式、资源包结构变化）时发布新基座，客户端按 `base`
  判断走全量下载。
- 补丁 tag 必须存在对应基座 tag，CI 会用 `scripts/version.py --check-base` 校验。
- 补丁按数据集分别生成，且**只增不删改**：只包含区间内新增的图片文件，不包含任何 JSON。
  JSON 包每次全量下载，不做 JSON 增量。
- 每个 release 为每个资源包同时发布两种补丁：

  | 补丁 | 命名 | 内容 |
  | --- | --- | --- |
  | 相邻增量 | `patch-<type>-<base>-<from:03d>-<to:03d>.zip` | 上一补丁到本补丁新增的文件 |
  | 基座累计 | `patch-<type>-<base>-000-<to:03d>.zip` | 基座以来所有新增文件 |

  从者资源包沿用旧命名 `patch-<base>-...`，其他类型带自己的前缀：

  ```
  patch-2026.11.27-003-007.zip          # 从者资源包
  patch-craft-2026.11.27-003-007.zip    # 礼装资源包
  ├── Craft/CharaGraph/...              # 003 → 007 新增的图片
  └── Craft/SkillIcons/...
  ```

  首个补丁（`001`）的累计与相邻补丁内容相同，只发一个；某类没有新增资源时仍会生成一个
  空补丁，让客户端明确知道无需全量下载。

  补丁包内没有 JSON，也没有删除或修改列表。客户端解压到对应资源目录即可，
  已有文件不受影响；落后多个版本时用累计包一次补齐。

  发布用的 `manifest.json` 会在 `resources.<dataset>.patches` 下分别列出可用补丁
  （起止补丁号、`archive`、`bytes`、`sha256`），客户端据此选择并校验。

## 数据来源

数据来自 [Atlas Academy](https://atlasacademy.io)（国服）与 [Mooncell](https://fgo.wiki)；
图片不随 git 仓库分发，随 Release 资源包提供。角色与图片版权归 TYPE-MOON / Aniplex 等
原权利方所有，本仓库仅供学习与非商业用途。
