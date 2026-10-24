# planner_prototypes: the first star-only planner (superseded)

Kept as reference, not imported by the server.

- `qcost.py`: cost and ranking of plans over a star of units (one hub, linked units).
- `qrender.py`: rendering a ranked star plan as SQL with vg:plan advice.

Both were the first deliverable of the annotated-query-tree planner (decision_page, hand
plan validated against them). They were superseded by `vitalgraph/db/sparql_sql/qplan.py`,
which plans any connected join graph with DPccp, OPTIONAL and NOT EXISTS attachments and
the executor's column contract, and by `qcard.py` (the sampling cardinality oracle).
`vitalgraph/db/sparql_sql/qtree.py` (the annotated tree they read) is still live.
