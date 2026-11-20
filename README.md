# mete-data-cn

《mete》使用的 FGO 国服（CN）从者数据包。

数据按从者拆分存放，发布时由脚本合并成单个 JSON 数组，并作为 GitHub Release 资产提供下载。

## 仓库结构

```
servants/<id>.json    # 每个从者一个 Servant 对象，文件名即从者 id
scripts/fetch.py      # 从 Atlas 导出转换并补齐 servants/<id>.json
scripts/split.py      # 一次性拆分脚本（已执行，保留用于追溯）
scripts/build.py      # 校验 + 合并 + 生成 manifest + 打包 zip
.github/workflows/    # JSON 校验与 Release 发布
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
| `manifest.json` | 版本、生成时间、从者数量、id 列表、文件大小与 SHA-256 |

`manifest.json` 示例：

```json
{
    "version": "data-2026.11.18",
    "generated_at": "2026-11-18T06:30:00Z",
    "servant_count": 447,
    "servant_ids": [100100, 100200, 800100, 3300100],
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
  - `assets`：`chara_graph`、`faces`、`narrow_figure`、`command`、`status`
- `Skill`：`slot`、`name`、`icon`、`strength`、`switch_cond`（可选）、`cool_down[]`、`effect`、`effects[]`、`target`
- `Noble`：`name`、`icon`、`card`、`rank`、`type`、`strength`、`switch_cond`（可选）、`effect`、`effects[]`

`switch_cond` 表示该技能/宝具只在特定状态下生效（如 `普通时`、`圣剑装填时`、`苍崎青子时`），
同一槽位/同名宝具可以有多条带不同 `switch_cond` 的记录。再临阶段变化则直接拆分到对应 `spirits`。

同一技能/宝具的强化前后版本会同时保留，用 `strength` 区分：`0` 为强化前，`1` 为强化后；
强化版本从 Mooncell 标注的开放阶段开始出现。
- `Effect`：`effect`、`kind`、`values[]`、`script[]`、`target`

图片字段均为 Atlas Academy CDN 外链，仓库不打包图片。

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
```

转换规则：

- 只保留可玩从者（`type` 为 `normal` / `heroine`，且有正式图鉴编号）
- 按灵基再临阶段和已实装灵衣拆分为 `spirits`
- 跳过剧情 NPC、敌方单位和客户端职阶枚举不支持的单位
- 百分比类数值统一为百分比 ×100（如 20% → `2000`），固定值保持原样
- 技能、职阶技能、宝具的数值取自 Mooncell
- 技能/宝具按 Mooncell 的再临形态分组，灵基阶段只包含该阶段已解锁的技能与宝具
- 强化技能/宝具在 Mooncell 标注的开放阶段之后才出现，并用 `strength` 标记

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
   git tag data-2026.11.18
   git push origin data-2026.11.18
   ```

CI 会校验全部 JSON、合并成 `servant.json`、生成 `manifest.json`，发布 `mete-data-cn.zip` 与 `manifest.json` 两个资产。

本地校验（不写文件）：

```bash
python scripts/build.py --version test --check
```

本地完整构建（产物在 `dist/`）：

```bash
python scripts/build.py --version test
```

## 数据来源

数据来自 [Atlas Academy](https://atlasacademy.io)（国服）与 [Mooncell](https://fgo.wiki)。角色与图片版权归 TYPE-MOON / Aniplex 等原权利方所有，本仓库仅供学习与非商业用途。
