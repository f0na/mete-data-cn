# mete-data-cn

《mete》使用的 FGO 国服（CN）从者数据包。

数据按从者拆分存放，发布时由脚本合并成单个 JSON 数组，连同图片资源打包为 GitHub Release 资产。

## 仓库结构

```
servants/<id>.json    # 每个从者一个 Servant 对象，文件名即从者 id
scripts/fetch.py      # 从 Atlas 导出转换并补齐 servants/<id>.json
scripts/assets.py     # 下载图片到本地缓存 images/（不入库）
scripts/split.py      # 一次性拆分脚本（已执行，保留用于追溯）
scripts/build.py      # 校验 + 合并 + 图片打包 + 生成 manifest
.github/workflows/    # JSON 校验与 Release 发布
images/               # 本地图片缓存（不入库，发版时打进 zip）
dist/                 # 构建产物（不入库）
```

## 获取数据

固定下载地址（始终指向最新正式 Release）：

- 清单（体积小，建议先取它检查版本 / 哈希）：
  `https://github.com/f0na/mete-data-cn/releases/latest/download/manifest.json`
- 数据包 zip：
  `https://github.com/f0na/mete-data-cn/releases/latest/download/mete-data-cn.zip`

zip 内包含：

| 文件 | 说明 |
| --- | --- |
| `servant.json` | 合并后的顶层数组，可直接按 `Servant[]` 反序列化 |
| `manifest.json` | 版本、生成时间、图片根目录、文件大小与 SHA-256 |
| `images/` | 从者图片资源，JSON 中的图片路径即相对于此目录 |

`manifest.json` 示例：

```json
{
    "version": "data-2026.11.20",
    "generated_at": "2026-11-18T06:30:00Z",
    "assets": {
        "root": "images"
    },
    "files": [
        {
            "name": "servant.json",
            "bytes": 145295,
            "sha256": "..."
        }
    ]
}
```

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

## 图片资源

**图片不进入 git 仓库。** 构建时由 `scripts/assets.py` 从 Atlas Academy / Mooncell
下载到本地 `images/`（已 gitignore），`scripts/build.py` 再把它们打进 Release 资源包：

```
mete-data-cn.zip
├── servant.json
├── manifest.json
└── images/                     # 如 images/CN/CharaGraph/100100/100100a@1.png
```

JSON 中的图片字段存的是相对路径，与 zip 内的 `images/` 一一对应：

```json
"assets": {
    "chara_graph": "CN/CharaGraph/100100/100100a@1.png",
    "faces": "CN/Faces/f_1001000.png"
}
```

客户端解析规则：`<解压目录>/<manifest.assets.root>/<路径>`，即
`<zip>/images/CN/CharaGraph/100100/100100a@1.png`。

`scripts/fetch.py` 会自动下载新增从者的图片；也可以单独同步：

```bash
# 下载缺失图片（已存在的会跳过）
python scripts/assets.py

# 只检查图片是否齐全，不下载
python scripts/assets.py --check

# 只把 JSON 里的旧 URL 转成路径，不下载
python scripts/assets.py --no-download
```

> `data-*` 标签发布时，CI 会先下载图片再打包。

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

# 只写入资源路径，不下载图片
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
- 图片会下载到本地 `images/`（不入库），JSON 中写入相对路径

### 手动新增或修改

1. 新增或修改 `servants/<id>.json`（文件名必须等于该文件的 `id`）。
2. 提交并推送：
   ```bash
   git add servants
   git commit -m "Update servant data"
   git push
   ```
3. 打 tag 并推送，触发 Release：
   ```bash
   git tag data-2026.11.20
   git push origin data-2026.11.20
   ```

CI 会先下载图片，再校验全部 JSON、合并成 `servant.json`、生成 `manifest.json`，
发布 `mete-data-cn.zip`（含 `images/`）与 `manifest.json` 两个资产。

本地校验（不写文件；加 `--check-images` 同时检查图片是否齐全）：

```bash
python scripts/build.py --version test --check
```

本地完整构建（产物在 `dist/`，需要先下载图片）：

```bash
python scripts/assets.py
python scripts/build.py --version test
```

只构建数据包、不打包图片：

```bash
python scripts/build.py --version test --no-images
```

## 数据来源

数据来自 [Atlas Academy](https://atlasacademy.io)（国服）与 [Mooncell](https://fgo.wiki)；
图片不随 git 仓库分发，随 Release 资源包提供。角色与图片版权归 TYPE-MOON / Aniplex 等
原权利方所有，本仓库仅供学习与非商业用途。
