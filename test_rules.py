import asyncio
from api.services.explain import run_explain_analyze
from api.services.rule_engine import RuleEngine
from api.db.connection import get_pool

async def test():
    pool = await get_pool()
    async with pool.acquire() as conn:
        query = """SELECT o.id, u.email, SUM(oi.quantity * oi.price) AS total
FROM orders o
JOIN users u ON u.id = o.user_id
JOIN order_items oi ON oi.order_id = o.id
WHERE o.status = 'completed'
GROUP BY o.id, u.email
ORDER BY total DESC
LIMIT 10"""
        plan = await run_explain_analyze(query, conn)
        engine = RuleEngine()
        issues = engine.analyze(plan)
        nodes = plan["nodes"]
        print("Nodes found:", len(nodes))
        print("Node types:", [n["type"] for n in nodes])
        print("Issues found:", len(issues))
        for i in issues:
            print(" ", i.severity, i.rule, i.title)

asyncio.run(test())
