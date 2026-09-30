"""Resume planning: finished work stays finished."""

from webcrawler.crawler.resume_plan import site_resume_action
from webcrawler.logger.crawl_logger import CrawlLogger


def test_start_always_scratches():
    assert (
        site_resume_action(resume_mode=False, visited_count=50, frontier_pending=10)
        == "scratch"
    )


def test_resume_with_saved_queue_does_not_restart():
    assert (
        site_resume_action(resume_mode=True, visited_count=80, frontier_pending=12)
        == "continue_queue"
    )


def test_resume_with_only_visited_pages_skips_them():
    assert (
        site_resume_action(resume_mode=True, visited_count=40, frontier_pending=0)
        == "rediscover_skip_visited"
    )


def test_resume_with_no_progress_starts_that_site():
    assert (
        site_resume_action(resume_mode=True, visited_count=0, frontier_pending=0)
        == "fresh"
    )


def test_page_lines_stay_out_of_the_gui_callback(tmp_path):
    seen: list[str] = []
    logger = CrawlLogger(tmp_path / "crawl_log.txt", on_message=seen.append)
    logger.page_visited("https://example.com/already-done", 200)
    logger.info("Heartbeat: visited=10 queued=3")
    logger.close()
    assert seen
    assert all("Visited page:" not in line for line in seen)
    assert any("Heartbeat:" in line for line in seen)
    text = (tmp_path / "crawl_log.txt").read_text(encoding="utf-8")
    assert "Visited page:" in text
