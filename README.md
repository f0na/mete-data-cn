# mete-data-cn

《mete》使用的 FGO 国服（CN）从者数据包。

数据按从者拆分存放，发布时由脚本合并成单个 JSON 数组，并作为 GitHub Release 资产提供下载。

## 仓库结构

```
servants/<id>.json    # 每个从者一个 Servant 对象，文件名即从者 id
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
    "servant_count": 1,
    "servant_ids": [800100],
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
- `Noble`：`name`、`icon`、`card`、`rank`、`type`、`strength`、`effect`、`effects[]`
- `Effect`：`effect`、`kind`、`values[]`、`script[]`、`target`

图片字段均为 Atlas Academy CDN 外链，仓库不打包图片。

## 更新数据

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

数据来自 [Atlas Academy](https://atlasacademy.io)（国服）。角色与图片版权归 TYPE-MOON / Aniplex 等原权利方所有，本仓库仅供学习与非商业用途。
