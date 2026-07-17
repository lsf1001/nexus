import { useState } from 'react';

/**
 * Artifact 类型 — 与后端 tool_result/final 帧产出的"作品"对齐。
 * Task 3.3 会从 wsHandlers 写入 store 的 `artifacts` slice,本组件订阅它渲染。
 * 这里先在本地定义并导出,供 3.3 直接复用(避免重复声明)。
 */
export type ArtifactKind = 'code' | 'markdown' | 'svg' | 'html';

export interface Artifact {
  id: string;
  kind: ArtifactKind;
  content: string;
  title?: string;
  /** code/markdown 的高亮语言(可选) */
  language?: string;
}

export interface ArtifactsPanelProps {
  /** 当前会话的 artifact 列表(来自 store,Phase 3.3 接入)。默认空数组。 */
  artifacts?: Artifact[];
}

/**
 * 右侧 Artifacts 面板 — 三区布局的右列。
 *
 * 行为:
 *   - `artifacts` 为空(默认)→ 返回 null,grid 第 3 轨塌缩为 0 宽,
 *     `.chat-area` 保持全宽(e2e 契约)。
 *   - 非空 → 渲染右栏,按 kind 渲染 code/markdown/svg/html。
 *
 * 这是 Task 2.3 的占位版:code 用 <pre>,markdown 暂按纯文本展示(3.3 接
 * react-markdown + 语法高亮),svg 直接内联,html 用沙箱 iframe。
 * 复制按钮用 navigator.clipboard,失败静默(本地环境无 clipboard 不报错)。
 */
export function ArtifactsPanel({ artifacts = [] }: ArtifactsPanelProps) {
  const [copiedId, setCopiedId] = useState<string | null>(null);

  if (artifacts.length === 0) return null;

  const handleCopy = (artifact: Artifact): void => {
    if (!navigator.clipboard?.writeText) return;
    void navigator.clipboard.writeText(artifact.content).then(() => {
      setCopiedId(artifact.id);
      window.setTimeout(() => setCopiedId(null), 1200);
    });
  };

  return (
    <aside className="artifacts-panel" aria-label="Artifacts">
      <header className="artifacts-panel-header">
        <span className="artifacts-panel-title">Artifacts</span>
        <span className="artifacts-panel-count">{artifacts.length}</span>
      </header>
      <div className="artifacts-panel-body">
        {artifacts.map((artifact) => (
          <article key={artifact.id} className="artifact-card" data-kind={artifact.kind}>
            <div className="artifact-card-head">
              <span className="artifact-card-title">
                {artifact.title || artifact.kind}
              </span>
              <button
                type="button"
                className="artifact-copy"
                onClick={() => handleCopy(artifact)}
              >
                {copiedId === artifact.id ? '已复制' : '复制'}
              </button>
            </div>
            <div className="artifact-card-body">
              {renderArtifact(artifact)}
            </div>
          </article>
        ))}
      </div>
    </aside>
  );
}

/** 按 kind 渲染 artifact 内容(占位渲染,3.3 会增强)。 */
function renderArtifact(artifact: Artifact) {
  switch (artifact.kind) {
    case 'code':
      return (
        <pre className="artifact-code">
          <code>{artifact.content}</code>
        </pre>
      );
    case 'svg':
      return (
        <div
          className="artifact-svg"
          // SVG 来自本地 agent 产出(非外部不可信源),内联渲染。
          dangerouslySetInnerHTML={{ __html: artifact.content }}
        />
      );
    case 'html':
      return (
        <iframe
          className="artifact-html"
          title={artifact.title || 'html-artifact'}
          sandbox="allow-scripts"
          srcDoc={artifact.content}
        />
      );
    case 'markdown':
    default:
      // 3.3 接入 react-markdown 渲染;当前按纯文本展示。
      return <div className="artifact-markdown">{artifact.content}</div>;
  }
}
