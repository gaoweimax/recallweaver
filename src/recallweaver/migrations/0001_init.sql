PRAGMA foreign_keys = ON;

-- 1. 租户/多 Agent 隔离表
CREATE TABLE IF NOT EXISTS tenants (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    created_at INTEGER NOT NULL
);

-- 2. 原始对话/事件表
CREATE TABLE IF NOT EXISTS episodes (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    raw_content TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

-- 3. 记忆主表 (包含双时间戳与遗忘权重机制)
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    content TEXT NOT NULL,
    memory_type TEXT DEFAULT 'fact',
    instruction_weight REAL DEFAULT 1.0,
    emotion_weight REAL DEFAULT 1.0,
    base_weight REAL DEFAULT 1.0,
    decay_lambda REAL DEFAULT 0.01,
    retrieval_count INTEGER DEFAULT 0,
    last_decay_at INTEGER NOT NULL,
    decayed_weight REAL DEFAULT 1.0,
    valid_from INTEGER NOT NULL,
    valid_to INTEGER,
    tx_time INTEGER NOT NULL,
    status TEXT DEFAULT 'active',
    source_episode_id TEXT,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (source_episode_id) REFERENCES episodes(id) ON DELETE SET NULL
);

-- 4. 实体表
CREATE TABLE IF NOT EXISTS entities (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    entity_type TEXT DEFAULT 'unknown',
    created_at INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

-- 5. 实体别名表
CREATE TABLE IF NOT EXISTS entity_aliases (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    alias TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (entity_id) REFERENCES entities(id) ON DELETE CASCADE
);

-- 6. 时空蜘蛛网边表 (三元组关系)
CREATE TABLE IF NOT EXISTS edges (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    subject_id TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object_id TEXT NOT NULL,
    memory_id TEXT,
    valid_from INTEGER NOT NULL,
    valid_to INTEGER,
    confidence REAL DEFAULT 1.0,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (subject_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (object_id) REFERENCES entities(id) ON DELETE CASCADE,
    FOREIGN KEY (memory_id) REFERENCES memories(id) ON DELETE SET NULL
);

-- 7. 记忆间关联表
CREATE TABLE IF NOT EXISTS memory_edges (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    source_memory_id TEXT NOT NULL,
    target_memory_id TEXT NOT NULL,
    relation_type TEXT NOT NULL,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE,
    FOREIGN KEY (source_memory_id) REFERENCES memories(id) ON DELETE CASCADE,
    FOREIGN KEY (target_memory_id) REFERENCES memories(id) ON DELETE CASCADE
);

-- 8. 检索日志表 (用于审计与可解释性)
CREATE TABLE IF NOT EXISTS retrieval_logs (
    id TEXT PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    query TEXT NOT NULL,
    candidates_json TEXT NOT NULL,
    recalled_json TEXT NOT NULL,
    score_detail_json TEXT NOT NULL,
    adopted INTEGER DEFAULT 0,
    created_at INTEGER NOT NULL,
    FOREIGN KEY (tenant_id) REFERENCES tenants(id) ON DELETE CASCADE
);

-- 9. 数据库迁移版本记录表
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at INTEGER NOT NULL
);

-- ==========================================
-- 核心索引：保证检索性能，杜绝全表扫描
-- ==========================================
-- 针对当前有效数据的部分索引（极速查询 valid_to 为空的数据）
CREATE INDEX IF NOT EXISTS idx_memories_current ON memories(tenant_id, valid_to) WHERE valid_to IS NULL;
-- 惰性衰减扫描索引
CREATE INDEX IF NOT EXISTS idx_memories_decay ON memories(tenant_id, last_decay_at);
-- 图遍历复合索引
CREATE INDEX IF NOT EXISTS idx_edges_subject_current ON edges(tenant_id, subject_id, valid_to);
CREATE INDEX IF NOT EXISTS idx_edges_object_current ON edges(tenant_id, object_id, valid_to);
-- 别名唯一性约束
CREATE UNIQUE INDEX IF NOT EXISTS idx_entity_aliases_unique ON entity_aliases(tenant_id, alias);

-- ==========================================
-- FTS5 全文检索引擎及同步触发器
-- ==========================================
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
    content,
    content='memories',
    content_rowid='rowid'
);

-- 触发器：插入同步
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;

-- 触发器：删除同步
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.rowid, old.content);
END;

-- 触发器：更新同步
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content) VALUES('delete', old.rowid, old.content);
    INSERT INTO memories_fts(rowid, content) VALUES (new.rowid, new.content);
END;