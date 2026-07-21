/**
 * ArtifactsPanel — 右栏"作品"面板容器(SPEC §3.1 / §8)
 *
 * 形态:
 *   - 折叠(artifactsCollapsed=true)→ 完全不渲染(CSS 0 宽 + null)
 *   - 展开 + 空列表 → 显示空态("agent 还没产出文件类产物")
 *   - 展开 + 有产物 → head(filename + 关闭) + tabs(切 kind) + body(渲染器) + foot(meta)
 *
 * 不在容器内做渲染选择:每个 artifact 在 push 时已固化 kind;切 tab 是切 activeArtifactId
 * 到另一个同 kind artifact(如果存在),否则停在当前。
 */
import { useStore } from '../../store';
import type { Artifact, ArtifactKind } from '../../store/slices/artifacts';
import {
  CodeRenderer,
  MarkdownRenderer,
  SvgRenderer,
  HtmlRenderer,
} from './renderers';

export function ArtifactsPanel() {
  const collapsed = useStore((s) => s.artifactsCollapsed);
  const artifacts = useStore((s) => s.artifacts);
  const activeId = useStore((s) => s.activeArtifactId);
  const setActive = useStore((s) => s.setActiveArtifact);
  const remove = useStore((s) => s.removeArtifact);
  const setCollapsed = useStore((s) => s.setArtifactsCollapsed);

  // 折叠态完全隐藏(用 CSS 0 宽 + null 兜底,防 a11y 焦点错乱)
  if (collapsed) return null;

  const active: Artifact | undefined = artifacts.find((a) => a.id === activeId);

  return (
    <aside
      className="artifacts-panel"
      role="complementary"
      aria-label="产物面板"
    >
      {artifacts.length === 0 || !active ? (
        <ArtifactsEmpty />
      ) : (
        <>
          <header className="artifact-head">
            <span className="artifact-filename" title={active.filename}>
              {kindIcon(active.kind)} {active.filename ?? active.title ?? '未命名产物'}
            </span>
            <div className="artifact-head-actions">
              {artifacts.length > 1 && (
                <span className="artifact-counter">
                  {artifacts.findIndex((a) => a.id === activeId) + 1} / {artifacts.length}
                </span>
              )}
              <button
                type="button"
                className="artifact-close"
                onClick={() => setCollapsed(true)}
                aria-label="关闭产物面板"
              >
                ✕
              </button>
            </div>
          </header>

          <nav className="artifact-tabs" role="tablist" aria-label="产物种类">
            {availableKinds(artifacts).map((k) => {
              const count = artifacts.filter((a) => a.kind === k).length;
              if (count === 0) return null;
              // 当前 tab: 当前 active 同 kind → 高亮
              const isActive = active.kind === k;
              // 切 tab: 跳到该 kind 的第一个 artifact
              const target = artifacts.find((a) => a.kind === k);
              return (
                <button
                  key={k}
                  type="button"
                  role="tab"
                  aria-selected={isActive}
                  className={`artifact-tab${isActive ? ' is-active' : ''}`}
                  onClick={() => target && setActive(target.id)}
                >
                  {kindLabel(k)}
                  <span className="artifact-tab-count">{count}</span>
                </button>
              );
            })}
          </nav>

          <div className="artifact-body">
            <ActiveRenderer artifact={active} />
          </div>

          <footer className="artifact-foot">
            <span>{active.sourceToolCallId ? `by ${active.sourceToolCallId}` : '产物'}</span>
            <span>· {active.content.length} 字符</span>
            <span className="artifact-foot-spacer" />
            {artifacts.length > 1 && (
              <button
                type="button"
                className="artifact-remove"
                onClick={() => remove(active.id)}
                aria-label="移除当前产物"
              >
                移除
              </button>
            )}
          </footer>
        </>
      )}
    </aside>
  );
}

function ActiveRenderer({ artifact }: { artifact: Artifact }) {
  switch (artifact.kind) {
    case 'code':
      return <CodeRenderer content={artifact.content} language={artifact.language} />;
    case 'markdown':
      return <MarkdownRenderer content={artifact.content} />;
    case 'svg':
      return <SvgRenderer content={artifact.content} />;
    case 'html':
      return <HtmlRenderer content={artifact.content} />;
    default:
      return <CodeRenderer content={artifact.content} />;
  }
}

function ArtifactsEmpty() {
  return (
    <div className="artifacts-empty">
      <div className="artifacts-empty-icon" aria-hidden="true">📄</div>
      <div className="artifacts-empty-title">还没有产物</div>
      <div className="artifacts-empty-hint">
        agent 在工具调用中产生的代码 / Markdown / SVG / HTML 会自动出现在这里。
      </div>
    </div>
  );
}

function availableKinds(list: Artifact[]): ArtifactKind[] {
  const s = new Set<ArtifactKind>();
  list.forEach((a) => s.add(a.kind));
  // 固定顺序: code → markdown → svg → html
  return (['code', 'markdown', 'svg', 'html'] as ArtifactKind[]).filter((k) => s.has(k));
}

function kindIcon(k: ArtifactKind): string {
  switch (k) {
    case 'code':
      return '📄';
    case 'markdown':
      return '📝';
    case 'svg':
      return '🖼';
    case 'html':
      return '🌐';
    default:
      return '📄';
  }
}

function kindLabel(k: ArtifactKind): string {
  switch (k) {
    case 'code':
      return 'Code';
    case 'markdown':
      return 'Md';
    case 'svg':
      return 'SVG';
    case 'html':
      return 'HTML';
    default:
      return k;
  }
}