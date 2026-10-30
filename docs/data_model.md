# RecallWeaver 数据字典

本文档对应 `schema.sql` 与 `src/recallweaver/migrations/0001_init.sql` 中的 SQLite 结构。SQLite 使用动态类型系统；下表中的类型是 schema 声明类型。标注“可空”表示 schema 未声明 `NOT NULL`，即使业务代码通常会提供值。

## 1. 通用约定

- ID 字段使用 `TEXT` 保存 UUID 或稳定标识；时间字段使用 `INTEGER` 保存 Unix 秒级时间戳。
- 外键约束由每个数据库连接上的 `PRAGMA foreign_keys = ON` 启用。
- `DEFAULT` 是数据库缺省值，不自动意味着 `NOT NULL`。
- `ON DELETE CASCADE` 表示父记录删除时同步删除从属记录；`ON DELETE SET NULL` 表示保留从属记录但解除来源关联。

## 2. `tenants`：租户

| 字段 | 类型 | 约束 / 默认值 | 业务含义 |
|---|---|---|---|
| `id` | TEXT | 主键 | 租户唯一标识；当前公开写入 API 使用 `default`。 |
| `name` | TEXT | 非空 | 租户显示名称。 |
| `created_at` | INTEGER | 非空 | 租户创建时间。 |

## 3. `episodes`：原始事件或对话来源

| 字段 | 类型 | 约束 / 默认值 | 业务含义 |
|---|---|---|---|
| `id` | TEXT | 主键 | 事件记录唯一标识。 |
| `tenant_id` | TEXT | 非空；外键 `tenants(id)`，删除租户时级联删除 | 所属租户。 |
| `raw_content` | TEXT | 非空 | 原始对话或事件正文。 |
| `created_at` | INTEGER | 非空 | 来源事件创建时间。 |

## 4. `memories`：记忆主表

| 字段 | 类型 | 约束 / 默认值 | 业务含义 |
|---|---|---|---|
| `id` | TEXT | 主键 | 记忆唯一标识。 |
| `tenant_id` | TEXT | 非空；外键 `tenants(id)`，删除租户时级联删除 | 所属租户。 |
| `content` | TEXT | 非空 | 记忆文本正文，也是 FTS5 索引内容的来源。 |
| `memory_type` | TEXT | 可空；默认 `'fact'` | 记忆类别。 |
| `instruction_weight` | REAL | 可空；默认 `1.0` | 指令属性权重。当前显式衰减公式未将它作为输入。 |
| `emotion_weight` | REAL | 可空；默认 `1.0` | 情绪属性权重。当前显式衰减公式未将它作为输入。 |
| `base_weight` | REAL | 可空；默认 `1.0` | 衰减计算的基础权重；公开 API 可由调用方指定。 |
| `decay_lambda` | REAL | 可空；默认 `0.01` | 指数时间衰减系数。 |
| `retrieval_count` | INTEGER | 可空；默认 `0` | 参与公式计算的累计检索次数计数。 |
| `last_decay_at` | INTEGER | 非空 | 衰减计算起点时间；当前实现以 Unix 秒保存。 |
| `decayed_weight` | REAL | 可空；默认 `1.0` | 已存储的衰减权重值。 |
| `valid_from` | INTEGER | 非空 | 事实在业务时间上的生效时刻。 |
| `valid_to` | INTEGER | 可空 | 事实在业务时间上的失效时刻；`NULL` 表示尚无失效时间。 |
| `tx_time` | INTEGER | 非空 | 记忆记录写入数据库的事务时间点。 |
| `status` | TEXT | 可空；默认 `'active'` | 记忆状态；冲突处理会将旧记忆设置为 `'expired'`。 |
| `source_episode_id` | TEXT | 可空；外键 `episodes(id)`，删除来源事件时设为 `NULL` | 记忆对应的来源事件。 |
| `created_at` | INTEGER | 非空 | 记忆记录创建时间；当前写入路径与 `valid_from`、`tx_time` 使用相同时间点。 |

### 双时间戳字段的语义

记忆表的时间字段回答不同的问题，不能互相替代：

| 字段 | 时间维度 | 回答的问题 | 当前写入/更新行为 |
|---|---|---|---|
| `valid_from` | 业务有效时间 | 这条事实从何时开始在现实或业务域内成立？ | 新记忆写入时设为当前 Unix 秒。 |
| `valid_to` | 业务有效时间 | 这条事实从何时起不再成立？ | 当前事实为 `NULL`；冲突失效时设为当前 Unix 秒。 |
| `tx_time` | 数据库事务时间 | 系统何时首次将这条记忆写入数据库？ | 新记录插入时设为当前 Unix 秒；冲突时不覆盖旧记录的该字段。 |

例如，系统在 6 月 10 日获知某人的地址从 6 月 1 日起已变更：理想的业务记录可令新地址的 `valid_from` 为 6 月 1 日，而 `tx_time` 为 6 月 10 日。这能表达“业务事实从 6 月 1 日生效，但系统直到 6 月 10 日才获知”。当前 `remember()` API 不接受独立的业务有效时间参数，因此默认将 `valid_from`、`tx_time` 和 `created_at` 设成同一写入时刻；要记录延迟获知的历史事实，需要由更高层提供相应数据写入能力。

冲突处理通过保留旧行、将其 `valid_to` 设为失效时间并插入新行，避免覆盖正文导致业务历史丢失。需要注意，schema 没有事务时间结束列，也没有自动保存每次行更新前后的快照；`tx_time` 是写入时间点，不能单独提供完整的“任意历史时刻数据库状态”重建能力。

## 5. `entities`：实体

