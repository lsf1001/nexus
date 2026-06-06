"""Rubric 子包：响应质量评分与判定（Phase 2）。

本包实现"输出质量自评"链路所需的数据结构与判定规则：
  - `schemas`: 评分维度（Rubric）、单维度结果（Score）、综合判定（RubricVerdict）
    等不可变数据类，以及 4 个内置 Rubric。

设计原则：
  - 这一层只承载数据与判定函数；不调用 LLM，不调用 DB，不依赖业务模块。
  - 所有数据类均为 ``frozen=True``，可被多线程/异步协程安全共享。
  - 后续 Task 2.2+ 在此之上叠加 prompt 模板、判官、修复策略、pipeline。
"""
