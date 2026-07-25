# Round 2: 文件上传 / 附件 + 草稿 UX 补全 — 设计 SPEC

> SPEC ID: `2026-07-24-round2-attachments-and-drafts`
> 父 SPEC: `2026-07-23-align-with-claude-desktop-design` §3 第 2 轮
> 状态: 待用户 review
> 实施方式: subagent-driven(参见对应 `plan` 文件)

---

## 1. 背景与目标

总览 SPEC 把第 2 轮列了两块 — 文件上传 / 附件(🔴 GAP #2)和草稿 UX 补全(🟡 GAP #3)。Round 1(Projects 骨架)已交付,本轮在 Round 1 上下文根上,补齐"内容进出 Composer"的两个面。

**WHY 这一轮重要**:用户对 Nexus 的核心期待是 Claude Desktop 等价体验。Composer 不能上传文件 = 一半工作流被截断;草稿不能跨 project 保留 = 用户每次切项目都要重写 prompt。这两块在 Round 1 之后变成最显眼的缺口。

**两个子目标的内在关系**:都绑定 Project(文件 per-project 落盘 + 草稿 per-project 持久化),跟 Round 1 的"上下文根"模型完全一致 — 不再独立造一套上下文。

---

## 2. 非目标

- ❌ **Voice 输入 / 录音转写** — 留到第 4 轮
- ❌ **URL 引用附件 / 网络文件抓取** — Round 5 之后
- ❌ **DAM(数字资产管理)级别的 metadata** — 仅保留 {id, name, size, mime, uploaded_at, project_id}
- ❌ **CDN 加速 / 多副本** — 单机本地 DMG
- ❌ **附件版本管理 / 历史** — 单条覆盖即可
- ❌ **附件 OCR / 图片理解增强** — 走 LLM 内置 vision
- ❌ **加密 / 脱敏** — 本地单机不需要

---

## 3. 范围(本期)

### 3.1 文件上传(主体,5 项)

| # | 决策 | 备注 |
|---|------|------|
| F1 | **入口** = 发送按钮左侧 `+` 按钮 + Composer 整区拖拽 + paste handler | 跟 Claude Desktop / Slack / Telegram 一致 |
| F2 | **预览** = Composer 下方贴附件预览条(缩略图 + 文件名 + 大小 + ×) | 跟随 input 一起滚出 Composer 底部,跟下消息前一直可见 |
| F3 | **存储** = per-project `~/Nexus/projects/{projectId}/uploads/{uuid}{ext}` | 走 Round 1 projects/storage.py 的 `_projects_root()` |
| F4 | **LLM 注入** = 消息发送时多 part content,文本文件读全文 + 图片 file→ base64 image_url | 文本上限 20000 字符(超则截断 + 末尾标记) |
| F5 | **REST** = `POST /api/attachments` 返 metadata,`GET /api/attachments/{id}` 拉 raw,`DELETE /api/attachments/{id}` 删除 | multipart/form-data |

### 3.2 草稿 UX 补全(3 项)

| # | 决策 | 备注 |
|---|------|------|
| D1 | **per-project 单草稿** = localStorage key = `nexus-draft-{projectId}` | 沿用 L1 防抖 + clearDraft 机制,只换 key + 加载时按 project 选 |
| D2 | **冲突提示** = 多 tab `storage` 事件监听,跨 tab 改同 project 草稿 → toast "另一窗口刚改,点恢复" | 不做 CRDT / OT,YAGNI |
| D3 | **草稿列表面板** = PreferencesModal 加 "草稿" tab,列所有 per-project 草稿 + 项目名 + 预览 + 跳回项目 | 跟 Skills / MCP tab 同模板 |

---

## 4. 详细 SPEC

### 4.1 Composer 上传入口(前端)

**文件清单**(新增 / 修改):
- 新增 `frontend/src/components/ChatArea/AttachmentBar.tsx`(附件预览条)
- 新增 `frontend/src/components/ChatArea/hooks/useAttachments.ts`(本地附件 state,不上 server)
- 修改 `frontend/src/components/ChatArea/Composer.tsx`(+ 按钮 + dropzone + paste)
- 修改 `frontend/src/components/ChatArea/index.tsx`(wire useAttachments + 提交时打包 attachments 给后端)
- 新增 `frontend/src/components/desktop/styles/chat.css` 块(附件预览条样式)

**+ 按钮**:
- 位置: sendButton 左侧 8px 间隙
- 图标: `+`(SVG,16px),hover 状态切到 `--ink-2`
- 行为: 调 hidden `<input type="file" multiple accept="image/*,.pdf,.txt,.md,.json,.csv,.py,.js,.ts,.tsx,.jsx" />` 的 click

**拖拽**:
- Composer 整个 `.composer-textarea` + `.composer-toolbar` 区域挂 `onDragOver` / `onDragLeave` / `onDrop`
- dragover 时 composer 边框颜色切到 `--accent`(`var(--accent)`),提示"松手上传"
- drop 时遍历 `e.dataTransfer.files`,过滤 type / 大小,append 到 attachments state

**paste**:
- textarea `onPaste` 监听 `e.clipboardData.items`,如果 `kind === 'file'` 就 file → attachment
- 文字 paste 不变

**附件类型白名单**:
- `image/png, image/jpeg, image/gif, image/webp`
- `application/pdf, text/plain, text/markdown, text/csv, application/json`
- `text/x-python, text/x-javascript, application/javascript, application/typescript, text/jsx, text/tsx`(后端兜底认后缀)
- 单文件上限 20MB(`MAX_FILE_SIZE = 20 * 1024 * 1024`),超则 toast 红字 "文件过大(>20MB)"

**WHY 20MB**:图片 base64 后 ≈ 27MB,Anthropic vision 限 5MB 拆多张;但 20MB 给 PDF / 文档留余地。本轮不做客户端压缩,只限制大小。

### 4.2 附件预览条(前端)

**文件**: `frontend/src/components/ChatArea/AttachmentBar.tsx`(新增)

**形态**:
- 位置: Composer 内部、textarea 下方、`composer-toolbar` 上方(夹在中间)
- 高度: 自适应,每行最多 3 个 chip,溢出横向 scroll
- chip 样式: 48px 高的圆角小卡片,左 32px 缩略图(图片用 base64 缩略 / 文件用首字母 placeholder),中 文件名 + 大小,右 × 按钮

**交互**:
- 点 × 移除附件
- 点 chip 主体:图片在 `<dialog>` 全屏查看;非图片弹 file size / path tooltip(无操作)
- 空数组 → 整条隐藏(display: none)

**关键 state**(useAttachments):
```ts
interface LocalAttachment {
  id: string;          // 客户端生成 uuid
  file: File;          // 原始 File 对象
  previewUrl?: string; // 图片: URL.createObjectURL(file)
  uploadStatus: 'pending' | 'uploading' | 'uploaded' | 'failed';
  serverId?: string;   // POST /api/attachments 成功后回填
  error?: string;
}
```

### 4.3 上传 REST(后端)

**新文件**:
- `nexus/backend/routes/attachments.py`(新路由)
- `nexus/backend/attachments.py`(storage helper:写盘 + 读盘 + mime sniff + 大小校验)
- `tests/test_attachments.py`(单测)

**REST 契约**:

```python
# POST /api/attachments
# multipart/form-data
#   - file: File
#   - project_id: str (form field, 必填)
# 返 201
{
  "id": "att_01HXY...",
  "project_id": "default",
  "original_name": "spec.pdf",
  "stored_filename": "att_01HXY...pdf",  # 内部 uuid + ext
  "file_path": "/Users/yxb/Nexus/projects/default/uploads/att_01HXY....pdf",
  "mime": "application/pdf",
  "size": 245123,
  "uploaded_at": "2026-07-24T10:00:00Z"
}

# GET /api/attachments/{id}
# 返 raw 文件,Content-Disposition: inline; filename={original_name}
# 限流:仅同 project 内的 attachment 可拉(防越权)

# DELETE /api/attachments/{id}
# 返 204,文件从磁盘删除
```

**存储位置**:
- `~/Nexus/projects/{projectId}/uploads/{stored_filename}`
- 启动时确保 `uploads/` 目录存在(mkdir parents=True exist_ok=True)
- 文件名 = `att_{uuid4()}{ext}`(ext 从原文件名取,空则空),防止目录穿越

**校验**:
- size > 20MB → 413 Payload Too Large
- mime 不在白名单(白名单与前端同步)→ 415 Unsupported Media Type
- project_id 不存在 → 404

**mime 嗅探**: 用 `python-magic-bin`(已安装?)做 magic bytes;fallback 用 `mimetypes.guess_type()` 兜底

### 4.4 LLM 多 part 注入(后端 → agent)

**触发点**:`/api/chat` 现有提交路径 + WS 路径都要支持

**改 `gateway.py` / `agent.py`**:
- 收到 user message + attachment_ids → 后端读取对应文件
- 构造 LLM message:
  ```python
  content = [{"type": "text", "text": user_text}]
  for att in attachments:
      if att.mime.startswith("image/"):
          data = base64.b64encode(open(att.file_path, "rb").read()).decode()
          content.append({
              "type": "image",
              "source": {"type": "base64", "media_type": att.mime, "data": data}
          })
      elif att.mime.startswith("text/") or att.mime in ("application/json", "application/pdf"):
          text = _read_text(att.file_path)  # 文本全文,PDF 待评估
          if len(text) > 20000:
              text = text[:20000] + f"\n\n... (已截断,原 {len(text)} 字符)"
          content.append({"type": "text", "text": f"--- attachment: {att.original_name} ---\n{text}\n--- end attachment ---"})
  ```
- message["content"] = content(Anthropic 风格多 part)
- 不再走纯 text 路径的 session_manager

**回退**:若 attachments 为空,继续走原纯 text 路径,**零回归**。

**WHY 文本读全文而非仅路径**:用户明确选择"标准多 part:文本全文 + 图片 base64"。这与 pathLinkify 反向贴图是不同层 — 反向贴图针对 LLM 写出的本地路径做预览;附件是 LLM 看不到本地文件,需要服务端把内容注入。

**WHY 不做 PDF 解析**:依赖 `pypdf` 之类,Round 2 不引入新依赖,PDF 走 `text/plain` fallback 报 mime 不支持(PDF 留到 Round 5 plugins 时一并做)。

### 4.5 草稿 per-project 持久化(前端)

**改 `frontend/src/components/ChatArea/hooks/useDraft.ts`**:

```ts
const draftKey = (projectId: string | null): string =>
  `nexus-draft-${projectId ?? "_none"}`;

// loadOnMount 接收 projectId 参数
loadOnMount: (projectId, conversationId, setInput) => {
  // 1) 优先读 per-project 草稿
  const draft = readDraftRaw(draftKey(projectId));
  if (draft && !conversationId) {
    setInput(draft.text);
    toast("已恢复草稿 " + formatAgo(draft.savedAt));
  }
};

// saveDraftEffect 不变(只是 key 拼接)
saveDraftEffect: (projectId, text) => writeDraft(draftKey(projectId), text);
```

**WHY key 用 `_none` 兜底**:active project 缺失时(启动前几帧)仍能存,避免丢草稿。

**WHY 不再"仅当 conversationId 为空时读"**:L1 的限制是"避免污染别人会话上下文"。per-project 草稿是另一回事 — 同一 project 下,切会话草稿应该还在。新逻辑:per-project 草稿总是读,无论 conversationId 是否有值。但 submit 成功后 clearDraft 仍要按当前 project key 清。

### 4.6 草稿冲突提示(前端,新)

**新文件**:`frontend/src/components/ChatArea/hooks/useDraftConflict.ts`

**机制**:
```ts
useEffect(() => {
  const onStorage = (e: StorageEvent) => {
    if (!e.key?.startsWith("nexus-draft-")) return;
    if (e.key !== draftKey(activeProjectId)) return;  // 别人项目的不管
    if (e.newValue === e.oldValue) return;             // 同源跳过
    toast(
      {
        title: "另一窗口刚修改草稿",
        body: "点恢复 / 保留本地版本",
        actions: [
          { label: "恢复远端", onClick: () => reloadRemote() },
          { label: "保留本地", onClick: () => writeLocal() }
        ],
        durationMs: 8000
      }
    );
  };
  window.addEventListener("storage", onStorage);
  return () => window.removeEventListener("storage", onStorage);
}, [activeProjectId]);
```

**WHY `storage` 事件而不是 BroadcastChannel**:`storage` 事件原生跨 tab / 跨 origin 不可见,Tauri 2 webview 多 tab / 跨域代理都能用,且零依赖。

### 4.7 草稿列表面板(前端)

**新文件**:`frontend/src/components/desktop/PreferencesModal.tsx` 加 "草稿" tab

**数据源**:扫 `localStorage` 中所有 `nexus-draft-*` key,反序列化后展示:
```ts
interface DraftListItem {
  projectId: string;
  projectName: string;  // 查 projects slice
  text: string;         // 截前 60 字
  savedAt: number;
}
```

**UI**:
- 表格行:[项目名] [预览 60 字] [相对时间] [跳回] [删除]
- "跳回" → 切 activeProjectId + setView("chat") + 关 modal
- "删除" → localStorage.removeItem(对应 key)
- 空状态:"暂无草稿" 灰字

**WHY 单一 modal tab 而非新 modal**:PreferencesModal 已统一管 Skills / MCP / 其它配置,草稿属同类(用户配置级别),加 tab 比新 modal 一致性更好。

### 4.8 文件清单(总览)

**后端**:
- 新增 `nexus/backend/routes/attachments.py`
- 新增 `nexus/backend/attachments.py`(storage)
- 新增 `tests/test_attachments.py`
- 修改 `nexus/backend/main.py`(include router)
- 修改 `nexus/backend/agent.py` 或 `gateway.py`(多 part 注入)

**前端**:
- 新增 `frontend/src/components/ChatArea/AttachmentBar.tsx`
- 新增 `frontend/src/components/ChatArea/hooks/useAttachments.ts`
- 新增 `frontend/src/components/ChatArea/hooks/useDraftConflict.ts`
- 修改 `frontend/src/components/ChatArea/Composer.tsx`
- 修改 `frontend/src/components/ChatArea/hooks/useDraft.ts`
- 修改 `frontend/src/components/ChatArea/index.tsx`
- 修改 `frontend/src/components/desktop/PreferencesModal.tsx`(加 tab)
- 修改 `frontend/src/components/desktop/styles/chat.css`

**测试**:
- 新增 `frontend/src/components/ChatArea/__tests__/AttachmentBar.test.tsx`
- 新增 `frontend/src/components/ChatArea/__tests__/useDraftConflict.test.ts`
- 修改 `frontend/src/components/ChatArea/__tests__/useDraft.test.ts`(per-project key)

---

## 5. 风险点与对策

| 风险 | 影响 | 对策 |
|------|------|------|
| F4:20MB 图片 base64 后 ≈ 27MB,Anthropic vision 限 5MB | LLM 拒收 | 客户端先缩放图片(> 2MB 用 canvas 缩到 1568px 长边,画质 0.85)再传 |
| F3:per-project 目录不在 → 上传失败 | 用户看不到附件 | 启动时 ensure uploads/ 存在 + 错误信息明确 |
| D2:storage 事件在 Tauri webview 内是否触发 | 跨 tab 同步失效 | 走 plan 验证步骤人工验;不触发时回退到 BroadcastChannel |
| F4:多 part 改造 agent 路径可能破现有 flow | 回归 | attachments 为空时走原纯 text 路径(零回归);专门写 e2e |
| D3:PreferencesModal tab 变多(3 → 4)拥挤 | UI 紧绷 | tab 用 chips / 滚动条而非分页 |
| F1:+ 按钮在窄屏挤压 composer | 移动端不能用 | 接受(本期只 macOS desktop);记录 Round 5 再处理 |
| 后端 mime sniff 误判 | 文件被当 image 注入失败 | text 文件统一走 attachment text part,不再用 magic bytes 判 |

---

## 6. 不在范围(留到后续轮)

- Voice / 录音输入 → 第 4 轮
- URL 引用 / 网络抓取附件 → Round 5+
- DAM(metadata / 搜索 / 标签)→ 与第 3 轮"消息级搜索"合并
- 附件版本管理 → DAM 之后
- 客户端图片压缩(pillow / canvas 高质量)→ Round 5+ 性能优化
- 跨设备同步草稿 → DMG 单机不涉及

---

## 7. SPEC 自检

- ✅ 没有 "TBD" / "TODO"(若 F1/F4 选项日后调整,在 plan 阶段覆盖)
- ✅ 各决策内部一致:per-project 存储 ↔ per-project 草稿,都走同一 project_id
- ✅ 范围聚焦:仅"上传 + 草稿",不混入搜索 / Voice / Plugins
- ✅ 无歧义:每个决策有 1 个具体方案 + 备选理由
- ✅ 文件路径 100% 完整,可直接给 subagent 执行

---

## 8. 签字 / 决策记录

| 决策点 | 选定方案 | 备选 |
|--------|---------|------|
| 入口 | + 按钮 + 拖拽 + paste | 全 dropzone / 仅拖拽 |
| 预览 | Composer 下方预览条 | inline 拼入 textarea / 仅 toast |
| 存储 | per-project uploads/ | 全局 ~/.nexus/ / 混合 |
| LLM 注入 | 多 part(文本全文 + 图片 base64) | 仅路径 / 智能截断 / tool 自读 |
| 草稿范围 | per-project 单草稿 | per-(project,conversation) / L1 增强 |
| 冲突提示 | storage 事件多 tab sync | 切 project 提示 / 静默 |
| 草稿列表 | PreferencesModal "草稿" tab | Composer 顶下拉 / 不做 |
| 文本处理 | 读全文,> 20000 截断 | 智能截断 / 路径注入 |

---

## 9. 后续流程

本 SPEC 通过用户 review 后,转交 `superpowers:writing-plans` 写 `docs/superpowers/plans/2026-07-24-round2-attachments-and-drafts-impl.md`,然后 subagent-driven 实施。
