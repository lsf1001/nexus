/**
 * 新建 Project 表单抽屉 — Round 1 SPEC §4.3。
 *
 * 三个字段:name(slug,必填)/ display_name / description。
 * name 客户端预校验 ^[a-z0-9][a-z0-9-_]{0,31}$,失败红字 + 阻止提交。
 * 后端 409 → toast(由 onError 回调实现)。
 */
import { useState } from 'react';
import { useStore } from '../../store';

const SLUG_RE = /^[a-z0-9][a-z0-9-_]{0,31}$/;

export interface NewProjectDrawerProps {
  open: boolean;
  onClose: () => void;
}

export function NewProjectDrawer({ open, onClose }: NewProjectDrawerProps) {
  const createProject = useStore((s) => s.createProject);
  const [name, setName] = useState('');
  const [displayName, setDisplayName] = useState('');
  const [description, setDescription] = useState('');
  const [submitting, setSubmitting] = useState(false);

  if (!open) return null;

  const nameValid = SLUG_RE.test(name);

  const submit = async (): Promise<void> => {
    if (!nameValid || submitting) return;
    setSubmitting(true);
    try {
      await createProject({
        name,
        display_name: displayName || name,
        description,
      });
      // 清表单 + 关闭
      setName('');
      setDisplayName('');
      setDescription('');
      onClose();
    } catch (err) {
      // 错误由 PreferencesModal 通过 store 弹 toast;这里不重复
      console.error('createProject 失败:', err);
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="new-project-drawer" role="dialog" aria-label="新建项目">
      <h3>新建项目</h3>
      <label>
        <span>slug (英文/数字/-/_)</span>
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="my-coding-project"
          autoFocus
        />
        {name.length > 0 && !nameValid && (
          <span className="field-error">格式不合法</span>
        )}
      </label>
      <label>
        <span>显示名</span>
        <input
          value={displayName}
          onChange={(e) => setDisplayName(e.target.value)}
          placeholder="我的编码项目"
        />
      </label>
      <label>
        <span>描述</span>
        <textarea
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          rows={3}
        />
      </label>
      <div className="new-project-drawer-actions">
        <button type="button" onClick={onClose} disabled={submitting}>取消</button>
        <button
          type="button"
          className="primary"
          onClick={() => void submit()}
          disabled={!nameValid || submitting}
        >
          {submitting ? '创建中…' : '创建'}
        </button>
      </div>
    </div>
  );
}