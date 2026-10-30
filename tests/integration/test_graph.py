"""图谱边写入与递归多跳遍历的集成测试。"""

from recallweaver.graph import GraphManager


def test_add_edge_creates_entities_and_relationships(test_database):
    """新增边时应自动创建实体，并持久化有向关系。"""
    graph = GraphManager()

    graph.add_edge("张三", "认识", "李四")
    graph.add_edge("李四", "住在", "北京")

    with test_database.get_connection() as conn:
        entities = conn.execute(
            "SELECT name FROM entities WHERE tenant_id = ?",
            ("default",),
        ).fetchall()
        edges = conn.execute(
            """
            SELECT subject.name AS subject, edge.predicate, object.name AS object
            FROM edges AS edge
            JOIN entities AS subject ON subject.id = edge.subject_id
            JOIN entities AS object ON object.id = edge.object_id
            WHERE edge.tenant_id = ?
            ORDER BY subject.name
            """,
            ("default",),
        ).fetchall()

    assert {row["name"] for row in entities} == {"张三", "李四", "北京"}
    assert [
        (row["subject"], row["predicate"], row["object"])
        for row in edges
    ] == [("张三", "认识", "李四"), ("李四", "住在", "北京")]


def test_get_neighbors_traverses_requested_number_of_hops(test_database):
    """递归 CTE 应按深度返回邻居，并能通过两跳找到北京。"""
    graph = GraphManager()
    graph.add_edge("张三", "认识", "李四")
    graph.add_edge("李四", "住在", "北京")

    one_hop = graph.get_neighbors("张三", depth=1)
    two_hops = graph.get_neighbors("张三", depth=2)

    assert {row["entity_name"] for row in one_hop} == {"李四"}
    assert {
        row["entity_name"]
        for row in two_hops
        if row["depth"] == 2
    } == {"北京"}
    beijing_path = next(row for row in two_hops if row["entity_name"] == "北京")
    assert beijing_path["relation"] == "认识 -> 住在"
