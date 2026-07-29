import config
import pytest

from cmd_arg import parse_cmd


@pytest.mark.asyncio
async def test_zhihu_creator_cli_sets_urls_and_standard_browser_mode():
    await parse_cmd(
        [
            "--platform",
            "zhihu",
            "--type",
            "creator",
            "--creator_id",
            "https://www.zhihu.com/people/example",
            "--enable_cdp_mode",
            "no",
        ]
    )

    assert config.ZHIHU_CREATOR_URL_LIST == [
        "https://www.zhihu.com/people/example"
    ]
    assert config.ENABLE_CDP_MODE is False
