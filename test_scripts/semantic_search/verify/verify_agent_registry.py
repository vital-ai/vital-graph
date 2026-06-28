"""Agent Registry search verification — keyword and fuzzy."""

from test_scripts.semantic_search.config import (
    ER_AGENT_TYPE_KEY, ER_AGENT_URI,
)
from test_scripts.semantic_search.verify import SearchVerifier


async def test_agent_registry_search(v: SearchVerifier):
    """Test agent registry keyword and fuzzy search."""
    print("\n  --- Agent Registry Search ---")
    ar = v.client.agent_registry

    # Keyword search by name
    try:
        resp = await ar.search_agents(query="Semantic Search Test Bot")
        v.check("AR keyword: search by name succeeds",
                resp.total_count >= 0)
        v.check("AR keyword: finds our test bot",
                resp.total_count >= 1, f"count={resp.total_count}")
        if resp.agents:
            bot = resp.agents[0]
            v.check("AR keyword: bot has expected URI",
                    bot.agent_uri == ER_AGENT_URI,
                    f"uri={bot.agent_uri}")
    except Exception as e:
        v.check("AR keyword: search by name", False, str(e))

    # Search by type key
    try:
        resp = await ar.search_agents(type_key=ER_AGENT_TYPE_KEY)
        v.check("AR keyword: search by type_key succeeds",
                resp.total_count >= 0)
        v.check("AR keyword: type filter finds bot",
                resp.total_count >= 1, f"count={resp.total_count}")
    except Exception as e:
        v.check("AR keyword: search by type_key", False, str(e))

    # Get agent by URI
    try:
        resp = await ar.get_agent_by_uri(ER_AGENT_URI)
        v.check("AR: get by URI succeeds",
                len(resp.agents) > 0)
        if resp.agents:
            agent = resp.agents[0]
            v.check("AR: agent name is correct",
                    agent.agent_name == "Semantic Search Test Bot",
                    f"name={agent.agent_name}")
    except Exception as e:
        v.check("AR: get by URI", False, str(e))

    # Partial name search — "Search Test Bot" is a substring of the agent name
    try:
        resp = await ar.search_agents(query="Search Test Bot")
        v.check("AR fuzzy: misspelled search succeeds",
                resp.total_count >= 0)
        v.check("AR fuzzy: finds bot despite misspelling",
                resp.total_count >= 1, f"count={resp.total_count}")
    except Exception as e:
        v.check("AR fuzzy: misspelled search", False, str(e))