| 字段 | 类型 | 约束 / 默认值 | 业务含义 |
|---|---|---|---|
| `id` | TEXT | 主键 | 实体唯一标识。 |
| `tenant_id` | TEXT | 非空；外键 `tenants(id)`，删除租户时级联删除 | 所属租户。 |
| `name` | TEXT | 非空 | 输入或展示用实体名称。 |
| `canonical_name` | TEXT | 非空 | 用于规范化匹配和合并的名称。 |
| `entity_type` | TEXT | 可空；默认 `'unknown'` | 实体类别。 |
| `created_at` | INTEGER | 非空 | 实体创建时间。 |

## 6. `entity_aliases`：实体别名

| 字段 | 类型 | 约束 / 默认值 | 业务含义 |
|---|---|---|---|
| `id` | TEXT | 主键 | 别名记录唯一标识。 |
| `tenant_id` | TEXT | 非空；外键 `tenants(id)`，删除租户时级联删除 | 所属租户。 |
| `entity_id` | TEXT | 非空；外键 `entities(id)`，删除实体时级联删除 | 此别名所属实体。 |
| `alias` | TEXT | 非空；唯一索引 `(tenant_id, alias)` | 实体的别名；同一租户内不可重复。 |
| `created_at` | INTEGER | 非空 | 别名记录创建时间。 |

## 7. `edges`：实体关系三元组

| 字段 | 类型 | 约束 / 默认值 | 业务含义 |
|---|---|---|---|
| `id` | TEXT | 主键 | 关系边唯一标识。 |
| `tenant_id` | TEXT | 非空；外键 `tenants(id)`，删除租户时级联删除 | 所属租户。 |
| `subject_id` | TEXT | 非空；外键 `entities(id)`，删除实体时级联删除 | 三元组主语实体。 |
| `predicate` | TEXT | 非空 | 关系谓词，如“居住于”。 |
| `object_id` | TEXT | 非空；外键 `entities(id)`，删除实体时级联删除 | 三元组宾语实体。 |
| `memory_id` | TEXT | 可空；外键 `memories(id)`，删除记忆时设为 `NULL` | 支撑该关系的记忆来源。 |
| `valid_from` | INTEGER | 非空 | 关系在业务时间上的生效时刻。 |
| `valid_to` | INTEGER | 可空 | 关系失效时刻；`NULL` 表示当前没有记录失效时间。 |
| `confidence` | REAL | 可空；默认 `1.0` | 关系可信度。 |
| `created_at` | INTEGER | 非空 | 关系记录创建时间。 |

## 8. `memory_edges`：记忆间关联

| 字段 | 类型 | 约束 / 默认值 | 业务含义 |
|---|---|---|---|
| `id` | TEXT | 主键 | 记忆关联唯一标识。 |
| `tenant_id` | TEXT | 非空；外键 `tenants(id)`，删除租户时级联删除 | 所属租户。 |
| `source_memory_id` | TEXT | 非空；外键 `memories(id)`，删除记忆时级联删除 | 关联起点记忆。 |
| `target_memory_id` | TEXT | 非空；外键 `memories(id)`，删除记忆时级联删除 | 关联目标记忆。 |
| `relation_type` | TEXT | 非空 | 记忆之间的关系类型。 |
| `created_at` | INTEGER | 非空 | 关联记录创建时间。 |

## 9. `retrieval_logs`：检索审计日志

| 字段 | 类型 | 约束 / 默认值 | 业务含义 |
|---|---|---|---|
| `id` | TEXT | 主键 | 检索日志唯一标识。 |
| `tenant_id` | TEXT | 非空；外键 `tenants(id)`，删除租户时级联删除 | 所属租户。 |
| `query` | TEXT | 非空 | 原始检索查询。 |
| `candidates_json` | TEXT | 非空 | 候选记忆的 JSON 序列化内容。 |
| `recalled_json` | TEXT | 非空 | 最终召回结果的 JSON 序列化内容。 |
| `score_detail_json` | TEXT | 非空 | 评分明细的 JSON 序列化内容。 |
| `adopted` | INTEGER | 可空；默认 `0` | 是否被调用方采纳的标记。 |
| `created_at` | INTEGER | 非空 | 检索日志创建时间。 |

## 10. `schema_migrations`：迁移版本

| 字段 | 类型 | 约束 / 默认值 | 业务含义 |
|---|---|---|---|
| `version` | INTEGER | 主键 | 已应用迁移的版本号。 |
| `applied_at` | INTEGER | 非空 | 迁移成功应用的时间。 |

## 11. FTS5 虚拟表与索引

| 对象 | 定义 / 约束 | 用途 |
|---|---|---|
| `memories_fts` | FTS5 外部内容表，`content='memories'`，以 `memories.rowid` 关联 | 对 `memories.content` 建全文索引。 |
| `memories_ai` | `AFTER INSERT` 触发器 | 新记忆插入后同步正文到 FTS5。 |
| `memories_ad` | `AFTER DELETE` 触发器 | 删除记忆时从 FTS5 删除对应索引内容。 |
| `memories_au` | `AFTER UPDATE` 触发器 | 更新记忆时先删除旧索引项，再插入新正文。 |
| `idx_memories_current` | `memories(tenant_id, valid_to)` 部分索引，条件 `valid_to IS NULL` | 加速查找尚未设置失效时间的记忆。 |
| `idx_memories_decay` | `memories(tenant_id, last_decay_at)` | 支持按租户和上次衰减时间访问记忆。 |
| `idx_edges_subject_current` | `edges(tenant_id, subject_id, valid_to)` | 支持按主语和有效状态查询关系。 |
| `idx_edges_object_current` | `edges(tenant_id, object_id, valid_to)` | 支持按宾语和有效状态查询关系。 |
| `idx_entity_aliases_unique` | 唯一索引 `(tenant_id, alias)` | 保证租户内别名唯一。 |
