# 阶段 1 实施计划

> 执行方式：使用 superpowers:executing-plans 与 test-driven-development，逐任务完成红灯、实现、绿灯及记录。

目标：交付严格调查协议、统一裁决、版本迁移及固定规则评测；完整雾港样本已获用户批准并冻结为 1.0.0，阶段 1 验收完成。
架构：schema 与引用检查独立于纯裁决。所有状态后继通过 app/state.py 分派；BFS 复用该路径。持久化保存不可变版本，不开放新前端/API。
技术：Pydantic 2、SQLAlchemy、Alembic、pytest、PostgreSQL 18。
规范：[故事规则](stage-1-story-rules.md)、[评测](../evaluation/task-success-baseline.md)。

## 全局约束

- 三角色、五地点、三结局；信任 -3..3，单次变化 -2..2。
- 有界 BFS 上限 50,000；超限不能批准。旧 Demo 和四份草稿不改。
- 不读取用户 .env；数据库验证仅使用隔离 *_test 数据库。
- 外部模型重试/超时/Trace 在阶段 2，本阶段不发 API 请求。
- 样本起草时为 draft；用户已审定并批准，冻结为 1.0.0。语义审定与用户批准不能被自动测试替代。

## 任务与验证

### 1. 协议与引用检查
文件：app/story_schema.py，tests/test_investigation_schema.py，tests/fixtures/mist_harbor_investigation.json。
接口：Story.model_validate(data)、parse_action(data)、canonical_hash(story)。
- [x] 写严格类型、额外字段、未知版本、重复 ID、悬空引用及非法效果测试，执行并确认失败。
- [x] 实现判别联合、故事/状态模型、跨实体引用及信任规则检查。
- [x] 运行 schema 测试，检查全样本合法；初次交付保持 draft，用户批准后冻结为 1.0.0。

### 2. 裁决、公开投影及可达性
文件：app/investigation.py，app/story_validation.py，修改 app/state.py；tests/test_investigation_rules.py。
接口：apply_state_changes(parent, story=story, action=action) -> Adjudication；initial_investigation_state(story)；public_projection(story,state)；check_reachability(story,max_states=50000)。
- [x] 写同地点调查、拒绝/重复、信任越界、事件一次性、兄弟分支、终局及未知版本失败测试。
- [x] 写证据互锁、缺失出口、冲突规则、不可达结局及超限测试，确认失败。
- [x] 实现原子副本更新，先行动后事件闭包；公开字段白名单。
- [x] BFS 排除 turn 去重，保留三结局见证；验证每条路径 15–25 次有效行动。
- [x] 运行规则、schema 测试。

### 3. 增量迁移与不可变版本
文件：app/models.py，app/story_versions.py，migrations/versions/0004_story_versions.py；tests/test_story_versions.py。
接口：save_story_version(db,story,status='draft')、load_story_version(db,id)；批准状态由后续用户确认流程使用。
- [x] 写版本隔离、哈希校验、不可变性、旧节点/事件迁移前后保持原样测试，确认失败。
- [x] 增加故事版本与可空会话/节点引用，地点字段扩大到64；增加数据库不可变约束。
- [x] 隔离库 upgrade head、alembic check；旧 Demo 三结局及回放测试通过。

### 4. 评测与交付
文件：evals/run_stage1.py，evals/cases/stage1.json，tests/test_stage1_evaluation.py；审定材料和开发日志。
接口：rules / legacy 两个套件；固定分母，失败/错误/跳过非零；报告仅规则/兼容，包含版本与 SHA256。
- [x] 写报告计数、空清单、缺失/非测试库拒绝、错误/超时/跳过等评测测试，确认失败。
- [x] 实现 subprocess 隔离案例执行和超时，JSON 到 Git 忽略 runtime/evals。
- [x] 全部后端测试、两个套件、迁移核对、Markdown 链接与 git diff --check。
- [x] 一次独立最终代码审查，修复有影响的问题后验证。
- [x] 提交相关文件，提供完整样本审定入口；未批准不标阶段全部完成。

## Review Focus

- 外部构造的状态必须校验其故事身份、版本及全部实体引用。
- 不可重复的信任效果和事件错误不能部分提交；负例必须检查父快照原样。
- 玩家字段不能夹带 facts、secret_fact_ids、未发现 evidence 或规则条件。
- 已批准版本数据库更新、删除及哈希不匹配必须拒绝，旧空关联仍合法。
- 评测子进程超时/异常/跳过必须保留固定分母，报告不能泄漏凭据。
