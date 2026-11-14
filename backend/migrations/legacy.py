"""Schema objects --autogenerate must leave alone (used by env.py and tests/test_migrations.py)."""

# Left over from an earlier design, no longer in the models but still holding rows: never offered as "drop" by
# --autogenerate. Remove an entry only together with a migration that moves or drops that data on purpose.
LEGACY_TABLES = {"ticket_gp_stages"}
LEGACY_COLUMNS = {("ticket_task_gps", "stage"), ("ticket_task_gps", "stage_at"), ("ticket_tasks", "workflow")}


def include_object(obj, name, type_, reflected, compare_to) -> bool:
    if type_ == "table":
        return name not in LEGACY_TABLES
    if type_ in ("index", "unique_constraint", "foreign_key_constraint", "column") and obj.table.name in LEGACY_TABLES:
        return False
    if type_ == "column" and reflected and compare_to is None:
        return (obj.table.name, name) not in LEGACY_COLUMNS
    return True
