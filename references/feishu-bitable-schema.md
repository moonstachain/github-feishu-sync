# Feishu Bitable Schema

Use this reference when validating or explaining the Feishu storage model for `github-feishu-sync`.

## Tables

- `GitHub仓库总表`
- `Skill Pattern子表`

## Stable Keys

- master table stable key: `完整名称`
- child table stable key: `来源仓库`

These keys must be used for upsert. Repeated sync runs should update existing rows instead of creating duplicates.

## Master Table Fields

- `仓库名`
- `完整名称`
- `可见性`
- `是否私有`
- `是否Fork`
- `主要语言`
- `仓库说明`
- `仓库主页`
- `一键安装链接`
- `是否Skill Pattern`
- `Pattern类型`
- `Pattern置信度`
- `Skill名称`
- `Skill摘要`
- `适用场景`
- `入口文件/结构`
- `是否含SKILL.md`
- `是否含agents配置`
- `是否安装就绪`
- `最近更新时间`
- `本次扫描时间`
- `备注`

## Child Table Fields

- `Skill名称`
- `来源仓库`
- `Pattern类型`
- `结构化说明`
- `适用场景`
- `一键安装链接`
- `仓库主页`
- `是否标准Skill`
- `安装就绪`
- `置信度`
- `最近更新时间`
- `扫描时间`
- `补充备注`

## Behavior Rules

- Every scanned repo should be written into `GitHub仓库总表`.
- Only rows with `pattern_type != not_skill_pattern` should be written into `Skill Pattern子表`.
- The default v1 policy is update-or-create only.
- Delete events should trigger a rescan, not automatic record deletion.
