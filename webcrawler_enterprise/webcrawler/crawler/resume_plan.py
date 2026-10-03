"""Decide how Resume should continue a website."""

from __future__ import annotations


def site_resume_action(
    *,
    resume_mode: bool,
    visited_count: int,
    frontier_pending: int,
) -> str:
    """Return how this website should be crawled.

    scratch
        Start button: wipe saved pages and begin from the first URL.
    fresh
        Resume, but this website has no saved pages yet.
    continue_queue
        Resume from the saved URL queue. Do not rediscover the whole site.
    rediscover_skip_visited
        Saved pages exist, but the URL queue was empty. Discover links again
        and skip every page already stored as visited.
    """
    if not resume_mode:
        return "scratch"
    if visited_count <= 0 and frontier_pending <= 0:
        return "fresh"
    if frontier_pending > 0:
        return "continue_queue"
    return "rediscover_skip_visited"
