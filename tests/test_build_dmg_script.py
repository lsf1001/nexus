"""DMG 构建脚本的分发安全契约测试。"""

from __future__ import annotations

from pathlib import Path


def test_app_is_signed_before_dmg_staging() -> None:
    """进入 DMG 的 App 必须先完成签名，不能只签缓存副本。"""
    script_path = Path(__file__).parents[1] / "scripts" / "build_dmg.sh"
    script = script_path.read_text(encoding="utf-8")

    sign_position = script.index('bash "$ROOT_DIR/scripts/sign_app.sh" "$CACHE_DIR/${APP_NAME}.app"')
    stage_position = script.index('cp -R "$CACHE_DIR/${APP_NAME}.app" "$TMP_STAGE/"')
    image_position = script.index("hdiutil create")

    assert sign_position < stage_position < image_position
