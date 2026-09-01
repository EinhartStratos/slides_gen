SET NAMES utf8mb4;
SET FOREIGN_KEY_CHECKS = 0;

-- ============================================================
-- v4 增量迁移：正文与单图 SVG 分离生成模式
-- 新增表：sg_generation_request、sg_generation_diagram
-- 扩展表：sg_generation_task、sg_generation_task_page
--
-- 注意：本迁移使用一次性 ALTER COLUMN，执行前请确认目标库尚未执行。
-- 如需幂等执行，请使用 apply_mysql_migration_v4.py 包装脚本。
-- ============================================================

CREATE TABLE IF NOT EXISTS `sg_generation_request` (
  `generation_id` VARCHAR(64) NOT NULL COMMENT '输入唯一ID',
  `api_key` VARCHAR(512) NOT NULL COMMENT '调用方 API Key',
  `template_id` VARCHAR(64) DEFAULT NULL COMMENT '模板ID',
  `generation_mode` VARCHAR(32) NOT NULL DEFAULT 'separated_body_diagram' COMMENT '生成模式：legacy_hybrid / separated_body_diagram',
  `requirement_text` LONGTEXT NOT NULL COMMENT '上游合并后的需求全文',
  `custom_requirements` LONGTEXT DEFAULT NULL COMMENT '本次生成指令',
  `request_payload_json` LONGTEXT DEFAULT NULL COMMENT '创建时的原始请求 JSON',
  `auto_compose` TINYINT(1) NOT NULL DEFAULT 1 COMMENT '正文和图形均可用时是否自动组装',
  `status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '聚合状态：pending/running/completed/completed_with_warnings/failed',
  `warning_message` TEXT DEFAULT NULL COMMENT '告警信息，例如需求文本超过5万字',
  `requirement_text_chars` INT UNSIGNED NOT NULL DEFAULT 0 COMMENT '需求文本字符数',
  `planning_manifest_ftp_path` VARCHAR(1024) DEFAULT NULL COMMENT '共享规划清单 FTP 路径',
  `body_task_id` VARCHAR(64) DEFAULT NULL COMMENT '正文任务ID',
  `diagram_task_id` VARCHAR(64) DEFAULT NULL COMMENT '图形任务ID',
  `compose_task_id` VARCHAR(64) DEFAULT NULL COMMENT '组装任务ID',
  `body_status` VARCHAR(32) NOT NULL DEFAULT 'not_requested' COMMENT '正文状态：not_requested/pending/running/completed/completed_with_warnings/failed',
  `diagram_status` VARCHAR(32) NOT NULL DEFAULT 'not_requested' COMMENT '图形状态：not_requested/pending/running/completed/completed_with_warnings/failed',
  `compose_status` VARCHAR(32) NOT NULL DEFAULT 'not_requested' COMMENT '组装状态：not_requested/waiting/pending/running/completed/completed_with_warnings/failed',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  `completed_at` DATETIME(3) DEFAULT NULL COMMENT '完成时间',
  PRIMARY KEY (`generation_id`),
  KEY `idx_sg_generation_request_api_key_created_at` (`api_key`, `created_at`),
  KEY `idx_sg_generation_request_status` (`status`),
  KEY `idx_sg_generation_request_body_task_id` (`body_task_id`),
  KEY `idx_sg_generation_request_diagram_task_id` (`diagram_task_id`),
  KEY `idx_sg_generation_request_compose_task_id` (`compose_task_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='生成输入父记录表';

CREATE TABLE IF NOT EXISTS `sg_generation_diagram` (
  `diagram_id` VARCHAR(64) NOT NULL COMMENT '图形唯一ID',
  `generation_id` VARCHAR(64) NOT NULL COMMENT '所属输入ID',
  `task_id` VARCHAR(64) NOT NULL COMMENT '所属图形任务ID',
  `page_key` VARCHAR(255) DEFAULT NULL COMMENT '稳定页键（模板页或章节键）',
  `template_page_no` INT UNSIGNED DEFAULT NULL COMMENT '模板页码',
  `final_page_no` INT UNSIGNED DEFAULT NULL COMMENT '组装后最终页码；SVG-only 时为空',
  `diagram_title` VARCHAR(255) DEFAULT NULL COMMENT '图形标题',
  `section_title` VARCHAR(255) DEFAULT NULL COMMENT '所属章节标题',
  `diagram_kind` VARCHAR(64) DEFAULT NULL COMMENT '图形类型，例如 architecture / sequence',
  `diagram_description` TEXT DEFAULT NULL COMMENT '图形说明',
  `version` INT UNSIGNED NOT NULL DEFAULT 1 COMMENT '版本号，重试时递增',
  `status` VARCHAR(32) NOT NULL DEFAULT 'pending' COMMENT '图形状态：pending/running/completed/failed',
  `ftp_original_svg_path` VARCHAR(1024) DEFAULT NULL COMMENT '原始模型生成 SVG 的 FTP 路径',
  `ftp_final_svg_path` VARCHAR(1024) DEFAULT NULL COMMENT '最终净化后 SVG 的 FTP 路径',
  `evidence_quotes_json` LONGTEXT DEFAULT NULL COMMENT '用于判断的原文摘录 JSON',
  `applied_rule_ids_json` LONGTEXT DEFAULT NULL COMMENT '命中的全局规则 ID 列表 JSON',
  `layout_decision_json` LONGTEXT DEFAULT NULL COMMENT '布局决策 JSON',
  `validation_status` VARCHAR(32) DEFAULT NULL COMMENT '校验状态：pending/passed/failed',
  `error_message` TEXT DEFAULT NULL COMMENT '失败信息',
  `created_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) COMMENT '创建时间',
  `updated_at` DATETIME(3) NOT NULL DEFAULT CURRENT_TIMESTAMP(3) ON UPDATE CURRENT_TIMESTAMP(3) COMMENT '更新时间',
  `completed_at` DATETIME(3) DEFAULT NULL COMMENT '完成时间',
  PRIMARY KEY (`diagram_id`),
  KEY `idx_sg_generation_diagram_generation_id` (`generation_id`),
  KEY `idx_sg_generation_diagram_task_id` (`task_id`),
  KEY `idx_sg_generation_diagram_status` (`status`),
  KEY `idx_sg_generation_diagram_generation_task_status` (`generation_id`, `task_id`, `status`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci COMMENT='独立图形表';

ALTER TABLE `sg_generation_task`
  ADD COLUMN `generation_id` VARCHAR(64) DEFAULT NULL COMMENT '所属输入ID' AFTER `api_key`,
  ADD COLUMN `task_type` VARCHAR(32) NOT NULL DEFAULT 'legacy' COMMENT '任务类型：legacy/body/diagrams/compose' AFTER `generation_id`,
  ADD COLUMN `depends_on_task_ids_json` LONGTEXT DEFAULT NULL COMMENT '依赖任务ID列表 JSON' AFTER `task_type`,
  ADD KEY `idx_sg_generation_task_generation_id` (`generation_id`),
  ADD KEY `idx_sg_generation_task_task_type` (`task_type`);

ALTER TABLE `sg_generation_task_page`
  ADD COLUMN `page_key` VARCHAR(255) DEFAULT NULL COMMENT '稳定页键' AFTER `page_no`,
  ADD COLUMN `template_page_title` VARCHAR(255) DEFAULT NULL COMMENT '模板固定章节标题' AFTER `page_key`,
  ADD COLUMN `information_sufficient` TINYINT(1) DEFAULT NULL COMMENT '信息是否充足' AFTER `should_generate`,
  ADD COLUMN `evidence_quotes_json` LONGTEXT DEFAULT NULL COMMENT '判断依据原文摘录 JSON' AFTER `information_sufficient`,
  ADD COLUMN `diagram_required` TINYINT(1) DEFAULT NULL COMMENT '该页是否需要额外生成图形' AFTER `diagram_kind`,
  ADD COLUMN `page_type` VARCHAR(32) DEFAULT NULL COMMENT '页面类型：cover/toc/content/diagram/end' AFTER `diagram_required`,
  ADD COLUMN `final_page_no` INT UNSIGNED DEFAULT NULL COMMENT '最终页码' AFTER `page_type`;

SET FOREIGN_KEY_CHECKS = 1;
