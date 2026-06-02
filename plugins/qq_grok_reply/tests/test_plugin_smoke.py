import asyncio
from pathlib import Path
from typing import Any, cast

from ncatbot.testing import PluginTestHarness
from ncatbot.testing.factories.qq import private_message


def test_plugin_smoke_loads_disabled_without_sending():
    async def _run() -> None:
        async with PluginTestHarness(
            plugin_names=["qq_grok_reply"],
            plugins_dir=Path("plugins"),
        ) as harness:
            typed_harness = cast(Any, harness)
            assert "qq_grok_reply" in typed_harness.loaded_plugins

            await typed_harness.inject(private_message("你好", user_id="20001"))
            await typed_harness.settle()

            typed_harness.assert_api("send_private_msg").not_called()

    asyncio.run(_run())
