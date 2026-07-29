from types import SimpleNamespace

import pytest

import config
from media_platform.zhihu import core
from media_platform.zhihu.client import ZhiHuClient
from model.m_zhihu import ZhihuContent


class FakeZhihuClient:
    async def get_note_by_keyword(self, keyword, page):
        return [SimpleNamespace(content_id=str(index)) for index in range(20)]


@pytest.mark.asyncio
async def test_zhihu_search_respects_requested_count(monkeypatch):
    crawler = core.ZhihuCrawler()
    crawler.zhihu_client = FakeZhihuClient()
    stored = []

    async def fake_store(content):
        stored.append(content.content_id)

    async def fake_comments(contents):
        return None

    async def no_sleep(_seconds):
        return None

    monkeypatch.setattr(config, "KEYWORDS", "测试")
    monkeypatch.setattr(config, "START_PAGE", 1)
    monkeypatch.setattr(config, "CRAWLER_MAX_NOTES_COUNT", 5)
    monkeypatch.setattr(config, "CRAWLER_MAX_SLEEP_SEC", 0)
    monkeypatch.setattr(core.zhihu_store, "update_zhihu_content", fake_store)
    monkeypatch.setattr(crawler, "batch_get_content_comments", fake_comments)
    monkeypatch.setattr(core.asyncio, "sleep", no_sleep)

    await crawler.search()

    assert stored == ["0", "1", "2", "3", "4"]
    assert config.CRAWLER_MAX_NOTES_COUNT == 5


@pytest.mark.asyncio
async def test_zhihu_comment_fetch_respects_max_count(monkeypatch):
    client = ZhiHuClient(
        headers={"cookie": ""}, playwright_page=None, cookie_dict={}
    )
    requested_limits = []

    async def fake_root_comments(content_id, content_type, offset, limit, order_by="score"):
        requested_limits.append(limit)
        return {
            "paging": {"is_end": False, "next": "https://example.test/?offset=next"},
            "data": [SimpleNamespace(comment_id=str(index)) for index in range(10)],
        }

    class FakeExtractor:
        @staticmethod
        def extract_offset(_paging):
            return "next"

        @staticmethod
        def extract_comments(_content, data):
            return data

    batches = []

    async def callback(items):
        batches.append(items)

    monkeypatch.setattr(config, "ENABLE_GET_SUB_COMMENTS", False)
    monkeypatch.setattr(client, "get_root_comments", fake_root_comments)
    client._extractor = FakeExtractor()
    content = ZhihuContent(content_id="1", content_type="article")

    comments = await client.get_note_all_comments(
        content, crawl_interval=0, callback=callback, max_count=1
    )

    assert requested_limits == [1]
    assert len(comments) == 1
    assert len(batches[0]) == 1
