import pytest

from store import bilibili


@pytest.mark.asyncio
async def test_bilibili_store_prefers_canonical_bv_url(monkeypatch):
    stored = []

    class FakeStore:
        async def store_content(self, content_item):
            stored.append(content_item)

    monkeypatch.setattr(
        bilibili.BiliStoreFactory, "create_store", staticmethod(lambda: FakeStore())
    )
    await bilibili.update_bilibili_video(
        {
            "View": {
                "aid": 617673117,
                "bvid": "BV19h4y1K7yM",
                "title": "测试",
                "desc": "",
                "pubdate": 0,
                "owner": {"mid": 1, "name": "作者"},
                "stat": {},
            }
        }
    )

    assert stored[0]["video_url"] == "https://www.bilibili.com/video/BV19h4y1K7yM"
