"""``nexus.backend.skills.schema``:SKILL.md 解析后的 Pydantic 模型。

WHY BaseModel:frontmatter 字段全在 YAML 里,Pydantic 校验能在解析阶段
就报"缺 name / 缺 entrypoint"这种硬错误,LLM 不会被"加载失败但继续
跑了 run_skill"的含糊 ToolMessage 误导。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class SkillManifest(BaseModel):
    """单个 skill 的元数据(从 SKILL.md frontmatter 解析)。"""

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)
    triggers: list[str] = Field(default_factory=list)
    # 必须绝对路径——LSP/SDK 已用 sandbox 锁 cwd,entrypoint 也得明牌
    entrypoint: str = Field(min_length=1)
    # 自由文本,告诉 LLM 这个 skill 接什么参数
    inputs: str = ""
    # 必需 env var 名列表;run_skill 入口处短路检查
    requires: list[str] = Field(default_factory=list)
    # markdown body(给 LLM 看的"怎么用"细节)
    body: str = ""
