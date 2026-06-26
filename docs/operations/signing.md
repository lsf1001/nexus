# macOS 代码签名与公证

> **本文件是 Nexus DMG 分发前的强制检查清单**。未签名的 DMG 用户首次打开
> 需要右键 → 打开(绕过 Gatekeeper);公证(notarize)通过后双击即可。

## 1. 现状(2026-06-25)

- `desktop/electron-builder.json` 的 `mac` 段只配了 `target=DMG` + icon,**未配签名**。
- 本地 `npm run desktop:pack` 会输出一行 `skipped macOS application code signing`,
  DMG 正常生成但 **未签名 + 未公证**。
- 产物:`release/Nexus-1.0.0-arm64.dmg`(176M)

## 2. 本地开发(不签)

不需要任何配置,直接跑:

```bash
cd desktop
npm run pack
# 输出 release/Nexus-1.0.0-arm64.dmg
# 用户首次打开:右键 → 打开(出现「来自身份不明开发者」提示)
```

## 3. 生产分发(必须签 + 公证)

### 3.1 硬件要求

- macOS 开发机(签名只能在 macOS 上跑,Linux/Windows 跨平台工具不能公证)
- Apple Developer ID 账号(年费 $99,实体或个人都行)
- 申请完到 App Store Connect 拿到:
  - **Developer ID Application** 证书(`Developer ID Application: Your Name (TEAMID)`)
  - **Developer ID Installer** 证书(给 .pkg 用,DMG 不需要)
  - Team ID(10 位字母数字)

### 3.2 本地配置

#### 方式 A:钥匙串里(开发机本人)

```bash
# 1. 下载证书到钥匙串(从 Apple Developer 网站)
open "https://developer.apple.com/account/resources/certificates/list"

# 2. 验证证书在钥匙串
security find-identity -p codesigning
# 应看到 'Developer ID Application: Your Name (TEAMID)'

# 3. 配 app-specific password 给 notarytool
# 登录 https://appleid.apple.com → App-Specific Passwords → 生成
# 存到 .env(不进 git):
echo 'APPLE_ID=you@example.com' >> .env
echo 'APPLE_APP_SPECIFIC_PASSWORD=abcd-efgh-ijkl-mnop' >> .env
echo 'APPLE_TEAM_ID=ABCDE12345' >> .env
```

#### 方式 B:CI 环境变量(推荐)

把证书导出成 `.p12` → base64 → 配到 CI secrets:

```bash
# 导出证书(从钥匙串拖到桌面,得到 identity.p12)
security import identity.p12 -P "<p12-password>"

# CI secrets:
# CSC_LINK       = base64 编码的 .p12 内容
# CSC_KEY_PASSWORD = .p12 密码
# APPLE_ID       = Apple ID 邮箱
# APPLE_APP_SPECIFIC_PASSWORD = app-specific password
# APPLE_TEAM_ID  = 10 位 Team ID
```

### 3.3 electron-builder 配置

在 `desktop/electron-builder.json` 的 `mac` 段加:

```json
{
  "mac": {
    "target": ["dmg"],
    "category": "public.app-category.productivity",
    "icon": "assets/icon.icns",
    "hardenedRuntime": true,
    "gatekeeperAssess": false,
    "entitlements": "build/entitlements.mac.plist",
    "entitlementsInherit": "build/entitlements.mac.plist",
    "notarize": true
  }
}
```

`build/entitlements.mac.plist`(最小权限集):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>com.apple.security.cs.allow-jit</key>
    <true/>
    <key>com.apple.security.cs.allow-unsigned-executable-memory</key>
    <true/>
    <key>com.apple.security.network.client</key>
    <true/>
    <key>com.apple.security.network.server</key>
    <true/>
    <key>com.apple.security.files.user-selected.read-write</key>
    <true/>
</dict>
</plist>
```

### 3.4 打包命令

```bash
cd desktop
# 本地有钥匙串:直接 pack
npm run pack

# CI 注入环境变量:electron-builder 自动读 CSC_LINK / CSC_KEY_PASSWORD
CSC_LINK="$(base64 -i identity.p12)" \
CSC_KEY_PASSWORD="<p12-password>" \
APPLE_ID="$APPLE_ID" \
APPLE_APP_SPECIFIC_PASSWORD="$APPLE_APP_SPECIFIC_PASSWORD" \
APPLE_TEAM_ID="$APPLE_TEAM_ID" \
  npm run pack
```

`electron-builder` 会自动:
1. 签名(用 `codesign --deep --force --options=runtime`)
2. 上传 Apple Notary Service(`xcrun notarytool submit`)
3. 等待公证完成(约 1-5 分钟)
4. Staple(`xcrun stapler staple`)

### 3.5 验证

```bash
# 1. 签名验证
codesign -dv --verbose=4 release/Nexus-1.0.0-arm64.dmg
# 应输出:Authority=Developer ID Application: Your Name (TEAMID)

# 2. 公证验证
xcrun stapler validate release/Nexus-1.0.0-arm64.dmg
# 应输出:The staple and ticket are valid.

# 3. Gatekeeper 验证
spctl --assess --type install release/Nexus-1.0.0-arm64.dmg
# 应输出:accepted
```

## 4. CI 集成(GitHub Actions 示例)

`.github/workflows/release.yml`:

```yaml
name: Release DMG
on:
  push:
    tags: ['v*']

jobs:
  build-macos:
    runs-on: macos-14
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: 22

      - name: Install deps
        run: npm install --prefix desktop

      - name: Build & sign & notarize
        env:
          CSC_LINK: ${{ secrets.MAC_CERT_P12_BASE64 }}
          CSC_KEY_PASSWORD: ${{ secrets.MAC_CERT_PASSWORD }}
          APPLE_ID: ${{ secrets.APPLE_ID }}
          APPLE_APP_SPECIFIC_PASSWORD: ${{ secrets.APPLE_APP_SPECIFIC_PASSWORD }}
          APPLE_TEAM_ID: ${{ secrets.APPLE_TEAM_ID }}
        run: npm run desktop:pack

      - name: Upload DMG
        uses: softprops/action-gh-release@v2
        with:
          files: release/*.dmg
```

## 5. 常见问题

| 问题 | 原因 | 解决 |
| --- | --- | --- |
| `skipped macOS application code signing` | 没找到 `Developer ID Application` 证书 | `security find-identity -p codesigning` 验证;CI 检查 `CSC_LINK` |
| `Unable to notarize` | 苹果账号密码错 / app-specific password 没配 | 重置 app-specific password,确认 `APPLE_ID` / `APPLE_APP_SPECIFIC_PASSWORD` |
| `The binary is not signed with a valid Developer ID certificate` | 用了 Apple Development 证书(不是 Developer ID) | Apple Developer 网站下载 `Developer ID Application` 类型 |
| DMG 双击「来自身份不明开发者」 | 漏 staple | `xcrun stapler staple <dmg>` 后重试 |
| 公证超时(>10 分钟) | 苹果服务端排队 | 正常现象,等 5-15 分钟,重试前 `xcrun notarytool history` 看状态 |

## 6. 升级检查清单(每次发版前)

- [ ] 证书未过期(Developer ID 证书 5 年有效)
- [ ] `CSC_LINK` / `APPLE_*` secrets 在 CI 仓库里
- [ ] `desktop/electron-builder.json` 配了 `hardenedRuntime` + `notarize: true`
- [ ] `build/entitlements.mac.plist` 存在且权限最小化
- [ ] 跑一次 `npm run desktop:pack` 验证 3.5 节的 3 条命令全过
